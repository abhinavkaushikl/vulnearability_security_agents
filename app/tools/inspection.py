"""BrowserInspectionTool + NetworkInspectionTool.

Collectors that run against ONE instrumented navigation. Between them they
cover 15 of the 21 evidence codes, which is what keeps the traffic footprint
to roughly a single human page view.

Everything here is deterministic Python. No LLM, no judgement — these
functions observe and record, they do not decide anything.
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

from playwright.async_api import Page, Response

from app.models.evidence import (ConsoleRecord, CookieRecord, FormRecord,
                                 HeaderSet, RequestRecord, ScriptRecord,
                                 SecretFinding, StorageRecord, WebVitals)
from app.safety import redaction

log = logging.getLogger(__name__)


def registrable_host(url: str) -> str:
    """Best-effort scope host. Used to classify first vs third party."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:                                           # noqa: BLE001
        return ""
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) > 2 else host


def is_same_site(url: str, scope_host: str) -> bool:
    h = (urlparse(url).hostname or "").lower()
    return bool(h) and (h == scope_host or h.endswith("." + scope_host))


class NetworkRecorder:
    """Attaches to a Page and records the whole request/response conversation.

    Must be attached BEFORE navigation, or the main document is missed.
    Header values are redacted at capture (app/safety/redaction.py).
    """

    def __init__(self, scope_host: str):
        self.scope_host = scope_host
        self.requests: list[RequestRecord] = []
        self.headers: list[HeaderSet] = []
        self.console: list[ConsoleRecord] = []
        self.main_response: HeaderSet | None = None
        self.cors: dict[str, dict[str, str]] = {}
        self._by_url: dict[str, RequestRecord] = {}
        self._main_url: str | None = None

    def attach(self, page: Page, main_url: str) -> None:
        self._main_url = main_url
        page.on("request", self._on_request)
        page.on("response", self._on_response)
        page.on("requestfailed", self._on_failed)
        page.on("console", self._on_console)
        page.on("pageerror", self._on_page_error)

    # --- handlers ---------------------------------------------------------
    def _on_request(self, request) -> None:
        try:
            url = request.url
            rec = RequestRecord(
                url=redaction.redact_url(url),
                method=request.method,
                resource_type=request.resource_type,
                origin=(urlparse(url).hostname or ""),
                is_third_party=not is_same_site(url, self.scope_host),
                is_insecure=url.startswith("http://"),
            )
            self.requests.append(rec)
            self._by_url[url] = rec
        except Exception as exc:                                # noqa: BLE001
            log.debug("request record failed: %s", exc)

    def _on_response(self, response: Response) -> None:
        try:
            url = response.url
            raw = response.headers
            safe = redaction.redact_headers(raw)
            hs = HeaderSet(url=redaction.redact_url(url), status=response.status,
                           headers=safe,
                           resource_type=getattr(response.request, "resource_type", ""))
            self.headers.append(hs)

            if rec := self._by_url.get(url):
                rec.status = response.status
                rec.response_headers = safe

            # CORS headers on cross-origin responses (19_test_modes_safety.md
            # authorises "basic CORS inspection"). No control consumes these,
            # so they are reported as INFORMATIONAL evidence only.
            if not is_same_site(url, self.scope_host):
                cors = {k: v for k, v in safe.items()
                        if k.startswith("access-control-")}
                if cors:
                    self.cors[urlparse(url).hostname or url] = cors

            # First response for the requested document is the main response.
            if self.main_response is None and response.request.resource_type == "document":
                self.main_response = hs
        except Exception as exc:                                # noqa: BLE001
            log.debug("response record failed: %s", exc)

    def _on_failed(self, request) -> None:
        if rec := self._by_url.get(request.url):
            rec.failed = True
            rec.failure_text = (request.failure or "")[:200]
        else:
            self.requests.append(RequestRecord(
                url=redaction.redact_url(request.url), method=request.method,
                resource_type=request.resource_type, failed=True,
                failure_text=(request.failure or "")[:200],
                is_third_party=not is_same_site(request.url, self.scope_host),
            ))

    def _on_console(self, msg) -> None:
        try:
            self.console.append(ConsoleRecord(
                level=msg.type, text=msg.text[:500],
                location=str(msg.location.get("url", ""))[:200]
                if isinstance(msg.location, dict) else ""))
        except Exception:                                       # noqa: BLE001
            pass

    def _on_page_error(self, error) -> None:
        self.console.append(ConsoleRecord(level="pageerror", text=str(error)[:500]))

    # --- derived ----------------------------------------------------------
    @property
    def third_party_origins(self) -> list[str]:
        return sorted({r.origin for r in self.requests
                       if r.is_third_party and r.origin})


