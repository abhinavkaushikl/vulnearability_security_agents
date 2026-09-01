"""The Agent Brain — heuristics, and the validation of what a model returns.

Two properties matter here and neither is about the quality of the reasoning:

  1. With no model at all, the agent still produces a real plan. `--no-llm` is
     a heuristic agent, not a broken one.
  2. A model answer that leaves the observed inventory is REJECTED, not
     repaired. The safety boundary is a post-check in code, exactly as the
     security engine's anti-fabrication gate is.
"""
from __future__ import annotations

import pytest

from app.behaviour import brain
from app.behaviour.memory import AgentMemory
from app.behaviour.models import (ActionKind, ElementKind, InteractiveElement,
                                  Journey, JourneyStep, PageModel, Risk,
                                  SiteKind, SiteUnderstanding)


def el(ref, name, kind=ElementKind.BUTTON, risk=Risk.SAFE, y=100,
       in_viewport=True) -> InteractiveElement:
    return InteractiveElement(
        ref=ref, name=name, kind=kind, risk=risk, y=y, width=80, height=30,
        in_viewport=in_viewport, selector=f'[data-aq-ref="{ref}"]',
        role="button" if kind is ElementKind.BUTTON else "link")


SHOP = PageModel(
    url="https://shop.test/", title="Fixture Store — buy things",
    headings=["Everything for the home", "Featured products"],
    text_excerpt="Free delivery over £50. Add to cart. Copper Kettle £38.00.",
    scrollable=True, scroll_height=3000, viewport_height=900,
    elements=[
        el("e0", "Search", ElementKind.SEARCH_INPUT),
        el("e1", "Menu", ElementKind.MENU_TOGGLE),
        el("e2", "Copper Kettle", ElementKind.PRODUCT_CARD, y=400),
        el("e3", "Add to cart", ElementKind.ADD_TO_CART, y=600),
        el("e4", "Cart (0)", ElementKind.NAV),
        el("e5", "Place order", ElementKind.BUTTON, risk=Risk.FORBIDDEN, y=900),
    ])

NEWS = PageModel(
    url="https://paper.test/", title="The Daily Fixture",
    headings=["Top stories", "Opinion"],
    text_excerpt="Latest news and breaking coverage. Published 3 hours ago.",
    elements=[el("e0", "Read more", ElementKind.LINK)])


# ── understanding ────────────────────────────────────────────────────────

def test_a_shop_is_recognised_as_a_shop():
    u = brain.heuristic_understanding(SHOP)
    assert u.kind is SiteKind.ECOMMERCE
    assert "cart" in u.key_affordances and "search" in u.key_affordances
    assert u.derived_by == "heuristic"


def test_not_every_site_is_a_shop():
    """The brief is explicit about this one."""
    assert brain.heuristic_understanding(NEWS).kind is SiteKind.NEWS


def test_an_unrecognisable_page_reports_no_confidence_rather_than_guessing():
    blank = PageModel(url="https://x.test/", title="", text_excerpt="")
    u = brain.heuristic_understanding(blank)
    assert u.kind is SiteKind.UNKNOWN
    assert u.confidence == 0.0


# ── journeys ─────────────────────────────────────────────────────────────

def test_journeys_are_only_built_from_affordances_that_exist():
    u = brain.heuristic_understanding(NEWS)
    journeys = brain.heuristic_journeys(u, NEWS)
    names = {j.id for j in journeys}
    assert "j-search" not in names, "no search box, so no search journey"
    assert "j-buy" not in names, "not a shop"
    assert "j-orient" in names, "orientation is always possible"


def test_a_shop_gets_a_shopping_journey_that_stops_before_paying():
    u = brain.heuristic_understanding(SHOP)
    journeys = brain.heuristic_journeys(u, SHOP)
    buy = next(j for j in journeys if j.id == "j-buy")
    labels = " ".join(s.label for s in buy.steps).lower()
    assert "cart" in labels
    assert "pay" not in labels and "order" not in labels


