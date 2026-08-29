"""Anti-bot / rate-limit detection.

Policy, stated once: DETECT, STOP, RECORD, REPORT.

We never bypass, retry-with-backoff-and-persist, rotate a user agent, rotate
an IP, solve a challenge, or install stealth patches. `Rules/19_test_modes_safety.md`
forbids it and so does the brief. A block is a reportable finding about the
target's edge protections — not an obstacle to route around.
"""
from __future__ import annotations

import re

from app.models.assessment import AntiBotSignal

#: Status codes that mean "stop", with the kind we report them as.
_BLOCKING_STATUS = {
    401: "access_denied",
    403: "access_denied",
    429: "rate_limit",
    503: "service_unavailable",
}

#: Body markers. Matched case-insensitively against the first ~40 KB of HTML.
_BODY_MARKERS: list[tuple[str, re.Pattern]] = [
    ("captcha",           re.compile(r"\b(?:recaptcha|hcaptcha|turnstile|captcha)\b", re.I)),
    ("bot_verification",  re.compile(r"verify(?:ing)?\s+(?:you\s+are|that\s+you're)\s+(?:a\s+)?human", re.I)),
    ("bot_verification",  re.compile(r"\bchecking\s+your\s+browser\b", re.I)),
    ("unusual_traffic",   re.compile(r"unusual\s+traffic|suspicious\s+activity", re.I)),
    ("access_denied",     re.compile(r"\baccess\s+denied\b|\bforbidden\b", re.I)),
    ("rate_limit",        re.compile(r"\brate\s*limit(?:ed)?\b|too\s+many\s+requests", re.I)),
]

#: Header fingerprints of common edge protection, used only to describe.
_EDGE_HEADERS = ("cf-mitigated", "x-datadome", "x-akamai-bot", "x-iinfo")


def detect(
    *,
    status: int | None,
    headers: dict[str, str] | None,
    body: str | None,
    url: str,
) -> AntiBotSignal:
    """Inspect one response. Returns a signal with `detected` set appropriately."""
    headers = {k.lower(): v for k, v in (headers or {}).items()}

    if status in _BLOCKING_STATUS:
        kind = _BLOCKING_STATUS[status]
        detail = f"HTTP {status}"
        if retry := headers.get("retry-after"):
            detail += f", Retry-After: {retry}"
        for h in _EDGE_HEADERS:
            if h in headers:
                detail += f", {h}: {headers[h]}"
        return AntiBotSignal(detected=True, kind=kind, status=status,
                             url=url, detail=detail)

    if body:
        sample = body[:40_000]
        for kind, pattern in _BODY_MARKERS:
            if m := pattern.search(sample):
                return AntiBotSignal(
                    detected=True, kind=kind, status=status, url=url,
                    detail=f"page body matched {kind} marker: {m.group(0)!r}")

    return AntiBotSignal(detected=False)


def blocked_reason(signal: AntiBotSignal) -> str:
    """The exact sentence recorded on every dependent control."""
    return (
        f"Target returned a {signal.kind.replace('_', ' ')} response "
        f"({signal.detail}) at {signal.url}. The assessment was halted and no "
        f"bypass was attempted, per Rules/19_test_modes_safety.md."
    )