# --- in-page collectors ----------------------------------------------------

async def inspect_cookies(context, page_url: str) -> list[CookieRecord]:
    """WEB-05. Attributes only — the value is never stored."""
    out = []
    for c in await context.cookies():
        out.append(CookieRecord(
            name=c.get("name", ""),
            domain=c.get("domain", ""),
            path=c.get("path", "/"),
            secure=bool(c.get("secure")),
            http_only=bool(c.get("httpOnly")),
            same_site=c.get("sameSite"),
            expires=c.get("expires"),
            value_length=len(c.get("value", "")),
            session_cookie=(c.get("expires", -1) in (-1, None)),
        ))
    return out


_STORAGE_JS = """() => {
  const grab = (area, name) => {
    const out = [];
    try {
      for (let i = 0; i < area.length; i++) {
        const k = area.key(i);
        const v = area.getItem(k) ?? '';
        out.push({area: name, key: k, len: v.length, sample: v.slice(0, 96)});
      }
    } catch (e) { /* storage may be blocked; report nothing rather than guess */ }
    return out;
  };
  return [...grab(localStorage, 'localStorage'), ...grab(sessionStorage, 'sessionStorage')];
}"""


async def inspect_storage(page: Page) -> list[StorageRecord]:
    """WEB-06. Key names and shapes. Values are classified, never stored."""
    try:
        rows = await page.evaluate(_STORAGE_JS)
    except Exception as exc:                                    # noqa: BLE001
        log.debug("storage inspection failed: %s", exc)
        return []
    out = []
    for r in rows:
        sample = r.get("sample", "")
        out.append(StorageRecord(
            area=r["area"], key=r["key"], value_length=r.get("len", 0),
            looks_like_jwt=redaction.looks_like_jwt(sample),
            looks_like_token=redaction.looks_like_token(sample),
        ))
    return out


_FORMS_JS = """() => Array.from(document.forms).map(f => {
  const fields = Array.from(f.elements).filter(e => e.name || e.id || e.type);
  const unlabelled = fields.filter(e => {
    if (['submit','button','hidden','image','reset'].includes(e.type)) return false;
    if (e.getAttribute('aria-label') || e.getAttribute('aria-labelledby')) return false;
    if (e.id && document.querySelector(`label[for="${CSS.escape(e.id)}"]`)) return false;
    return !e.closest('label');
  }).length;
  return {
    action: f.action || '', method: (f.method || 'get').toLowerCase(),
    fieldCount: fields.length,
    names: fields.map(e => e.name || e.id || '').filter(Boolean).slice(0, 40),
    types: fields.map(e => e.type || '').filter(Boolean).slice(0, 40),
    hasPassword: fields.some(e => e.type === 'password'),
    unlabelled: unlabelled,
    autocompleteOff: (f.getAttribute('autocomplete') || '').toLowerCase() === 'off',
  };
})"""


async def inspect_forms(page: Page) -> list[FormRecord]:
    """PRIV-02, A11Y-03, IAM-03. Structure only — no form is ever submitted."""
    try:
        rows = await page.evaluate(_FORMS_JS)
    except Exception as exc:                                    # noqa: BLE001
        log.debug("form inspection failed: %s", exc)
        return []
    return [FormRecord(
        action=redaction.redact_url(r.get("action", "")),
        method=r.get("method", "get"),
        over_https=str(r.get("action", "")).startswith("https://")
        or not str(r.get("action", "")).startswith("http://"),
        field_count=r.get("fieldCount", 0),
        field_names=r.get("names", []),
        field_types=r.get("types", []),
        has_password_field=r.get("hasPassword", False),
        unlabelled_field_count=r.get("unlabelled", 0),
        autocomplete_off=r.get("autocompleteOff", False),
    ) for r in rows]


_SCRIPTS_JS = """() => Array.from(document.querySelectorAll('script')).map(s => ({
  src: s.src || '', inline: !s.src,
  integrity: !!s.integrity, crossorigin: s.crossOrigin !== null,
  len: (s.textContent || '').length,
}))"""


