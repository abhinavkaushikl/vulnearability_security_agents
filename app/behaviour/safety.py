"""What the behaviour agent may and may not touch.

The agent is autonomous, which makes this module the thing that keeps it
honest. It is a classifier, not a set of `if` statements scattered through
the executor: every element the observer surfaces is classified once, the
classification travels with the element, and `executor.py` asks only
`is this cleared?`.

The boundary follows the product brief and §11 of CLAUDE.md:

  * FORBIDDEN — never dispatched, under any plan, at any autonomy level.
    Irreversible or financial: place order, pay, confirm purchase, delete,
    close account, unsubscribe, transfer funds. Also: real credential
    submission and anything that would send data to a third party on the
    user's behalf.
  * SENSITIVE — the agent may approach and observe, never complete. A login
    form may be focused and its client-side validation observed; it is never
    submitted with credentials. A checkout page may be *reached*; the button
    that charges a card may not be pressed.
  * SAFE — ordinary browsing.

Matching is on the accessible name, the visible text, the value, the name and
id attributes, and — for links — the path. Substring matching on short words
produces false positives ("payment history" is not a payment), so patterns
are matched as whole words with `\b` anchors.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from app.behaviour.models import ElementKind, FormModel, InteractiveElement, Risk

# ── the deny list ─────────────────────────────────────────────────────────
#
# Each entry is (pattern, reason). The reason is carried onto the element and
# ends up in the report, so a user can see exactly why the agent stopped.

_FORBIDDEN: list[tuple[str, str]] = [
    (r"\b(place|submit|confirm|complete|finalis[sz]e)\s+(the|your|my)?\s*order\b",
     "completes a purchase"),
    (r"\b(buy|purchase)\s+(it\s+)?now\b", "completes a purchase"),
    (r"\bpay\s+(now|securely|with|by)\b", "initiates a payment"),
    (r"\b(make|confirm|authorise|authorize)\s+(a\s+)?payment\b",
     "initiates a payment"),
    (r"\bcomplete\s+purchase\b", "completes a purchase"),
    (r"\bplace\s+bid\b", "places a financial commitment"),
    (r"\b(transfer|send)\s+(money|funds)\b", "moves money"),
    (r"\bdelete\b", "destructive"),
    (r"\bremove\s+account\b", "destructive"),
    (r"\b(close|deactivate|terminate)\s+(my\s+)?account\b", "destructive"),
    (r"\bcancel\s+(order|subscription|booking|reservation)\b", "destructive"),
    (r"\bunsubscribe\b", "destructive"),
    (r"\bempty\s+(the\s+)?(cart|basket|trash|bin)\b", "destructive"),
    (r"\b(reset|change)\s+password\b", "changes account state"),
    (r"\brequest\s+(a\s+)?refund\b", "irreversible request"),
    (r"\bpublish\b", "publishes content on the user's behalf"),
    (r"\b(post|send)\s+(comment|review|message|reply)\b",
     "publishes content on the user's behalf"),
    (r"\breport\s+(this|abuse|user|post)\b", "files a report on someone"),
    (r"\bapply\s+now\b", "submits an application"),
    (r"\bbook\s+(now|and\s+pay)\b", "creates a booking"),
    (r"\bconfirm\s+(and\s+)?(book|reserve|pay)\b", "creates a booking"),
    (r"\bdonate\b", "initiates a payment"),
    (r"\bsubscribe\s+(and\s+)?pay\b", "initiates a payment"),
]

_SENSITIVE: list[tuple[str, str]] = [
    (r"\b(log\s?in|sign\s?in|sign\s?on)\b", "authentication surface"),
    (r"\b(log\s?out|sign\s?out)\b", "would end the session mid-journey"),
    (r"\b(sign\s?up|register|create\s+(an\s+)?account)\b",
     "account creation surface"),
    (r"\bcheckout\b", "checkout surface — reachable, never completed"),
    (r"\b(proceed|continue)\s+to\s+(checkout|payment)\b",
     "checkout surface — reachable, never completed"),
    (r"\bcontact\s+(us|sales)\b", "contact form — never submitted"),
    (r"\brequest\s+(a\s+)?(demo|quote|callback)\b", "lead form — never submitted"),
    (r"\bstart\s+(free\s+)?trial\b", "account creation surface"),
    (r"\bupload\b", "would send a file"),
    (r"\bshare\b", "would publish to a third party"),
]

#: Field names arrive as `card_number`, `cc-exp`, `user.pin` and `Card Number`,
#: so `\b` is the wrong boundary — `_` is a word character, and `\bpin\b` would
#: miss `user_pin`. These lookarounds treat any non-alphanumeric as a break,
#: which matches every separator a form actually uses.
#:
#: The boundary is not cosmetic. Without it `pin` matches inside "shopping"
#: and the agent refuses to press "Continue shopping" on the grounds that it
#: is a credential field — a refusal that is both wrong and unexplainable.
_B = r"(?<![a-z0-9])"
_E = r"(?![a-z0-9])"

#: Input fields the agent will never type a real value into.
_PAYMENT_FIELD = re.compile(
    _B + r"(?:"
    r"card[\s_.-]*(?:number|no|num)|cardnumber"
    r"|cc[\s_.-]*(?:num|number|exp|cvc|cvv)"
    r"|cvv|cvc|security[\s_.-]*code|expiry|exp[\s_.-]*(?:date|month|year)"
    r"|iban|routing[\s_.-]*number|account[\s_.-]*number|sort[\s_.-]*code"
    r"|ssn|social[\s_.-]*security|passport|national[\s_.-]*id"
    r"|tax[\s_.-]*id|aadhaar|pan[\s_.-]*number"
    r")" + _E, re.I)

_CREDENTIAL_FIELD = re.compile(
    _B + r"(?:"
    r"password|passwd|pwd|otp|one[\s_.-]*time(?:[\s_.-]*(?:code|password))?"
    r"|2fa|mfa|verification[\s_.-]*code|security[\s_.-]*answer|pin"
    r")" + _E, re.I)

_FORBIDDEN_RE = [(re.compile(p, re.I), r) for p, r in _FORBIDDEN]
_SENSITIVE_RE = [(re.compile(p, re.I), r) for p, r in _SENSITIVE]

#: Schemes the agent never follows. mailto:/tel: leave the browser entirely.
_OFFSITE_SCHEMES = {"mailto", "tel", "sms", "javascript", "file", "ftp",
                    "whatsapp", "intent"}


def is_payment_field(*texts: str) -> bool:
    return any(_PAYMENT_FIELD.search(t or "") for t in texts)


def is_credential_field(*texts: str) -> bool:
    return any(_CREDENTIAL_FIELD.search(t or "") for t in texts)


def classify_text(*texts: str) -> tuple[Risk, str]:
    """Classify from whatever strings describe a control.

    FORBIDDEN wins over SENSITIVE: "Delete account" inside a login page is
    forbidden, not sensitive.
    """
    haystack = " ".join(t for t in texts if t).strip()
    if not haystack:
        return Risk.SAFE, ""
    for rx, reason in _FORBIDDEN_RE:
        if rx.search(haystack):
            return Risk.FORBIDDEN, reason
    for rx, reason in _SENSITIVE_RE:
        if rx.search(haystack):
            return Risk.SENSITIVE, reason
    return Risk.SAFE, ""


def classify_element(el: InteractiveElement) -> tuple[Risk, str]:
    """The single place an element's risk is decided."""
    if el.kind in (ElementKind.PASSWORD_INPUT,):
        return Risk.FORBIDDEN, "credential field — never typed into"
    if is_payment_field(el.name, el.text, el.selector):
        return Risk.FORBIDDEN, "payment or identity field — never typed into"
    if is_credential_field(el.name, el.text, el.selector):
        return Risk.FORBIDDEN, "credential field — never typed into"

    if el.href:
        scheme = urlparse(el.href).scheme.lower()
        if scheme in _OFFSITE_SCHEMES:
            return Risk.FORBIDDEN, f"{scheme}: link leaves the browser"

    risk, reason = classify_text(el.name, el.text, el.href or "")
    if el.kind is ElementKind.ADD_TO_CART and risk is Risk.SAFE:
        # Adding to a cart is reversible and is the conversion action the
        # brief explicitly asks the agent to exercise. It stays SAFE.
        return Risk.SAFE, ""
    return risk, reason


