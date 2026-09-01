"""Website Observer — DOM, accessibility, structure and vitals into a PageModel.

Phase 1 of the loop (§3). This module answers "what do I see?" and nothing
else: it makes no decision, dispatches no action, and never consults the LLM.
Its output is the only view of the page anything downstream ever gets.

The element inventory is deliberately narrow. The brain receives labels,
roles and refs — not HTML, not selectors, not scripts — so the widest
instruction it can express is "act on the thing you already showed me", and
the safety classification of that thing was decided here, before the model
saw it.
"""
from __future__ import annotations

import logging
import re

from playwright.async_api import Page

from app.behaviour import js, safety
from app.behaviour.models import (A11ySnapshot, ElementKind, FormModel,
                                  InteractiveElement, PageModel, PageVitals,
                                  Risk)

log = logging.getLogger(__name__)

#: Word patterns that name a kind of control regardless of its markup.
_SEARCH = re.compile(r"\b(search|find|look ?up|query)\b|^q$|^s$", re.I)
_CART = re.compile(r"\b(add to (cart|bag|basket)|add to trolley|añadir)\b"
                   r"|add-?to-?cart|addtocart|add_to_cart", re.I)
_QTY = re.compile(r"\b(qty|quantity|amount)\b", re.I)
_MENU = re.compile(r"\b(menu|navigation|hamburger|toggle nav|open menu)\b"
                   r"|burger|nav-?toggle", re.I)
_CLOSE = re.compile(r"\b(close|dismiss|×|✕)\b|close-?(modal|dialog|btn)", re.I)
_PAGINATION = re.compile(r"\b(next|previous|prev|page \d+|load more|show more)\b"
                         r"|pagination", re.I)
_PRODUCT = re.compile(r"product|item-card|listing|sku|catalog", re.I)


def _derive_kind(raw: dict) -> ElementKind:
    """Classify by behaviour, not by tag.

    A `<div role="button" class="add-to-cart">` and a `<button>Add to bag</button>`
    are the same thing to a user, so they must be the same thing to the agent.
    """
    tag = raw.get("tag", "")
    typ = (raw.get("type") or "").lower()
    role = (raw.get("role") or "").lower()
    words = " ".join(str(raw.get(k) or "") for k in
                     ("name", "text", "placeholder", "elName", "id", "cls",
                      "testid"))

    if tag == "input" or role in ("textbox", "searchbox", "combobox"):
        if typ == "password":
            return ElementKind.PASSWORD_INPUT
        if typ == "email" or re.search(r"\bemail\b", words, re.I):
            return ElementKind.EMAIL_INPUT
        if typ == "search" or role == "searchbox" or _SEARCH.search(words):
            return ElementKind.SEARCH_INPUT
        if typ == "checkbox" or role == "checkbox":
            return ElementKind.CHECKBOX
        if typ == "radio" or role == "radio":
            return ElementKind.RADIO
        if typ in ("submit", "button", "reset", "image"):
            return ElementKind.SUBMIT
        if tag == "select" or role == "combobox":
            return ElementKind.SELECT
        if _QTY.search(words):
            return ElementKind.QUANTITY
        return ElementKind.TEXT_INPUT

    if tag == "select":
        return ElementKind.QUANTITY if _QTY.search(words) else ElementKind.SELECT
    if tag == "textarea":
        return ElementKind.TEXTAREA
    if tag in ("video", "audio") or role == "media":
        return ElementKind.MEDIA
    if role == "tab":
        return ElementKind.TAB
    if tag == "summary" or role == "button" and raw.get("expanded") is not None:
        if tag == "summary":
            return ElementKind.ACCORDION

    if _CART.search(words):
        return ElementKind.ADD_TO_CART
    if _CLOSE.search(words) and raw.get("inForm") is not True:
        return ElementKind.MODAL_CLOSE
    if _MENU.search(words) or raw.get("haspopup") in ("menu", "true"):
        return ElementKind.MENU_TOGGLE
    if _PAGINATION.search(words):
        return ElementKind.PAGINATION

    if role == "link" or tag == "a":
        # A link inside a card, outside the navigation, is the primary target
        # of that card. On a shop it is a product; on a news site it is a
        # story; on a directory it is an entry. The kind is named for the
        # commonest case, but what it MEANS is "the thing this tile is for",
        # and that is what makes it the first thing the agent reaches for.
        if raw.get("inCard") and not raw.get("inNav"):
            return ElementKind.PRODUCT_CARD
        if _PRODUCT.search(words):
            return ElementKind.PRODUCT_CARD
        if raw.get("inNav"):
            return ElementKind.NAV
        return ElementKind.LINK
    if role == "button" or tag == "button":
        if raw.get("expanded") is not None:
            return ElementKind.ACCORDION
        if raw.get("inForm") and typ in ("submit", ""):
            return ElementKind.SUBMIT
        return ElementKind.BUTTON
    return ElementKind.OTHER


def _to_element(raw: dict) -> InteractiveElement:
    kind = _derive_kind(raw)
    el = InteractiveElement(
        ref=raw["ref"],
        kind=kind,
        role=raw.get("role", ""),
        name=raw.get("name", "") or "",
        text=raw.get("text", "") or "",
        tag=raw.get("tag", ""),
        href=raw.get("href"),
        selector=f'[data-aq-ref="{raw["ref"]}"]',
        x=float(raw.get("x", 0)), y=float(raw.get("y", 0)),
        width=float(raw.get("w", 0)), height=float(raw.get("h", 0)),
        in_viewport=bool(raw.get("inViewport")),
        visible=bool(raw.get("visible")),
        enabled=bool(raw.get("enabled", True)),
        focusable=bool(raw.get("focusable")),
        has_accessible_name=bool(raw.get("named")),
    )
    # The identity fields go into the classifier too: a control named only by
    # an icon still betrays itself through its class or test id.
    risk, reason = safety.classify_element(el)
    if risk is Risk.SAFE:
        risk, reason = safety.classify_text(
            raw.get("cls", ""), raw.get("testid", ""), raw.get("id", ""))
    el.risk, el.risk_reason = risk, reason
    return el


