"""EvidenceProjectionTool — slices the bundle to just what one rule needs.

This is the quiet load-bearing piece of the whole design. A CSP question
receives the CSP header and the console violations, not a megabyte of DOM.
Small, factual prompts are what make a local 7B model viable here.

Crucially it is GENERIC: projection is driven by CollectorCode, never by
control identity. There is no `if control_id == "WEB-01"` anywhere in this
file, or anywhere else in the system.
"""
from __future__ import annotations

import json

from app.models.evidence import EvidenceBundle
from app.models.rules import CollectorCode, SecurityRule

#: Hard cap on serialized projection size, so no prompt can blow the context.
MAX_PROJECTION_CHARS = 6000

#: Headers worth showing for any header-driven control. Keeping this list
#: short is what keeps prompts small; it is a display filter, not rule logic.
_SECURITY_HEADERS = (
    "content-security-policy", "content-security-policy-report-only",
    "strict-transport-security", "x-content-type-options", "x-frame-options",
    "referrer-policy", "permissions-policy", "cross-origin-opener-policy",
    "cross-origin-embedder-policy", "cross-origin-resource-policy",
    "cache-control", "vary", "age", "pragma", "expires",
    "server", "x-powered-by", "x-aspnet-version", "set-cookie",
    "access-control-allow-origin", "access-control-allow-credentials",
)


def _headers(b: EvidenceBundle) -> dict:
    if not b.main_response:
        return {"observed": False,
                "note": "no main-document response was captured"}
    present = {k: v for k, v in b.main_response.headers.items()
               if k in _SECURITY_HEADERS}
    absent = [h for h in _SECURITY_HEADERS[:12] if h not in b.main_response.headers]
    return {
        "observed": True,
        "url": b.main_response.url,
        "status": b.main_response.status,
        "security_headers_present": present,
        "security_headers_absent": absent,
        "total_header_count": len(b.main_response.headers),
    }


def _cookies(b: EvidenceBundle) -> dict:
    return {
        "observed": bool(b.cookies) or b.has(CollectorCode.CK),
        "count": len(b.cookies),
        "cookies": [{
            "name": c.name, "domain": c.domain, "path": c.path,
            "secure": c.secure, "http_only": c.http_only,
            "same_site": c.same_site, "session_cookie": c.session_cookie,
        } for c in b.cookies[:25]],
        "note": "cookie VALUES are never collected; only attributes",
    }


def _storage(b: EvidenceBundle) -> dict:
    return {
        "observed": b.has(CollectorCode.WS),
        "count": len(b.storage),
        "entries": [{
            "area": s.area, "key": s.key, "value_length": s.value_length,
            "looks_like_jwt": s.looks_like_jwt,
            "looks_like_token": s.looks_like_token,
        } for s in b.storage[:30]],
        "note": "storage VALUES are never collected; only key names and shapes",
    }


def _network(b: EvidenceBundle) -> dict:
    insecure = [r.url for r in b.requests if r.is_insecure][:10]
    failed = [{"url": r.url, "failure": r.failure_text}
              for r in b.requests if r.failed][:10]
    return {
        "observed": b.has(CollectorCode.NET),
        "request_count": len(b.requests),
        "failed_count": sum(1 for r in b.requests if r.failed),
        "insecure_http_subresources": insecure,
        "insecure_count": len(insecure),
        "failed_requests": failed,
        "page_is_https": b.final_url.startswith("https://"),
    }


def _console(b: EvidenceBundle) -> dict:
    errs = [c for c in b.console if c.level in ("error", "pageerror", "warning")]
    return {
        "observed": b.has(CollectorCode.CON),
        "message_count": len(b.console),
        "errors_and_warnings": [{"level": c.level, "text": c.text[:200]}
                                for c in errs[:15]],
    }


def _dom(b: EvidenceBundle) -> dict:
    return {
        "observed": b.has(CollectorCode.DOM),
        "title": b.page_title,
        "final_url": b.final_url,
        "html_length": b.html_length,
        "link_count": len(b.links),
    }