def classify_form(form: FormModel, fields: list[InteractiveElement]
                  ) -> tuple[Risk, str]:
    """A form is as dangerous as its most dangerous field.

    No form is ever submitted by this agent — `executor.py` has no code path
    that presses a form's submit control except for a search box, whose only
    payload is a query string the agent generated itself. The classification
    still matters because it decides whether the agent may type at all.
    """
    if form.has_password or any(f.kind is ElementKind.PASSWORD_INPUT
                                for f in fields):
        return Risk.SENSITIVE, "contains a credential field"
    if form.has_payment_field:
        return Risk.FORBIDDEN, "contains a payment or identity field"
    risk, reason = classify_text(form.name, form.action)
    return risk, reason


def in_scope(url: str, root_host: str) -> bool:
    """Same registrable host, or a subdomain of it. Never a third party.

    The agent explores a site; it does not follow the web. An off-site link
    is inventoried and reported, and never navigated to.
    """
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    root = root_host.lower().removeprefix("www.")
    host = host.removeprefix("www.")
    return host == root or host.endswith("." + root)


class ActionRefused(Exception):
    """The safety layer declined an action. Recorded, never retried around."""


def guard(el: InteractiveElement | None, kind: str) -> None:
    """Raise if this element must not be touched. Called by the executor."""
    if el is None:
        return
    if el.risk is Risk.FORBIDDEN:
        raise ActionRefused(
            f"{kind} on {el.label!r} refused — {el.risk_reason or 'forbidden'}")
