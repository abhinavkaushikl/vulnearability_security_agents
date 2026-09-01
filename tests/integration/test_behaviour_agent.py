"""User Behaviour Agent, end to end, against a real Chromium.

The fixture site is deliberately imperfect and every defect in it exists to
prove one part of the agent works. It binds 127.0.0.1 only: an autonomous
browser agent is exactly the thing that must never be pointed at a public
site by a test suite.

The tests that matter most are the negative ones — what the agent did NOT do.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.behaviour.models import ActionKind, AgentState, ElementKind, Outcome
from app.behaviour.runner import SessionOptions, run_session
from app.behaviour.serializers import to_json
from tests.fixtures.ux_server import UXFixtureSite

# Only the executor test below is async. The session fixture drives one full
# run with asyncio.run and every assertion then reads its result, so marking
# the whole module asyncio would just warn on every sync test.
pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]

#: Controls the fixture plants specifically so the agent can refuse them.
FORBIDDEN_LABELS = ["Buy now", "Place order", "Empty the cart"]


@pytest.fixture(scope="module")
def session():
    """One agent run, shared by every assertion. Running the agent per test
    would take minutes and would not test anything extra."""
    async def go():
        with UXFixtureSite() as site:
            report = await run_session(
                site.base_url,
                options=SessionOptions(no_llm=True, pacing=0.25,
                                       max_actions=34, seed=7),
                config=str(ROOT / "config.yaml"),
                policy=str(ROOT / "policy.yaml"))
        return report
    return asyncio.run(go())


# ── it ran ───────────────────────────────────────────────────────────────

def test_the_session_completes_without_a_model(session):
    """--no-llm is a heuristic agent, not a broken one."""
    assert session.state is AgentState.COMPLETED
    assert session.llm_model is None
    assert session.understanding.derived_by == "heuristic"
    assert session.journeys, "a run with no model still plans journeys"
    assert session.actions, "and still dispatches actions"


def test_it_worked_out_what_the_site_is(session):
    assert session.understanding.kind.value == "ecommerce"
    assert session.understanding.primary_goal
    assert "search" in session.understanding.key_affordances
    assert "cart" in session.understanding.key_affordances


def test_it_explored_beyond_the_landing_page(session):
    assert session.pages_explored >= 2, "an agent that never leaves home is a scan"
    urls = {p.url for p in session.pages}
    assert len(urls) >= 2


# ── it measured ──────────────────────────────────────────────────────────

def test_a_control_that_never_responded_has_no_response_time(session):
    """Whatever the agent happened to press, nothing that failed to respond
    may carry a latency. A number here would be fabricated."""
    dead = [a for a in session.actions if a.outcome is Outcome.NO_RESPONSE]
    for a in dead:
        assert a.timing.perceived_ms is None
        assert a.timing.ui_response_ms is None


def test_the_planted_debounce_is_measured_rather_than_called_dead(session):
    """The search box responds after 620 ms. A short patience would report
    every debounced control on the web as broken."""
    typed = [a for a in session.actions
             if a.intent.kind in (ActionKind.TYPE, ActionKind.SUBMIT_SEARCH)]
    assert typed, "the agent never reached the search box"
    measured = [a for a in typed if a.timing.perceived_ms is not None]
    assert measured, "the debounced response was missed entirely"
    assert any(a.timing.perceived_ms > 400 for a in measured), \
        "the 620 ms debounce should show as a slow response"


def test_a_navigation_is_timed_from_the_new_document(session):
    """A navigation destroys the in-page probe. Reading it afterwards yields
    null, and reporting that as 'inconclusive' is how a working link ends up
    counted as a broken one."""
    navs = [a for a in session.actions if a.url_changed]
    assert navs, "the agent never changed page"
    assert any(a.timing.perceived_ms is not None for a in navs)
    assert all(a.outcome is not Outcome.INCONCLUSIVE for a in navs)


def test_scrolling_is_measured_in_frames(session):
    scrolls = [a for a in session.actions if a.category == "scroll"
               and a.outcome is Outcome.SUCCESS]
    assert scrolls
    assert any(a.timing.scroll_fps is not None for a in scrolls)


def test_the_focus_only_response_of_a_text_field_counts_as_a_response(session):
    """Clicking a search box gives you a caret and nothing else. That is the
    whole of the correct response, and calling it dead would report every
    search box on the web as broken."""
    field_clicks = [a for a in session.actions
                    if a.intent.kind is ActionKind.CLICK
                    and a.element_kind is ElementKind.SEARCH_INPUT]
    if field_clicks:
        assert any(a.outcome is Outcome.SUCCESS for a in field_clicks)


# ── it never did what it must not ────────────────────────────────────────

def test_no_forbidden_control_was_ever_dispatched(session):
    """The fixture plants 'Buy now', 'Place order' and 'Empty the cart'."""
    for a in session.actions:
        if a.outcome is Outcome.REFUSED:
            continue
        for label in FORBIDDEN_LABELS:
            assert label.lower() not in (a.element_label or "").lower(), \
                f"the agent dispatched {a.intent.kind.value} on {a.element_label!r}"


def test_no_form_was_ever_submitted(session):
    """The fixture server answers 405 to every POST. The only submission the
    agent performs is a search, which is a GET of its own query."""
    submits = [a for a in session.actions
               if a.intent.kind is ActionKind.SUBMIT_SEARCH]
    for a in submits:
        assert a.element_kind is ElementKind.SEARCH_INPUT


def test_no_credential_or_payment_field_was_typed_into(session):
    typed = [a for a in session.actions if a.intent.kind is ActionKind.TYPE]
    for a in typed:
        assert a.element_kind is not ElementKind.PASSWORD_INPUT
        label = (a.element_label or "").lower()
        for bad in ("password", "card", "cvc", "cvv"):
            assert bad not in label


def test_the_agent_stayed_on_one_host(session):
    host = session.target.split("//", 1)[1].split("/")[0]
    for p in session.pages:
        assert host in p.url, f"the agent left the site: {p.url}"


def test_traffic_stayed_inside_the_budget(session):
    assert session.requests_made > 0
    assert session.requests_made <= 24, "the navigation budget was exceeded"


# ── it reported honestly ─────────────────────────────────────────────────

def test_inp_is_null_everywhere_and_never_zero(session):
    payload = to_json(session)
    for p in payload["pages"]:
        assert p["vitals"]["inp_ms"] is None


def test_no_unobserved_metric_serialises_as_zero(session):
    payload = to_json(session)
    for a in payload["actions"]:
        if a["outcome"] == "NO_RESPONSE":
            assert a["timing"]["perceived_ms"] is None
            assert a["timing"]["ui_response_ms"] is None


def test_the_score_only_counts_components_it_measured(session):
    unrated = [c for c in session.score.components if c.score is None]
    for c in unrated:
        assert c.n == 0, "a component with data must produce a score"
    rated = [c for c in session.score.components if c.score is not None]
    assert rated, "nothing at all was measurable"
    assert session.score.overall is not None


def test_every_finding_cites_something_that_happened(session):
    seqs = {a.seq for a in session.actions}
    for f in session.findings:
        assert f.observed and f.expected and f.recommendation
        for s in f.evidence_seq:
            assert s in seqs, f"{f.id} cites action {s}, which does not exist"


def test_the_report_serialises_to_the_shape_the_interface_reads(session):
    payload = to_json(session)
    for key in ("session_id", "target", "state", "understanding", "score",
                "journeys", "journey_outcomes", "timeline", "interactions",
                "categories", "actions", "thoughts", "pages", "findings",
                "insights", "summary", "mission", "refusals"):
        assert key in payload, f"the interface reads {key}"


def test_the_agent_log_describes_only_actions_that_happened(session):
    """§16: the thought stream is assembled in Python from ActionRecords, so
    it cannot narrate something the agent did not do."""
    assert session.thoughts
    for t in session.thoughts:
        assert t.observation and t.action
        assert t.state.value in {s.value for s in AgentState}


# ── the executor, driven directly ────────────────────────────────────────
#
# The session tests above assert on whatever the agent chose to do, and it
# chooses differently as the site changes — which is the point of an
# autonomous agent, and useless for pinning one behaviour. These drive the
# executor at three specific controls the fixture plants for the purpose.

@pytest.mark.asyncio
async def test_the_executor_tells_a_dead_control_from_a_working_one():
    """`#dead` has no handler bound; `#menu` opens a dropdown. The measured
    difference between them is the single most important thing this agent
    does, so it is pinned rather than left to exploration order."""
    from app.behaviour.executor import ActionExecutor
    from app.behaviour.measure import MeasurementEngine
    from app.behaviour.models import ActionIntent
    from app.behaviour.observer import WebsiteObserver
    from app.config.settings import load_settings
    from app.safety.limits import TrafficBudget
    from app.tools.browser import BrowserSession

    settings = load_settings(project_root=ROOT)
    with UXFixtureSite() as site:
        budget = TrafficBudget(max_navigations=8, max_pages=4,
                               timeout_seconds=120)
        browser = BrowserSession(settings, budget, ROOT / "artifacts" / "test")
        await browser.start()
        try:
            ctx = await browser.new_context(label="test")
            page = await browser.open_page(ctx)
            await browser.navigate(page, site.base_url, reason="fixture test")
            await browser.wait_for_ready(page, settle_ms=900)

            observer = WebsiteObserver()
            engine = MeasurementEngine()
            model = await observer.observe(page)
            ex = ActionExecutor(page, budget, engine,
                                root_host="127.0.0.1", entry_url=site.base_url,
                                pacing=0.2, seed=1)

            def ref_for(fragment: str) -> str:
                el = next(e for e in model.elements
                          if fragment.lower() in e.label.lower())
                return el.ref

            dead = await ex.execute(ActionIntent(
                kind=ActionKind.CLICK, element_ref=ref_for("mailing list"),
                reason="press a control with no handler"), model)
            assert dead.outcome is Outcome.NO_RESPONSE
            assert dead.timing.perceived_ms is None

            alive = await ex.execute(ActionIntent(
                kind=ActionKind.CLICK, element_ref=ref_for("Menu"),
                reason="press a control that works"), model)
            assert alive.outcome is Outcome.SUCCESS
            assert alive.timing.perceived_ms is not None
            assert alive.timing.perceived_ms < 500
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_the_executor_refuses_the_purchase_button_at_dispatch():
    """The classifier marks it FORBIDDEN and the executor declines it. The
    refusal is recorded as data — not a silent skip — and the run continues."""
    from app.behaviour.executor import ActionExecutor
    from app.behaviour.measure import MeasurementEngine
    from app.behaviour.models import ActionIntent, Risk
    from app.behaviour.observer import WebsiteObserver
    from app.config.settings import load_settings
    from app.safety.limits import TrafficBudget
    from app.tools.browser import BrowserSession

    settings = load_settings(project_root=ROOT)
    with UXFixtureSite() as site:
        budget = TrafficBudget(max_navigations=8, max_pages=4,
                               timeout_seconds=120)
        browser = BrowserSession(settings, budget, ROOT / "artifacts" / "test")
        await browser.start()
        try:
            ctx = await browser.new_context(label="test")
            page = await browser.open_page(ctx)
            await browser.navigate(page, f"{site.base_url}/product.html",
                                   reason="fixture test")
            await browser.wait_for_ready(page, settle_ms=700)

            model = await WebsiteObserver().observe(page)
            ex = ActionExecutor(page, budget, MeasurementEngine(),
                                root_host="127.0.0.1", entry_url=site.base_url,
                                pacing=0.2, seed=1)

            buy = next(e for e in model.elements
                       if "buy now" in e.label.lower())
            assert buy.risk is Risk.FORBIDDEN
            assert buy.risk_reason

            record = await ex.execute(ActionIntent(
                kind=ActionKind.CLICK, element_ref=buy.ref,
                reason="a plan that should not survive the safety layer"),
                model)
            assert record.outcome is Outcome.REFUSED
            assert "refused" in record.observed.lower()
            # The page did not navigate to a confirmation of anything.
            assert "product.html" in page.url

            # And the checkout page's card field is never typed into.
            await browser.navigate(page, f"{site.base_url}/checkout.html",
                                   reason="fixture test")
            checkout = await WebsiteObserver().observe(page)
            card = next(e for e in checkout.elements
                        if "card" in e.label.lower())
            assert card.risk is Risk.FORBIDDEN
            typed = await ex.execute(ActionIntent(
                kind=ActionKind.TYPE, element_ref=card.ref, value="4111",
                reason="a plan that should not survive the safety layer"),
                checkout)
            assert typed.outcome is Outcome.REFUSED
        finally:
            await browser.close()
