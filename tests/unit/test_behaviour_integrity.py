"""Phase 0 — the ways the report could still mislead, and the fixes for them.

Each test here pins one property that the rest of the system depends on but
that nothing previously enforced: a diagnosis survives into the report, a
defect the agent detects is actually reported, and a score never travels
without the caveat that qualifies it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.behaviour import scoring
from app.behaviour.executor import describe_dispatch_failure
from app.behaviour.models import (ActionIntent, ActionKind, ActionRecord,
                                  InteractionTiming, Outcome, PageVisit,
                                  Severity)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)

PLAYWRIGHT_COVERED = """Locator.click: Timeout 6000ms exceeded.
Call log:
  - waiting for locator("[data-aq-ref=\\"e25\\"]").first
  -   locator resolved to <a title="Cart" class="E7_UTN" data-aq-ref="e25">
  - attempting click action
  -   waiting for element to be visible, enabled and stable
  -   element is visible, enabled and stable
  -   scrolling into view if needed
  -   done scrolling
  -   <div class="login-modal-overlay"></div> intercepts pointer events
"""

PLAYWRIGHT_UNSTABLE = """Locator.click: Timeout 6000ms exceeded.
Call log:
  - attempting click action
  -   element is not stable
"""


def act(seq: int, *, outcome=Outcome.SUCCESS, blocked=None,
        element="Cart") -> ActionRecord:
    return ActionRecord(
        seq=seq, at=T0 + timedelta(milliseconds=seq * 100),
        intent=ActionIntent(kind=ActionKind.CLICK, reason="open the cart"),
        element_label=element, category="button", outcome=outcome,
        blocked_reason=blocked, timing=InteractionTiming(perceived_ms=50))


# ── the diagnosis must survive the trip into the report ──────────────────

def test_the_reason_a_click_could_not_land_is_kept_not_truncated_away():
    """The reason sits at the END of Playwright's message.

    A head-slice keeps "Timeout 6000ms exceeded" — which says nothing — and
    discards "intercepts pointer events", which is the entire finding.
    """
    observed, reason = describe_dispatch_failure(
        TimeoutError(PLAYWRIGHT_COVERED))
    assert reason == "another element covers it"
    assert "another element covers it" in observed
    assert "login-modal-overlay" in observed


def test_different_actionability_failures_are_told_apart():
    _, covered = describe_dispatch_failure(TimeoutError(PLAYWRIGHT_COVERED))
    _, unstable = describe_dispatch_failure(TimeoutError(PLAYWRIGHT_UNSTABLE))
    assert covered != unstable
    assert unstable == "it was still moving"


def test_a_non_actionability_error_keeps_its_message_and_claims_no_reason():
    observed, reason = describe_dispatch_failure(ValueError("no such frame"))
    assert reason is None
    assert "no such frame" in observed


# ── a defect the agent detects must be a defect the agent reports ────────

def test_a_control_the_browser_could_not_action_becomes_a_finding():
    actions = [act(1), act(2, outcome=Outcome.ERROR,
                          blocked="another element covers it")]
    findings = scoring.generate_findings(actions, [], [], [])
    obscured = [f for f in findings if f.id == "UX-OBSCURED"]
    assert obscured, "an unclickable control produced no finding"
    assert obscured[0].severity is Severity.HIGH
    assert "another element covers it" in obscured[0].observed


def test_a_dispatch_error_with_no_actionability_reason_is_not_a_ux_finding():
    """A tooling failure is not a defect in the site under test."""
    actions = [act(1, outcome=Outcome.ERROR, blocked=None)]
    findings = scoring.generate_findings(actions, [], [], [])
    assert not [f for f in findings if f.id == "UX-OBSCURED"]


# ── a score never travels without what qualifies it ──────────────────────

def test_a_session_that_ran_to_plan_carries_no_caveat():
    assert scoring.describe_degradation(
        model_timeouts=0, model_calls=6, actions_dispatched=30,
        planned_journeys=3, journeys_run=3) == []


def test_a_heuristic_fallback_session_says_so():
    notes = scoring.describe_degradation(model_timeouts=7, model_calls=11,
                                         actions_dispatched=27,
                                         planned_journeys=3, journeys_run=3)
    assert any("deadline" in n for n in notes)
    assert any("7" in n and "11" in n for n in notes)


def test_a_budget_killed_session_says_so():
    notes = scoring.describe_degradation(budget_stopped=True,
                                         actions_dispatched=27)
    assert any("budget" in n for n in notes)


def test_the_score_object_carries_the_degradation_flag():
    score = scoring.compute_score([act(1), act(2)], [], [])
    assert score.degraded is False and score.degradation == []
    score.degradation = scoring.describe_degradation(model_timeouts=3,
                                                     model_calls=4)
    score.degraded = bool(score.degradation)
    assert score.degraded is True


# ── twenty copies of one defect are one defect ───────────────────────────

class _Err:
    """Stands in for a Playwright pageerror payload."""

    def __init__(self, message: str, name: str = "", stack: str = ""):
        self._m, self.name, self.stack = message, name, stack

    def __str__(self) -> str:
        return self._m


class _Sink:
    """The two attributes _record_page_error actually touches."""

    def __init__(self):
        self.errors: list[str] = []
        self._error_counts: dict[str, int] = {}


def _record(sink, err):
    from app.behaviour.agent import UserBehaviourAgent
    UserBehaviourAgent._record_page_error(sink, err)


def test_the_same_page_error_twenty_times_is_one_entry_with_a_count():
    """Otherwise duplicates fill the report's error list and hide the rest."""
    sink = _Sink()
    for _ in range(20):
        _record(sink, _Err("he"))
    _record(sink, _Err("something else entirely"))
    assert len(sink.errors) == 2
    assert "(x20)" in sink.errors[0]
    assert "something else entirely" in sink.errors[1]


def test_a_thrown_non_error_says_that_is_why_there_is_no_stack():
    """`throw "he"` gives a two-character message, no name and no stack.

    Reporting the message alone is unactionable; saying the site threw a
    non-Error IS the diagnosis.
    """
    sink = _Sink()
    _record(sink, _Err("he"))
    assert "non-Error value was thrown" in sink.errors[0]


def test_a_real_error_keeps_its_name_and_first_stack_frame():
    sink = _Sink()
    _record(sink, _Err("x is not a function", name="TypeError",
                       stack="TypeError: x is not a function\n"
                             "    at checkout.js:42:9\n    at main.js:1:1"))
    entry = sink.errors[0]
    assert "TypeError: x is not a function" in entry
    assert "checkout.js:42:9" in entry
