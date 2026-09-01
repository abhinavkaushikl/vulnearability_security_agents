"""Out-of-band collectors: TLS, DNS, redirect chain, well-known, benign 404.

These do not use the browser. Two reasons:

  * Playwright cannot expose a certificate chain or a DNS record, and NET-02,
    NET-04 and NET-05 need exactly those.
  * DNS resolution costs the target nothing, so it is free evidence.

Total additional traffic: one TLS handshake, one HTTP request to test the
scheme redirect, two well-known fetches, one benign 404. Five requests.
"""
from __future__ import annotations

import asyncio
import logging
import re
import socket
import ssl
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

try:                                    # optional: only needed under CERT_NONE
    from cryptography import x509
    from cryptography.x509.oid import ExtensionOID, NameOID
except ImportError:                     # pragma: no cover - degrades to error
    x509 = None                         # type: ignore[assignment]
    ExtensionOID = NameOID = None       # type: ignore[assignment]

from app.models.evidence import (DnsEvidence, ErrorPageEvidence, RedirectHop,
                                 TlsEvidence, WellKnownEvidence)
from app.safety import redaction

log = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (compatible; SecurityAssessment/1.0; +passive-audit)"
_VERSION_RE = re.compile(
    r"\b([A-Za-z][A-Za-z0-9_+-]{1,24})[/ ]v?(\d+\.\d+(?:\.\d+)?)\b")
_STACK_RE = re.compile(
    r"Traceback \(most recent call last\)|at [\w.$]+\([\w./]+:\d+\)|"
    r"\bStack ?trace\b|Exception in thread|\bat java\.|System\.\w+Exception", re.I)
_PATH_RE = re.compile(
    r"(?:/(?:var|usr|home|opt|srv|etc)/[\w./-]{4,}|[A-Z]:\\\\[\w\\\\.-]{4,})")


async def collect_tls(hostname: str, port: int = 443,
                      timeout: float = 10.0) -> TlsEvidence:
    """NET-02, NET-04. One handshake against the authorized target."""
    ev = TlsEvidence()

    def _handshake() -> TlsEvidence:
        out = TlsEvidence()
        ctx = ssl.create_default_context()
        ctx.check_hostname = False          # we want to REPORT a mismatch
        ctx.verify_mode = ssl.CERT_NONE     # not to fail on it
        try:
            with socket.create_connection((hostname, port), timeout=timeout) as sock:
                with ctx.wrap_socket(sock, server_hostname=hostname) as tls:
                    out.reachable = True
                    out.protocol = tls.version()
                    cipher = tls.cipher()
                    out.cipher = cipher[0] if cipher else None
                    cert = tls.getpeercert()
                    if not cert:
                        # verify_mode=CERT_NONE (set above so a hostname
                        # mismatch is REPORTED, not raised) makes the stdlib
                        # skip decoding, so getpeercert() is empty. The DER is
                        # still on the wire — parse it ourselves.
                        der = tls.getpeercert(binary_form=True)
                        if der:
                            _parse_der(der, out, hostname)
                        else:
                            out.error = "peer presented no certificate"
                        return out
                    subject = dict(x[0] for x in cert.get("subject", ()))
                    issuer = dict(x[0] for x in cert.get("issuer", ()))
                    out.subject_cn = subject.get("commonName")
                    out.issuer = issuer.get("commonName") or issuer.get("organizationName")
                    out.san = [v for k, v in cert.get("subjectAltName", ()) if k == "DNS"]
                    out.not_before = cert.get("notBefore")
                    out.not_after = cert.get("notAfter")
                    if out.not_after:
                        exp = datetime.strptime(
                            out.not_after, "%b %d %H:%M:%S %Y %Z"
                        ).replace(tzinfo=timezone.utc)
                        out.days_until_expiry = (
                            exp - datetime.now(timezone.utc)).days
                    out.hostname_matches = _hostname_matches(hostname, out.san,
                                                             out.subject_cn)
        except Exception as exc:                                # noqa: BLE001
            out.error = f"{type(exc).__name__}: {exc}"
        return out

    try:
        ev = await asyncio.wait_for(asyncio.to_thread(_handshake), timeout + 5)
    except Exception as exc:                                    # noqa: BLE001
        ev.error = f"{type(exc).__name__}: {exc}"
    return ev