def test_the_login_journey_never_intends_to_submit_credentials():
    from app.behaviour.models import FormModel
    # A page whose only affordance is a login, so the journey is not trimmed
    # by the four-journey cap.
    page = PageModel(
        url="https://app.test/", title="Sign in",
        elements=[el("e0", "Sign in", ElementKind.SUBMIT)],
        forms=[FormModel(ref="f0", has_password=True)])
    u = brain.heuristic_understanding(page)
    assert "login" in u.key_affordances
    journeys = brain.heuristic_journeys(u, page)
    auth = next(j for j in journeys if j.id == "j-auth")
    assert "never submits" in auth.goal
    assert not any(s.action == "submit_search" for s in auth.steps)
    assert not any(s.action == "type" for s in auth.steps), \
        "the agent never types into a credential form"


def test_journeys_are_capped_so_one_session_cannot_run_forever():
    u = brain.heuristic_understanding(SHOP)
    assert len(brain.heuristic_journeys(u, SHOP)) <= 4


# ── decisions ────────────────────────────────────────────────────────────

def decision(step_action, hint="", memory=None):
    j = Journey(id="j-1", name="t", goal="g",
                steps=[JourneyStep(label="do it", action=step_action,
                                   target_hint=hint)])
    return brain.heuristic_decision(
        SHOP, j, 0, memory or AgentMemory(),
        brain.heuristic_understanding(SHOP))


def test_a_step_resolves_to_the_control_it_names():
    intent = decision("click", "add to cart")
    assert intent.kind is ActionKind.CLICK
    assert intent.element_ref == "e3"


def test_the_heuristic_never_selects_a_forbidden_control():
    memory = AgentMemory()
    for hint in ("place order", "", "buy", "order"):
        intent = decision("click", hint, memory)
        assert intent.element_ref != "e5"


def test_an_unmatched_step_falls_back_to_the_most_prominent_thing():
    """A person who cannot find what they came for tries the most obvious
    thing on screen — they do not stand still."""
    intent = decision("click", "return an item under warranty")
    assert intent.kind is ActionKind.CLICK
    assert intent.element_ref in {"e2", "e4"}      # a card, or the nav
    assert intent.element_ref != "e5"              # never the forbidden one


def test_with_nothing_left_to_try_the_agent_scrolls_to_look_further():
    memory = AgentMemory()
    place = memory.place(SHOP)
    for e in SHOP.elements:
        memory.mark_tried(place, e.label)
        memory.dead.add((place, e.label))
    intent = decision("click", "return an item under warranty", memory)
    assert intent.kind is ActionKind.SCROLL
    assert intent.reason


def test_a_control_that_did_nothing_is_not_pressed_again():
    memory = AgentMemory()
    place = memory.place(SHOP)
    memory.dead.add((place, "Add to cart"))
    intent = decision("click", "add to cart", memory)
    assert intent.element_ref != "e3"


def test_a_matcher_needs_a_reason_to_match():
    """Without this, the tie-breakers alone carry an element over the line and
    the agent 'finds' a cookie-banner dismisser on a page that has none."""
    assert brain._match(SHOP.actionable, "accept all cookies",
                        (ElementKind.MODAL_CLOSE,)) is None


def test_the_search_query_comes_from_the_sites_own_words():
    q = brain.search_query(SHOP, brain.heuristic_understanding(SHOP))
    assert q and len(q.split()) <= 2
    assert "shop" not in q, "stop words are excluded"


# ── validating what a model returns ──────────────────────────────────────

class _Out:
    def __init__(self, **kw):
        self.action = kw.get("action", "click")
        self.element_ref = kw.get("element_ref")
        self.value = kw.get("value")
        self.amount = kw.get("amount")
        self.expectation = kw.get("expectation", "")
        self.reason = kw.get("reason", "")