def _scripts(b: EvidenceBundle) -> dict:
    third = [s for s in b.scripts if s.is_third_party]
    return {
        "observed": b.has(CollectorCode.JS),
        "script_count": len(b.scripts),
        "third_party_scripts": [{
            "src": s.src, "has_integrity": s.has_integrity,
            "has_crossorigin": s.has_crossorigin} for s in third[:20]],
        "third_party_without_integrity": sum(
            1 for s in third if not s.has_integrity),
        "secret_findings": [{"kind": f.kind, "location": f.location,
                             "confidence": f.confidence} for f in b.secrets[:20]],
        "note": "secret VALUES are never collected; only kind and location",
    }


def _forms(b: EvidenceBundle) -> dict:
    return {
        "observed": b.has(CollectorCode.FRM),
        "form_count": len(b.forms),
        "forms": [{
            "action": f.action, "method": f.method,
            "field_count": f.field_count, "field_names": f.field_names[:20],
            "has_password_field": f.has_password_field,
            "unlabelled_field_count": f.unlabelled_field_count,
        } for f in b.forms[:10]],
        "note": "no form was submitted; structure was inventoried only",
    }


def _tls(b: EvidenceBundle) -> dict:
    t = b.tls
    return {
        "observed": t.reachable,
        "protocol": t.protocol, "cipher": t.cipher,
        "subject_cn": t.subject_cn, "issuer": t.issuer,
        "san": t.san[:15], "not_after": t.not_after,
        "days_until_expiry": t.days_until_expiry,
        "hostname_matches": t.hostname_matches,
        "error": t.error,
    }


def _dns(b: EvidenceBundle) -> dict:
    d = b.dns
    return {"observed": not d.error, "a": d.a[:8], "aaaa": d.aaaa[:8],
            "cname": d.cname, "ns": d.ns[:8], "caa": d.caa,
            "dnssec_present": d.dnssec_present, "error": d.error}


def _redirect(b: EvidenceBundle) -> dict:
    return {
        "observed": b.http_scheme_reachable is not None,
        "http_probe_succeeded": b.http_scheme_reachable,
        "chain": [{"url": h.url, "status": h.status, "location": h.location}
                  for h in b.redirect_chain],
        "ends_on_https": bool(b.redirect_chain)
        and str(b.redirect_chain[-1].location or b.redirect_chain[-1].url
                ).startswith("https://"),
    }


def _error_page(b: EvidenceBundle) -> dict:
    e = b.error_page
    return {
        "observed": e.status is not None,
        "probed_url": e.probed_url, "status": e.status,
        "server_header": e.server_header, "x_powered_by": e.powered_by,
        "leaks_stack_trace": e.leaks_stack_trace,
        "leaks_internal_path": e.leaks_internal_path,
        "version_strings": e.version_strings,
    }


def _a11y(b: EvidenceBundle) -> dict:
    a = b.a11y
    return {
        "observed": b.has(CollectorCode.A11),
        "axe_available": a.axe_available,
        "axe_violation_count": a.violation_count,
        "axe_violations": a.violations[:15],
        "images_missing_alt": a.images_missing_alt,
        "unlabelled_inputs": a.unlabelled_inputs,
        "landmark_count": a.landmark_count,
        "lang_attribute": a.lang_attribute,
        "coverage_note": ("automated tooling covers only a minority of WCAG 2.2 "
                          "success criteria; this cannot establish AA conformance"),
    }


def _vitals(b: EvidenceBundle) -> dict:
    return {
        "observed": b.has(CollectorCode.CWV),
        "measurement_type": "LAB (single machine, single connection)",
        "lcp_ms": b.vitals.lcp_ms, "cls": b.vitals.cls, "fcp_ms": b.vitals.fcp_ms,
        "inp_ms": None,
        "inp_note": "INP requires real user input and was not measured",
        "field_data_note": ("this control asks for the 75th percentile of FIELD "
                            "data (CrUX/RUM), which a lab run cannot supply"),
    }


def _timing(b: EvidenceBundle) -> dict:
    return {"observed": bool(b.navigation_timing),
            "navigation_timing_ms": {k: round(v, 1) for k, v in
                                     b.navigation_timing.items()}}


def _third_party(b: EvidenceBundle) -> dict:
    return {"observed": b.has(CollectorCode.THIRD_PARTY),
            "origin_count": len(b.third_party_origins),
            "origins": b.third_party_origins[:30]}