async def inspect_scripts(page: Page, scope_host: str) -> list[ScriptRecord]:
    """WEB-07 (SRI on cross-origin scripts)."""
    try:
        rows = await page.evaluate(_SCRIPTS_JS)
    except Exception as exc:                                    # noqa: BLE001
        log.debug("script inspection failed: %s", exc)
        return []
    return [ScriptRecord(
        src=r.get("src", ""), inline=r.get("inline", False),
        is_third_party=bool(r.get("src")) and not is_same_site(r["src"], scope_host),
        has_integrity=r.get("integrity", False),
        has_crossorigin=r.get("crossorigin", False),
        body_length=r.get("len", 0),
    ) for r in rows]


async def inspect_links(page: Page) -> list[str]:
    """LNK. Inventory only — links are recorded, never followed."""
    try:
        return await page.evaluate(
            "() => Array.from(document.querySelectorAll('a[href]'))"
            ".map(a => a.href).slice(0, 500)")
    except Exception:                                           # noqa: BLE001
        return []


_VITALS_JS = """() => new Promise(resolve => {
  const out = {lcp: null, cls: null, fcp: null};
  try {
    for (const e of performance.getEntriesByType('paint'))
      if (e.name === 'first-contentful-paint') out.fcp = e.startTime;
    new PerformanceObserver(list => {
      const es = list.getEntries();
      if (es.length) out.lcp = es[es.length - 1].startTime;
    }).observe({type: 'largest-contentful-paint', buffered: true});
    let cls = 0;
    new PerformanceObserver(list => {
      for (const e of list.getEntries()) if (!e.hadRecentInput) cls += e.value;
      out.cls = cls;
    }).observe({type: 'layout-shift', buffered: true});
  } catch (e) { /* unsupported: leave nulls, never estimate */ }
  setTimeout(() => resolve(out), 900);
})"""

_NAVTIMING_JS = """() => {
  const n = performance.getEntriesByType('navigation')[0];
  if (!n) return {};
  return {
    dns_time: n.domainLookupEnd - n.domainLookupStart,
    tcp_time: n.connectEnd - n.connectStart,
    tls_time: n.secureConnectionStart > 0 ? n.connectEnd - n.secureConnectionStart : 0,
    ttfb: n.responseStart - n.startTime,
    dom_content_loaded: n.domContentLoadedEventEnd - n.startTime,
    page_load_time: n.loadEventEnd > 0 ? n.loadEventEnd - n.startTime : n.duration,
    redirect_count: n.redirectCount || 0,
    transfer_size: n.transferSize || 0,
  };
}"""


async def collect_navigation_timing(page: Page) -> dict[str, float]:
    """TIM. PerformanceNavigationTiming. Missing values are omitted, not zeroed."""
    try:
        return await page.evaluate(_NAVTIMING_JS) or {}
    except Exception as exc:                                    # noqa: BLE001
        log.debug("navigation timing failed: %s", exc)
        return {}


async def collect_web_vitals(page: Page) -> WebVitals:
    """CWV. LAB measurements. INP stays None — it needs real user input.

    PERF-01 asks for the 75th percentile of FIELD data and says lab is
    supplementary. These numbers are reported as INFORMATIONAL, never graded.
    """
    try:
        v = await page.evaluate(_VITALS_JS)
    except Exception as exc:                                    # noqa: BLE001
        log.debug("web vitals failed: %s", exc)
        return WebVitals()
    return WebVitals(lcp_ms=v.get("lcp"), cls=v.get("cls"), fcp_ms=v.get("fcp"))


async def scan_page_secrets(page: Page, html: str,
                            scripts: list[ScriptRecord]) -> list[SecretFinding]:
    """WEB-09. Scans HTML plus same-origin script bodies.

    Matched secrets are NEVER stored — only kind, location and a redacted
    neighbourhood. See app/safety/redaction.py.
    """
    findings: list[dict] = []
    findings += redaction.scan_for_secrets(html, "document")
    findings += redaction.find_source_maps(html, "document")

    inline_idx = 0
    for s in scripts:
        if s.inline:
            inline_idx += 1
            continue
        if not s.src or s.is_third_party:
            continue      # do not fetch third-party bodies: out of scope
        try:
            body = await page.evaluate(
                """async (u) => { try { const r = await fetch(u);
                     return (await r.text()).slice(0, 400000); } catch(e){ return ''; } }""",
                s.src)
        except Exception:                                       # noqa: BLE001
            continue
        if body:
            findings += redaction.scan_for_secrets(body, s.src)
            findings += redaction.find_source_maps(body, s.src)

    return [SecretFinding(**f) for f in findings[:60]]