def _parse_der(der: bytes, out: TlsEvidence, hostname: str) -> None:
    """Populate cert fields from raw DER, mirroring the getpeercert() path.

    NET-02 and NET-04 need the subject, issuer and expiry, none of which the
    stdlib decodes under CERT_NONE. Dates are rendered in the same format
    getpeercert() uses so both paths are indistinguishable downstream.
    """
    if x509 is None:
        out.error = ("peer certificate not parseable: install `cryptography` "
                     "to decode it under CERT_NONE")
        return
    try:
        cert = x509.load_der_x509_certificate(der)
    except Exception as exc:                                    # noqa: BLE001
        out.error = f"peer certificate not parseable: {type(exc).__name__}"
        return

    def _first(name, oid) -> str | None:
        attrs = name.get_attributes_for_oid(oid)
        return attrs[0].value if attrs else None

    out.subject_cn = _first(cert.subject, NameOID.COMMON_NAME)
    out.issuer = (_first(cert.issuer, NameOID.COMMON_NAME)
                  or _first(cert.issuer, NameOID.ORGANIZATION_NAME))
    try:
        ext = cert.extensions.get_extension_for_oid(
            ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
        out.san = ext.value.get_values_for_type(x509.DNSName)
    except x509.ExtensionNotFound:
        out.san = []

    fmt = "%b %e %H:%M:%S %Y GMT"
    not_before = cert.not_valid_before_utc
    not_after = cert.not_valid_after_utc
    out.not_before = not_before.strftime(fmt)
    out.not_after = not_after.strftime(fmt)
    out.days_until_expiry = (not_after - datetime.now(timezone.utc)).days
    out.hostname_matches = _hostname_matches(hostname, out.san, out.subject_cn)


def _hostname_matches(hostname: str, san: list[str], cn: str | None) -> bool:
    names = list(san) + ([cn] if cn else [])
    host = hostname.lower()
    for name in names:
        n = (name or "").lower()
        if n == host:
            return True
        if n.startswith("*.") and host.count(".") >= n.count(".") - 1:
            if host.endswith(n[1:]):
                return True
    return False


async def collect_dns(hostname: str) -> DnsEvidence:
    """NET-05, NET-06. Resolved off-target — costs the site nothing."""
    ev = DnsEvidence()
    try:
        import dns.resolver
    except ImportError:
        ev.error = "dnspython not installed"
        return ev

    def _q(rtype: str) -> list[str]:
        try:
            ans = dns.resolver.resolve(hostname, rtype, lifetime=6.0)
            return [r.to_text() for r in ans]
        except Exception:                                       # noqa: BLE001
            return []

    try:
        res = await asyncio.gather(*[asyncio.to_thread(_q, t) for t in
                                     ("A", "AAAA", "CNAME", "NS", "MX", "CAA")])
        ev.a, ev.aaaa, ev.cname, ev.ns, ev.mx, ev.caa = res
        dnskey = await asyncio.to_thread(_q, "DNSKEY")
        ev.dnssec_present = bool(dnskey)
    except Exception as exc:                                    # noqa: BLE001
        ev.error = f"{type(exc).__name__}: {exc}"
    return ev


async def collect_redirect_chain(url: str) -> tuple[list[RedirectHop], bool | None]:
    """NET-01. Does http:// redirect to https:// without serving content?

    Returns (hops, http_scheme_reachable). `http_scheme_reachable` is None when
    the probe itself failed, so an unreachable host is never read as "no
    insecure endpoint".
    """
    parsed = urlparse(url)
    http_url = f"http://{parsed.netloc}{parsed.path or '/'}"
    hops: list[RedirectHop] = []
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=12.0,
                                     headers={"User-Agent": _UA},
                                     verify=False) as client:
            current = http_url
            for _ in range(6):
                r = await client.get(current)
                loc = r.headers.get("location")
                hops.append(RedirectHop(url=redaction.redact_url(current),
                                        status=r.status_code, location=loc))
                if not loc or not (300 <= r.status_code < 400):
                    break
                current = str(httpx.URL(current).join(loc))
            return hops, True
    except Exception as exc:                                    # noqa: BLE001
        log.debug("redirect probe failed: %s", exc)
        return hops, None


async def collect_well_known(base_url: str) -> WellKnownEvidence:
    """security.txt and robots.txt. Two cheap GETs.

    Rules/19_test_modes_safety.md names security.txt as a legitimate passive
    check, though no control in the 144 consumes it — reported as
    INFORMATIONAL supporting evidence for IR-05.
    """
    ev = WellKnownEvidence()
    parsed = urlparse(base_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10.0,
                                     headers={"User-Agent": _UA}) as client:
            try:
                r = await client.get(f"{root}/.well-known/security.txt")
                if r.status_code == 200 and len(r.text) < 20000:
                    ev.security_txt_present = True
                    ev.security_txt_fields = sorted({
                        line.split(":", 1)[0].strip().lower()
                        for line in r.text.splitlines()
                        if ":" in line and not line.strip().startswith("#")
                    })
            except Exception:                                   # noqa: BLE001
                pass
            try:
                r = await client.get(f"{root}/robots.txt")
                if r.status_code == 200:
                    ev.robots_txt_present = True
                    ev.robots_disallow_count = sum(
                        1 for ln in r.text.splitlines()
                        if ln.strip().lower().startswith("disallow:"))
            except Exception:                                   # noqa: BLE001
                pass
    except Exception as exc:                                    # noqa: BLE001
        log.debug("well-known probe failed: %s", exc)
    return ev


async def probe_error_page(base_url: str) -> ErrorPageEvidence:
    """WEB-10, APP-07. ONE benign GET on a random path.

    Non-destructive by construction: a GET for a path that cannot exist. We
    read what the server volunteers about itself in an error response. No
    fuzzing, no enumeration, no repeated probing.
    """
    parsed = urlparse(base_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    probe = f"{root}/assessment-probe-{uuid.uuid4().hex[:12]}"
    ev = ErrorPageEvidence(probed_url=probe)
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=10.0,
                                     headers={"User-Agent": _UA}) as client:
            r = await client.get(probe)
            ev.status = r.status_code
            ev.server_header = r.headers.get("server")
            ev.powered_by = r.headers.get("x-powered-by")
            body = r.text[:60000]
            ev.body_length = len(r.text)
            ev.leaks_stack_trace = bool(_STACK_RE.search(body))
            ev.leaks_internal_path = bool(_PATH_RE.search(body))
            versions = set()
            for header in (ev.server_header, ev.powered_by,
                           r.headers.get("x-aspnet-version")):
                if header and (m := _VERSION_RE.search(header)):
                    versions.add(f"{m.group(1)}/{m.group(2)}")
            ev.version_strings = sorted(versions)
    except Exception as exc:                                    # noqa: BLE001
        log.debug("error-page probe failed: %s", exc)
    return ev