def _well_known(b: EvidenceBundle) -> dict:
    w = b.well_known
    return {"observed": b.has(CollectorCode.WK),
            "security_txt_present": w.security_txt_present,
            "security_txt_fields": w.security_txt_fields,
            "robots_txt_present": w.robots_txt_present,
            "robots_disallow_count": w.robots_disallow_count}


def _cors(b: EvidenceBundle) -> dict:
    return {"observed": b.has(CollectorCode.CORS),
            "cross_origin_responses": dict(list(b.cors_headers.items())[:10])}


def _cache(b: EvidenceBundle) -> dict:
    if not b.main_response:
        return {"observed": False}
    h = b.main_response.headers
    return {"observed": True,
            "cache_control": h.get("cache-control"), "vary": h.get("vary"),
            "age": h.get("age"), "pragma": h.get("pragma"),
            "expires": h.get("expires"),
            "set_cookie_present": "set-cookie" in h}


def _self(b: EvidenceBundle) -> dict:
    """GOV-05 / IN-07: controls about the audit report itself."""
    return {"observed": True, "audit_metadata": b.audit_metadata,
            "target_url": b.target_url, "final_url": b.final_url,
            "collected_at": b.collected_at.isoformat(),
            "collectors_run": [c.value for c in b.collectors_run]}


def _shot(b: EvidenceBundle) -> dict:
    return {"observed": bool(b.screenshots), "screenshots": b.screenshots}


#: Collector code -> projector. Adding a collector means adding one entry.
_PROJECTORS = {
    CollectorCode.HDR: ("response_headers", _headers),
    CollectorCode.CK: ("cookies", _cookies),
    CollectorCode.WS: ("web_storage", _storage),
    CollectorCode.NET: ("network_requests", _network),
    CollectorCode.CON: ("console", _console),
    CollectorCode.DOM: ("document", _dom),
    CollectorCode.JS: ("scripts_and_secrets", _scripts),
    CollectorCode.FRM: ("forms", _forms),
    CollectorCode.LNK: ("document", _dom),
    CollectorCode.TLS: ("tls_certificate", _tls),
    CollectorCode.DNS: ("dns", _dns),
    CollectorCode.RDR: ("http_to_https_redirect", _redirect),
    CollectorCode.ERR: ("error_page_probe", _error_page),
    CollectorCode.A11: ("accessibility", _a11y),
    CollectorCode.CWV: ("web_vitals_lab", _vitals),
    CollectorCode.TIM: ("navigation_timing", _timing),
    CollectorCode.THIRD_PARTY: ("third_party_origins", _third_party),
    CollectorCode.WK: ("well_known", _well_known),
    CollectorCode.CORS: ("cors", _cors),
    CollectorCode.CACHE: ("cache_headers", _cache),
    CollectorCode.SELF: ("audit_metadata", _self),
    CollectorCode.SHOT: ("screenshots", _shot),
}


def project_for_rule(rule: SecurityRule, bundle: EvidenceBundle) -> dict:
    """Build the compact evidence view for one rule.

    Driven entirely by the rule's interpreted collector set. If a rule has no
    interpretation, it gets nothing — and the evaluator will return
    NOT_TESTABLE, which is the correct outcome rather than a guess.
    """
    codes = rule.interpretation.required_collectors if rule.interpretation else []
    out: dict = {}
    for code in codes:
        entry = _PROJECTORS.get(code)
        if not entry:
            continue
        key, fn = entry
        if key in out:
            continue
        try:
            out[key] = fn(bundle)
        except Exception as exc:                                # noqa: BLE001
            out[key] = {"observed": False, "error": f"projection failed: {exc}"}

    if not out:
        out["_note"] = ("no evidence collector maps to this control at the "
                        "passive test layer")
    return out


def serialize_projection(projection: dict) -> str:
    """JSON for the prompt, hard-capped so no prompt can blow the context."""
    text = json.dumps(projection, indent=1, default=str, ensure_ascii=False)
    if len(text) > MAX_PROJECTION_CHARS:
        text = text[:MAX_PROJECTION_CHARS] + "\n... [projection truncated]"
    return text


def evidence_corpus(projection: dict) -> str:
    """Flat lower-cased text of the projection, for the anti-fabrication check.

    A verdict citing an observed_value that does not appear in here did not
    come from the evidence, and is rejected.
    """
    return json.dumps(projection, default=str, ensure_ascii=False).lower()