def _to_form(raw: dict, elements: dict[str, InteractiveElement]) -> FormModel:
    field_names = " ".join(raw.get("fieldNames", []))
    form = FormModel(
        ref=raw["ref"],
        name=raw.get("name", ""),
        action=raw.get("action", ""),
        method=raw.get("method", "get"),
        field_refs=[r for r in raw.get("fieldRefs", []) if r],
        has_password=bool(raw.get("hasPassword")),
        has_payment_field=safety.is_payment_field(field_names, raw.get("name", "")),
        submit_ref=raw.get("submitRef"),
    )
    fields = [elements[r] for r in form.field_refs if r in elements]
    form.risk, _ = safety.classify_form(form, fields)
    return form


class WebsiteObserver:
    """Builds a PageModel from a live page. Read-only, apart from ref stamps."""

    def __init__(self, *, max_elements: int = 220,
                 keyboard_walk_steps: int = 12):
        self.max_elements = max_elements
        self.keyboard_walk_steps = keyboard_walk_steps

    async def observe(self, page: Page, *, with_vitals: bool = False,
                      with_keyboard: bool = False) -> PageModel:
        """One full observation. Never raises: a partial view beats none."""
        try:
            raw = await page.evaluate(js.PAGE_MODEL, self.max_elements)
        except Exception as exc:                                # noqa: BLE001
            log.warning("page model extraction failed: %s", exc)
            return PageModel(url=page.url, title="",
                             console_errors=[f"observation failed: {exc}"])

        elements = [_to_element(r) for r in raw.get("elements", [])]
        by_ref = {e.ref: e for e in elements}
        forms = [_to_form(f, by_ref) for f in raw.get("forms", [])]

        # A field inside a forbidden form inherits the refusal — a card number
        # box is dangerous whether or not its own name gave it away.
        for form in forms:
            if form.risk is Risk.FORBIDDEN:
                for ref in form.field_refs:
                    if (el := by_ref.get(ref)) and el.risk is Risk.SAFE:
                        el.risk = Risk.FORBIDDEN
                        el.risk_reason = "field of a payment form"

        a = raw.get("a11y", {})
        model = PageModel(
            url=raw.get("url", page.url),
            title=raw.get("title", ""),
            fingerprint=raw.get("fingerprint", ""),
            headings=raw.get("headings", []),
            text_excerpt=raw.get("textExcerpt", ""),
            elements=elements,
            forms=forms,
            a11y=A11ySnapshot(
                focusable_count=a.get("focusableCount", 0),
                unlabelled_controls=a.get("unlabelledControls", 0),
                images_missing_alt=a.get("imagesMissingAlt", 0),
                heading_levels=a.get("headingLevels", []),
                heading_order_ok=bool(a.get("headingOrderOk", True)),
                landmark_roles=a.get("landmarkRoles", []),
                has_skip_link=bool(a.get("hasSkipLink")),
            ),
            scrollable=bool(raw.get("scrollable")),
            scroll_height=float(raw.get("scrollHeight", 0)),
            viewport_height=float(raw.get("viewportHeight", 0)),
            has_modal=bool(raw.get("hasModal")),
        )

        if with_vitals:
            model.vitals = await self.vitals(page)
        if with_keyboard:
            model.a11y.focus_visible_ratio = await self.keyboard_walk(page)
        return model

    async def vitals(self, page: Page) -> PageVitals:
        """Navigation timing + paint metrics. Unobserved fields stay None."""
        try:
            v = await page.evaluate(js.VITALS)
        except Exception as exc:                                # noqa: BLE001
            log.debug("vitals unavailable: %s", exc)
            return PageVitals()
        return PageVitals(
            status=v.get("status"),
            redirects=int(v.get("redirects") or 0),
            dns_ms=v.get("dns"), tcp_ms=v.get("tcp"), tls_ms=v.get("tls"),
            ttfb_ms=v.get("ttfb"), dom_content_loaded_ms=v.get("dcl"),
            load_ms=v.get("load"), fcp_ms=v.get("fcp"), lcp_ms=v.get("lcp"),
            cls=v.get("cls"), js_execution_ms=v.get("js"),
            transferred_bytes=int(v["bytes"]) if v.get("bytes") else None,
            request_count=int(v.get("requests") or 0),
        )

    async def keyboard_walk(self, page: Page) -> float | None:
        """Tab through the first N stops; report the share visibly indicated.

        A ratio, not a verdict. Automated focus-indicator detection cannot
        establish WCAG 2.4.7 conformance — it can only tell you that N of M
        stops had no detectable indicator at all, which is worth reporting.
        Returns None when nothing was focusable, so "no data" never reads as
        "zero percent".
        """
        seen = 0
        indicated = 0
        try:
            for _ in range(self.keyboard_walk_steps):
                await page.keyboard.press("Tab")
                await page.wait_for_timeout(60)
                state = await page.evaluate(js.FOCUS_STATE)
                if not state:
                    continue
                seen += 1
                if state.get("indicated"):
                    indicated += 1
        except Exception as exc:                                # noqa: BLE001
            log.debug("keyboard walk interrupted: %s", exc)
        if seen == 0:
            return None
        return round(indicated / seen, 3)
