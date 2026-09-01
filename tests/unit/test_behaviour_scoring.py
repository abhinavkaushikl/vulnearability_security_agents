"""UX scoring and finding generation.

The property under test throughout: a dimension with no observations scores
`None` and is excluded, never scored zero. A zero would be a claim about the
site; None is the truth about the session.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.behaviour import scoring
from app.behaviour.models import (A11ySnapshot, ActionIntent, ActionKind,
                                  ActionRecord, InteractionTiming, Journey,
                                  JourneyStep, Outcome, PageModel, PageVisit,
                                  PageVitals, ScoreBand, Severity)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def action(seq: int, *, kind=ActionKind.CLICK, category="button",
           outcome=Outcome.SUCCESS, perceived=None, ui=None, net=None,
           shift=None, fps=None, dropped=None, frames=None,
           element="Add to cart", journey="j-1", step="Add it to the cart",
           errors=None) -> ActionRecord:
    return ActionRecord(
        seq=seq, at=T0 + timedelta(milliseconds=seq * 100),
        intent=ActionIntent(kind=kind, journey_id=journey, step_label=step,
                            reason=step),
        element_label=element, category=category, outcome=outcome,
        console_errors=errors or [],
        timing=InteractionTiming(
            perceived_ms=perceived, ui_response_ms=ui,
            network_complete_ms=net, layout_shift=shift,
            scroll_fps=fps, dropped_frames=dropped, frame_count=frames))


def page_model(**a11y) -> PageModel:
    base = dict(focusable_count=40, unlabelled_controls=0,
                images_missing_alt=0, heading_order_ok=True,
                landmark_roles=["banner", "main"], has_skip_link=True)
    base.update(a11y)
    return PageModel(url="https://x.test/", a11y=A11ySnapshot(**base))


def visit(**vitals) -> PageVisit:
    return PageVisit(url="https://x.test/", vitals=PageVitals(**vitals))


# ── the honest default ───────────────────────────────────────────────────

def test_nothing_observed_is_unrated_not_zero():
    score = scoring.compute_score([], [], [])
    assert score.overall is None
    assert score.band is ScoreBand.UNRATED
    assert all(c.score is None and c.n == 0 for c in score.components)


def test_a_component_with_no_data_is_excluded_not_scored_zero():
    """A site where nothing was scrollable must not be punished for it."""
    actions = [action(1, perceived=80, ui=80)]
    score = scoring.compute_score(actions, [page_model()], [visit()])
    scroll = next(c for c in score.components if c.name == "Scroll Experience")
    assert scroll.score is None
    assert score.overall is not None and score.overall > 50


def test_every_component_carries_its_sample_size():
    actions = [action(i, perceived=100, ui=100) for i in range(1, 6)]
    score = scoring.compute_score(actions, [page_model()], [visit()])
    speed = next(c for c in score.components if c.name == "Interaction Speed")
    assert speed.n == 5
    assert "5" in speed.basis


# ── the curve ────────────────────────────────────────────────────────────

def test_instant_interactions_score_full_marks_and_slow_ones_do_not():
    fast = scoring.compute_score(
        [action(i, perceived=90, ui=90) for i in range(1, 5)],
        [page_model()], [visit()])
    slow = scoring.compute_score(
        [action(i, perceived=1400, ui=1400) for i in range(1, 5)],
        [page_model()], [visit()])
    f = next(c for c in fast.components if c.name == "Interaction Speed")
    s = next(c for c in slow.components if c.name == "Interaction Speed")
    assert f.score == 100
    assert s.score is not None and s.score < 40


def test_the_scoring_curve_is_monotonic():
    """Slower must never score higher. Obvious, and worth pinning."""
    previous = 101
    for ms in (50, 150, 250, 400, 700, 1200, 2500):
        s = scoring.compute_score([action(1, perceived=ms, ui=ms)],
                                  [page_model()], [visit()])
        value = next(c for c in s.components
                     if c.name == "Interaction Speed").score
        assert value is not None and value <= previous, ms
        previous = value


def test_scoring_is_deterministic():
    actions = [action(i, perceived=120 + i * 30, ui=120 + i * 30)
               for i in range(1, 8)]
    a = scoring.compute_score(actions, [page_model()], [visit(lcp_ms=1800)])
    b = scoring.compute_score(actions, [page_model()], [visit(lcp_ms=1800)])
    assert a.overall == b.overall
    assert [c.score for c in a.components] == [c.score for c in b.components]


def test_reliability_ignores_refusals_and_punishes_dead_controls():
    """Declining to press 'Place order' says nothing about the site."""
    with_refusals = [
        action(1, outcome=Outcome.SUCCESS, perceived=90, ui=90),
        action(2, outcome=Outcome.REFUSED),
        action(3, outcome=Outcome.REFUSED),
    ]
    r = next(c for c in scoring.compute_score(
        with_refusals, [page_model()], [visit()]).components
        if c.name == "Interaction Reliability")
    assert r.n == 1 and r.score == 100

    with_dead = [
        action(1, outcome=Outcome.SUCCESS, perceived=90, ui=90),
        action(2, outcome=Outcome.NO_RESPONSE),
    ]
    r2 = next(c for c in scoring.compute_score(
        with_dead, [page_model()], [visit()]).components
        if c.name == "Interaction Reliability")
    assert r2.score == 50


def test_an_action_that_fetches_without_feedback_is_penalised():
    silent = [action(1, outcome=Outcome.UNEXPECTED, net=300, ui=None),
              action(2, outcome=Outcome.SUCCESS, net=300, ui=60, perceived=60)]
    r = next(c for c in scoring.compute_score(
        silent, [page_model()], [visit()]).components
        if c.name == "Responsiveness")
    assert r.score is not None and r.score < 60
    assert "no visible feedback" in r.basis


# ── findings ─────────────────────────────────────────────────────────────

def test_a_dead_control_produces_a_finding_that_cites_the_action():
    actions = [action(7, outcome=Outcome.NO_RESPONSE,
                      element="Join the mailing list")]
    findings = scoring.generate_findings(actions, [page_model()], [visit()], [])
    dead = next(f for f in findings if f.id == "UX-DEAD")
    assert dead.severity in (Severity.HIGH, Severity.CRITICAL)
    assert "Join the mailing list" in dead.observed
    assert dead.evidence_seq == [7]


def test_a_hover_that_opens_nothing_is_not_a_dead_control():
    """Most navigation is click-driven. Counting hovers here would report
    every such site as broken."""
    actions = [action(1, kind=ActionKind.HOVER, category="menu",
                      outcome=Outcome.NO_RESPONSE, element="Menu")]
    findings = scoring.generate_findings(actions, [page_model()], [visit()], [])
    assert not any(f.id == "UX-DEAD" for f in findings)


def test_a_slow_category_produces_a_finding_and_a_fast_one_does_not():
    slow = [action(i, category="search", perceived=900, ui=900)
            for i in range(1, 4)]
    ids = {f.id for f in scoring.generate_findings(
        slow, [page_model()], [visit()], [])}
    assert "UX-SLOW-SEARCH" in ids

    fast = [action(i, category="search", perceived=90, ui=90)
            for i in range(1, 4)]
    ids2 = {f.id for f in scoring.generate_findings(
        fast, [page_model()], [visit()], [])}
    assert "UX-SLOW-SEARCH" not in ids2


def test_findings_are_ordered_most_severe_first():
    actions = [
        action(1, outcome=Outcome.NO_RESPONSE, element="Dead"),
        action(2, outcome=Outcome.NO_RESPONSE, element="Also dead"),
        action(3, outcome=Outcome.NO_RESPONSE, element="Third"),
    ]
    findings = scoring.generate_findings(
        actions, [page_model(unlabelled_controls=3)], [visit()], [])
    ranks = [f.severity.rank for f in findings]
    assert ranks == sorted(ranks, reverse=True)


def test_every_finding_states_both_what_was_observed_and_what_was_expected():
    actions = [action(1, outcome=Outcome.NO_RESPONSE),
               action(2, category="search", perceived=1400, ui=1400),
               action(3, category="scroll", fps=22, frames=100, dropped=40,
                      perceived=None),
               action(4, net=200, ui=None, outcome=Outcome.UNEXPECTED)]
    findings = scoring.generate_findings(
        actions, [page_model(unlabelled_controls=2)],
        [visit(cls=0.4)], [])
    assert findings
    for f in findings:
        assert f.observed and f.expected and f.impact and f.recommendation


# ── journeys ─────────────────────────────────────────────────────────────

def journey(n: int = 3) -> Journey:
    return Journey(id="j-1", name="Shop", goal="get a product into the cart",
                   steps=[JourneyStep(label=f"step {i}", action="click")
                          for i in range(n)])


def test_the_agents_own_bookkeeping_decides_completion_not_a_label_count():
    """Recovery actions reuse the step label they were recovering. Counting
    distinct labels makes a journey that retried twice and gave up look
    completed — which is exactly the bug this argument exists to prevent."""
    j = journey(3)
    actions = [action(1, step="step 0"), action(2, step="step 0"),
               action(3, step="step 0", outcome=Outcome.NO_RESPONSE)]
    inferred = scoring.journey_outcomes([j], actions)
    assert inferred[0].completed is False

    told = scoring.journey_outcomes([j], actions, {
        "j-1": {"steps_attempted": 1, "completed": False,
                "abandoned_at": "step 0", "reason": "three attempts failed"}})
    assert told[0].completed is False
    assert told[0].abandoned_at == "step 0"
    assert told[0].steps_attempted == 1

    done = scoring.journey_outcomes([j], actions, {
        "j-1": {"steps_attempted": 3, "completed": True,
                "abandoned_at": None, "reason": None}})
    assert done[0].completed is True
    assert done[0].abandoned_at is None


def test_an_abandoned_journey_becomes_a_finding():
    j = journey(4)
    actions = [action(1, step="step 0")]
    outcomes = scoring.journey_outcomes([j], actions, {
        "j-1": {"steps_attempted": 2, "completed": False,
                "abandoned_at": "step 2", "reason": "the control did nothing"}})
    findings = scoring.generate_findings(actions, [page_model()], [visit()],
                                         outcomes)
    abandoned = next(f for f in findings if f.id.startswith("UX-ABANDON"))
    assert "step 2" in abandoned.observed
    assert "the control did nothing" in abandoned.observed


# ── category latencies ───────────────────────────────────────────────────

def test_a_p95_needs_three_samples_before_it_is_reported():
    rows = scoring.summarise_category(
        [action(1, category="search", perceived=100, ui=100),
         action(2, category="search", perceived=200, ui=200)])
    assert rows[0]["n"] == 2
    assert rows[0]["p95_ms"] is None

    rows3 = scoring.summarise_category(
        [action(i, category="search", perceived=i * 100, ui=i * 100)
         for i in range(1, 4)])
    assert rows3[0]["p95_ms"] is not None


def test_actions_with_no_response_are_excluded_from_latency_not_counted_as_fast():
    rows = scoring.summarise_category([
        action(1, category="button", perceived=100, ui=100),
        action(2, category="button", outcome=Outcome.NO_RESPONSE),
    ])
    assert rows[0]["n"] == 1
    assert rows[0]["median_ms"] == 100
