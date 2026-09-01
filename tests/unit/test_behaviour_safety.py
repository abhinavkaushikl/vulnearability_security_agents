"""The safety classifier — what the behaviour agent may and may not touch.

These are the tests that matter most in this package. Everything else in the
agent produces a report; this decides whether an autonomous browser agent
presses "Place order" on someone's shop.
"""
from __future__ import annotations

import pytest

from app.behaviour import safety
from app.behaviour.models import ElementKind, FormModel, InteractiveElement, Risk


def el(name: str = "", *, kind: ElementKind = ElementKind.BUTTON,
       text: str = "", href: str | None = None, ref: str = "e0"
       ) -> InteractiveElement:
    return InteractiveElement(ref=ref, kind=kind, name=name, text=text,
                              href=href, selector=f'[data-aq-ref="{ref}"]')


# ── the deny list ────────────────────────────────────────────────────────

@pytest.mark.parametrize("label", [
    "Place order", "Place your order", "Confirm order", "Complete purchase",
    "Buy now", "Buy it now", "Pay now", "Pay securely", "Make a payment",
    "Delete", "Delete account", "Close my account", "Cancel subscription",
    "Cancel order", "Unsubscribe", "Empty the cart", "Transfer money",
    "Reset password", "Donate", "Apply now", "Book now", "Publish",
    "Post comment", "Send message",
])
def test_irreversible_controls_are_forbidden(label):
    risk, reason = safety.classify_element(el(label))
    assert risk is Risk.FORBIDDEN, f"{label!r} must never be pressed"
    assert reason, "a refusal must say why — it ends up in the report"


@pytest.mark.parametrize("label", [
    "Add to cart", "Add to bag", "Add to basket", "View cart", "Continue shopping",
    "Products", "Read more", "Next page", "Filter", "Sort by price",
    "Open the menu", "Play", "Search",
])
def test_ordinary_browsing_stays_safe(label):
    risk, _ = safety.classify_element(el(label))
    assert risk is Risk.SAFE, f"{label!r} is ordinary browsing"


@pytest.mark.parametrize("label", [
    "Sign in", "Log in", "Sign up", "Create an account", "Checkout",
    "Proceed to checkout", "Start free trial", "Contact us", "Request a demo",
    "Log out",
])
def test_thresholds_are_sensitive_not_forbidden(label):
    """The agent may reach these surfaces. It never completes them."""
    risk, reason = safety.classify_element(el(label))
    assert risk is Risk.SENSITIVE, f"{label!r} should be approachable"
    assert reason


def test_forbidden_beats_sensitive():
    """'Delete account' on a sign-in page is forbidden, not sensitive."""
    risk, _ = safety.classify_element(el("Sign in and delete account"))
    assert risk is Risk.FORBIDDEN


def test_substring_collisions_do_not_forbid_innocent_controls():
    """Whole-word anchoring: a payment HISTORY page is not a payment."""
    for label in ("Payment history", "Order history", "Deleted items archive",
                  "Buying guide", "Cancellation policy"):
        risk, _ = safety.classify_element(el(label))
        assert risk is not Risk.FORBIDDEN, label


# ── fields ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("field", [
    "cardnumber", "card_number", "cc-exp", "cvv", "cvc", "security code",
    "iban", "routing number", "sort code", "ssn", "passport", "aadhaar",
])
def test_payment_and_identity_fields_are_never_typed_into(field):
    risk, _ = safety.classify_element(
        el(field, kind=ElementKind.TEXT_INPUT))
    assert risk is Risk.FORBIDDEN


@pytest.mark.parametrize("field", ["password", "passwd", "otp",
                                   "one-time code", "2fa", "pin"])
def test_credential_fields_are_never_typed_into(field):
    risk, _ = safety.classify_element(el(field, kind=ElementKind.TEXT_INPUT))
    assert risk is Risk.FORBIDDEN


def test_a_password_input_is_forbidden_whatever_it_is_called():
    risk, _ = safety.classify_element(
        el("Your secret", kind=ElementKind.PASSWORD_INPUT))
    assert risk is Risk.FORBIDDEN


def test_a_payment_form_is_forbidden_and_a_login_form_is_sensitive():
    pay = FormModel(ref="f0", name="checkout", has_payment_field=True)
    assert safety.classify_form(pay, [])[0] is Risk.FORBIDDEN

    login = FormModel(ref="f1", name="session", has_password=True)
    assert safety.classify_form(login, [])[0] is Risk.SENSITIVE


# ── links that leave the browser ─────────────────────────────────────────

@pytest.mark.parametrize("href", ["mailto:a@b.test", "tel:+441234567890",
                                  "javascript:void(0)", "sms:+1555"])
def test_links_that_leave_the_browser_are_forbidden(href):
    risk, _ = safety.classify_element(el("Contact", kind=ElementKind.LINK,
                                         href=href))
    assert risk is Risk.FORBIDDEN


# ── scope ────────────────────────────────────────────────────────────────

def test_scope_covers_the_host_and_its_subdomains_only():
    assert safety.in_scope("https://shop.example.com/x", "example.com")
    assert safety.in_scope("https://www.example.com/", "example.com")
    assert safety.in_scope("https://example.com/a?b=c", "www.example.com")
    assert not safety.in_scope("https://example.com.evil.test/", "example.com")
    assert not safety.in_scope("https://notexample.com/", "example.com")
    assert not safety.in_scope("https://partner.test/", "example.com")


def test_guard_raises_only_on_forbidden():
    forbidden = el("Place order")
    forbidden.risk, forbidden.risk_reason = safety.classify_element(forbidden)
    with pytest.raises(safety.ActionRefused):
        safety.guard(forbidden, "click")

    ok = el("Add to cart")
    ok.risk, ok.risk_reason = safety.classify_element(ok)
    safety.guard(ok, "click")           # must not raise
    safety.guard(None, "click")         # must not raise
