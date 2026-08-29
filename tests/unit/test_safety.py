"""Redaction, anti-bot policy and the traffic budget."""
from __future__ import annotations

import pytest

from app.safety import redaction
from app.safety.antibot import blocked_reason, detect
from app.safety.limits import BudgetExceeded, TrafficBudget

FAKE_SECRETS = [
    "AKIAIOSFODNN7EXAMPLE",
    "-----BEGIN RSA PRIVATE KEY-----",
    "ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "sk_live_aaaaaaaaaaaaaaaaaaaa",
]


# --- redaction -----------------------------------------------------------

def test_set_cookie_keeps_attributes_and_drops_the_value():
    """WEB-05 needs the FLAGS. It never needs the value."""
    out = redaction.redact_set_cookie(
        "sid=s3cr3tvalue; Path=/; Secure; HttpOnly; SameSite=Lax")
    assert "s3cr3tvalue" not in out
    for attr in ("Secure", "HttpOnly", "SameSite=Lax", "Path=/"):
        assert attr in out


def test_sensitive_headers_are_replaced_with_a_shape():
    out = redaction.redact_headers({"Authorization": "Bearer abc123xyz",
                                    "Content-Type": "text/html"})
    assert "abc123xyz" not in str(out)
    assert out["content-type"] == "text/html"      # keys lower-cased


def test_sensitive_query_parameters_are_redacted():
    out = redaction.redact_url(
        "https://x.test/cb?code=AQ12345678901234567890&page=2")
    assert "AQ12345678901234567890" not in out
    assert "page=2" in out


@pytest.mark.parametrize("secret", FAKE_SECRETS)
def test_scan_never_stores_the_matched_secret(secret):
    findings = redaction.scan_for_secrets(f'var k = "{secret}";', "app.js")
    assert findings, f"pattern did not match {secret[:12]}"
    assert secret not in str(findings)


def test_redact_secrets_in_text_removes_the_literal_but_marks_the_site():
    text = 'const k = "AKIAIOSFODNN7EXAMPLE"; ok'
    out = redaction.redact_secrets_in_text(text)
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert "REDACTED" in out and out.endswith("ok")


def test_jwt_and_token_detection():
    jwt = ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
           "dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk")
    assert redaction.looks_like_jwt(jwt)
    assert redaction.looks_like_token(jwt)
    assert not redaction.looks_like_jwt("dark")
    assert not redaction.looks_like_token("dark")


def test_source_map_references_are_reported():
    out = redaction.find_source_maps("//# sourceMappingURL=app.js.map", "app.js")
    assert out and out[0]["kind"] == "source_map_reference"


# --- anti-bot ------------------------------------------------------------

@pytest.mark.parametrize("status,kind", [
    (429, "rate_limit"), (403, "access_denied"),
    (401, "access_denied"), (503, "service_unavailable"),
])
def test_blocking_status_codes_are_detected(status, kind):
    s = detect(status=status, headers={}, body=None, url="https://x.test/")
    assert s.detected and s.kind == kind


@pytest.mark.parametrize("body,kind", [
    ("<h1>Checking your browser before accessing</h1>", "bot_verification"),
    ("Please complete the reCAPTCHA", "captcha"),
    ("We detected unusual traffic from your network", "unusual_traffic"),
])
def test_challenge_bodies_are_detected(body, kind):
    s = detect(status=200, headers={}, body=body, url="https://x.test/")
    assert s.detected and s.kind == kind


def test_a_normal_page_is_not_flagged():
    assert not detect(status=200, headers={},
                      body="<h1>Welcome to our shop</h1>",
                      url="https://x.test/").detected


def test_blocked_reason_states_that_no_bypass_was_attempted():
    s = detect(status=429, headers={"Retry-After": "60"}, body=None,
               url="https://x.test/")
    reason = blocked_reason(s)
    assert "halted" in reason and "no bypass" in reason.lower()


# --- traffic budget ------------------------------------------------------

def test_navigation_budget_is_enforced():
    b = TrafficBudget(max_navigations=2)
    b.navigate("https://x.test/", "WEB-01")
    b.navigate("https://x.test/", "PERF")
    with pytest.raises(BudgetExceeded, match="navigation budget"):
        b.navigate("https://x.test/", "one too many")


def test_page_budget_is_enforced():
    b = TrafficBudget(max_pages=1)
    b.open_page()
    with pytest.raises(BudgetExceeded, match="page budget"):
        b.open_page()


def test_every_navigation_is_attributed_to_a_reason():
    """There is no unattributed traffic in this system."""
    b = TrafficBudget()
    b.navigate("https://x.test/", "WEB-01: main document headers")
    b.aux("https://x.test/robots.txt", "IR-05: security.txt")
    log = b.report()
    assert len(log) == 2
    assert all("::" in entry for entry in log)
    assert b.total_requests == 2


def test_timeout_is_enforced():
    b = TrafficBudget(timeout_seconds=-1)      # already expired
    with pytest.raises(BudgetExceeded, match="timeout"):
        b.navigate("https://x.test/", "too late")
