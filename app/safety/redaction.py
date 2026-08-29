"""Redaction at capture time.

Secrets are stripped on the way INTO the evidence bundle, not on the way out
to a report. A value that is never written cannot leak through a log, a trace,
a spreadsheet or an LLM prompt.

What the controls actually need:
  * WEB-05 needs cookie FLAGS  -> we keep name/domain/path/secure/httponly/samesite
  * WEB-06 needs storage KEYS  -> we keep key names and value shapes
  * WEB-09 needs to know a secret EXISTS -> we keep kind + location, never the value
"""
from __future__ import annotations

import math
import re
from collections import Counter

#: Headers whose values are never stored, in any form.
SENSITIVE_HEADERS = frozenset({
    "authorization", "proxy-authorization", "cookie", "set-cookie",
    "x-api-key", "x-auth-token", "x-csrf-token", "x-xsrf-token",
    "api-key", "x-access-token", "x-session-token",
})

#: Query parameters that commonly carry credentials or session material.
SENSITIVE_PARAMS = frozenset({
    "token", "access_token", "id_token", "refresh_token", "api_key", "apikey",
    "password", "passwd", "pwd", "secret", "client_secret", "session",
    "sessionid", "sid", "auth", "signature", "sig", "code",
})

_JWT_RE = re.compile(r"^eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*$")

#: WEB-09 patterns. Each entry is (kind, compiled pattern).
SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("aws_access_key",   re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("private_key",      re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("google_api_key",   re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("slack_token",      re.compile(r"\bxox[abprs]-[0-9A-Za-z-]{10,}\b")),
    ("github_token",     re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("stripe_key",       re.compile(r"\b[sr]k_(?:live|test)_[0-9A-Za-z]{16,}\b")),
    ("jwt",              re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+")),
    ("bearer_literal",   re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{20,}={0,2}")),
    ("basic_auth_url",   re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s:@]+@")),
    ("password_assign",  re.compile(r"""["']?pass(?:word|wd)?["']?\s*[:=]\s*["'][^"']{4,}["']""", re.I)),
    ("private_ip",       re.compile(r"\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b")),
]

_TOKENISH = re.compile(r"^[A-Za-z0-9_\-+/=.]{24,}$")


def shannon_entropy(s: str) -> float:
    """Bits per character. Used as a weak signal, never as the sole trigger."""
    if not s:
        return 0.0
    counts = Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def looks_like_jwt(value: str) -> bool:
    return bool(_JWT_RE.match(value.strip()))


def looks_like_token(value: str) -> bool:
    """High-entropy, token-shaped string. Deliberately conservative."""
    v = value.strip()
    if len(v) < 24 or not _TOKENISH.match(v):
        return False
    return shannon_entropy(v) >= 3.5


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    """Lower-case keys, replace sensitive values with a shape descriptor.

    Set-Cookie is special: WEB-05 needs its ATTRIBUTES, so we keep the
    attribute string and drop only the value.
    """
    out: dict[str, str] = {}
    for raw_key, value in headers.items():
        key = raw_key.lower()
        if key == "set-cookie":
            out[key] = redact_set_cookie(value)
        elif key in SENSITIVE_HEADERS:
            out[key] = f"<redacted len={len(value)}>"
        else:
            out[key] = value
    return out


def redact_set_cookie(value: str) -> str:
    """`sid=abc123; Secure; HttpOnly` -> `sid=<redacted len=6>; Secure; HttpOnly`."""
    parts = value.split(";")
    if not parts:
        return value
    head = parts[0]
    if "=" in head:
        name, _, val = head.partition("=")
        parts[0] = f"{name}=<redacted len={len(val)}>"
    return ";".join(parts)


def redact_url(url: str) -> str:
    """Replace sensitive query-parameter values. Used for PRIV-10 evidence."""
    if "?" not in url:
        return url
    base, _, query = url.partition("?")
    kept = []
    for pair in query.split("&"):
        key, sep, val = pair.partition("=")
        if sep and (key.lower() in SENSITIVE_PARAMS or looks_like_token(val)):
            kept.append(f"{key}=<redacted len={len(val)}>")
        else:
            kept.append(pair)
    return f"{base}?{'&'.join(kept)}"


def context_hint(text: str, start: int, end: int, window: int = 24) -> str:
    """A neighbourhood around a finding, with the finding itself removed.

    Gives a human enough to locate the secret in the source without the
    report becoming a place secrets live.
    """
    left = text[max(0, start - window):start].replace("\n", " ")
    right = text[end:end + window].replace("\n", " ")
    return f"...{left}<REDACTED:{end - start} chars>{right}..."


def scan_for_secrets(text: str, location: str) -> list[dict]:
    """WEB-09. Returns findings WITHOUT the matched values.

    Pattern matches are high confidence. Entropy alone is reported at low
    confidence, because minified bundles are full of high-entropy strings
    that are not secrets — an honest scanner says so rather than crying wolf.
    """
    findings: list[dict] = []
    seen: set[tuple[str, int]] = set()

    for kind, pattern in SECRET_PATTERNS:
        for m in pattern.finditer(text):
            key = (kind, m.start())
            if key in seen:
                continue
            seen.add(key)
            findings.append({
                "kind": kind,
                "location": location,
                "context_hint": context_hint(text, m.start(), m.end()),
                "confidence": 0.55 if kind == "private_ip" else 0.9,
            })
            if len(findings) >= 50:      # bound the report
                return findings
    return findings


def find_source_maps(text: str, location: str) -> list[dict]:
    """WEB-09 also covers source maps: they can re-expose original sources."""
    out = []
    for m in re.finditer(r"//[#@]\s*sourceMappingURL=(\S+)", text):
        out.append({
            "kind": "source_map_reference",
            "location": location,
            "context_hint": f"sourceMappingURL={m.group(1)[:80]}",
            "confidence": 1.0,
        })
    return out


def redact_secrets_in_text(text: str) -> str:
    """Replace every SECRET_PATTERNS match in a body with a placeholder.

    Applied to captured HTML and script bodies immediately AFTER the WEB-09
    scan has recorded that a secret exists. The finding survives; the secret
    does not. Anything downstream — an LLM prompt, a DOM excerpt in a report,
    a debug log — then works on text that no longer contains live credentials.
    """
    if not text:
        return text
    out = text
    for kind, pattern in SECRET_PATTERNS:
        out = pattern.sub(lambda m: f"<REDACTED:{kind}:{len(m.group(0))}>", out)
    return out