def to_intent(out):
    b = brain.AgentBrain(None, enabled=False)
    j = Journey(id="j-1", name="t", goal="g",
                steps=[JourneyStep(label="do it", action="click")])
    fallback = brain.heuristic_decision(
        SHOP, j, 0, AgentMemory(), brain.heuristic_understanding(SHOP))
    return b._to_intent(out, SHOP, j, j.steps[0], fallback), fallback


@pytest.mark.parametrize("bad", [
    _Out(element_ref="e99"),                       # a ref that does not exist
    _Out(element_ref="e5"),                        # a FORBIDDEN control
    _Out(action="exploit", element_ref="e3"),      # not an action
    _Out(action="click", element_ref=None),        # click with no element
])
def test_a_model_answer_outside_the_inventory_is_rejected_not_repaired(bad):
    intent, fallback = to_intent(bad)
    assert intent == fallback
    assert intent.element_ref != "e5"


def test_a_valid_model_answer_is_used():
    intent, fallback = to_intent(
        _Out(action="click", element_ref="e3", reason="a shopper would"))
    assert intent.element_ref == "e3"
    assert intent.reason == "a shopper would"


def test_a_brain_with_no_provider_still_decides():
    b = brain.AgentBrain(None, enabled=True)
    assert b.enabled is False       # no provider means no model, whatever asked


# ── the model is never allowed to stall the run ──────────────────────────

@pytest.mark.asyncio
async def test_a_slow_model_falls_back_rather_than_blocking_the_session():
    """A local 7B routinely takes over a minute on the journey plan, and the
    HTTP timeout has retries behind it. Without a deadline the agent measures
    nothing for six minutes. Past the deadline it uses the heuristic answer
    and gets on with it."""
    import asyncio

    class _Slow:
        model = "slow-model"

        async def complete_structured(self, system, user, schema, retries=2):
            await asyncio.sleep(30)
            raise AssertionError("should have been abandoned before this")

    b = brain.AgentBrain(_Slow(), enabled=True, call_timeout=0.05)
    understanding = await b.understand(SHOP)

    assert b.model_timeouts == 1
    assert understanding.derived_by == "heuristic", \
        "a heuristic answer must never be reported as the model's"
    assert understanding.kind is SiteKind.ECOMMERCE


@pytest.mark.asyncio
async def test_a_broken_model_never_raises_into_the_session():
    class _Broken:
        model = "broken"

        async def complete_structured(self, system, user, schema, retries=2):
            raise RuntimeError("inference server is on fire")

    b = brain.AgentBrain(_Broken(), enabled=True)
    journeys = await b.plan_journeys(brain.heuristic_understanding(SHOP), SHOP)
    assert journeys and all(j.derived_by == "heuristic" for j in journeys)
    assert b.model_failures == 1


@pytest.mark.asyncio
async def test_steps_are_walked_deterministically_unless_asked_otherwise():
    """The model plans; Python executes. Turning this on costs one round trip
    per action, which is the difference between a 40-second session and a
    45-minute one on a local model."""
    calls = {"n": 0}

    class _Counting:
        model = "counting"

        async def complete_structured(self, system, user, schema, retries=2):
            calls["n"] += 1
            return None

    j = Journey(id="j-1", name="t", goal="g",
                steps=[JourneyStep(label="do it", action="click",
                                   target_hint="add to cart")])
    u = brain.heuristic_understanding(SHOP)

    quiet = brain.AgentBrain(_Counting(), enabled=True, decide_with_model=False)
    intent = await quiet.decide(SHOP, j, 0, AgentMemory(), u, [])
    assert calls["n"] == 0, "walking a planned step needs no model call"
    assert intent.element_ref == "e3"

    loud = brain.AgentBrain(_Counting(), enabled=True, decide_with_model=True)
    await loud.decide(SHOP, j, 0, AgentMemory(), u, [])
    assert calls["n"] == 1
