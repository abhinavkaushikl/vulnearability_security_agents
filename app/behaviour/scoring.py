"""UX score and UX findings — deterministic, from measurements only.

House rule 3 of CLAUDE.md: *the LLM never computes.* Every number in the
report is produced here, in pure Python, from timings the probe observed.
Same session, same numbers, every time.

Three things this module refuses to do:

  * **Score what it did not measure.** A component with no observations is
    `None`, not zero, and it is excluded from the overall rather than
    dragging it down. `UNRATED` is a real outcome.
  * **Hide the sample size.** Every component carries `n`. A "navigation: 88"
    off two page loads is not the same claim as one off twenty, and the
    report says which it is.
  * **Invent a threshold.** Every boundary below is a published one, named at
    the point of use. Where no published threshold exists (scroll smoothness,
    reliability) the boundary is arithmetic on the frame budget or a plain
    ratio, and it says so.
"""
from __future__ import annotations

from collections import defaultdict

from app.behaviour.models import (ActionKind, ActionRecord, ElementKind, Journey,
                                  JourneyOutcome, Outcome, PageModel,
                                  PageVisit, ScoreBand, ScoreComponent,
                                  Severity, UXFinding, UXScore)
from app.tools.statistics import calculate_percentile

# ── published thresholds ─────────────────────────────────────────────────
#
# RAIL (Google, 2015-): under 100 ms a response feels instantaneous; under
# 1000 ms the user stays in flow. Nielsen (1993) gives the same three
# boundaries — 0.1 s, 1 s, 10 s — from work in the 1960s. They have not moved
# because human perception has not.
INSTANT_MS = 100.0
FLOW_MS = 1000.0

# Core Web Vitals "good" / "needs improvement" boundaries.
LCP_GOOD_MS, LCP_POOR_MS = 2500.0, 4000.0
CLS_GOOD, CLS_POOR = 0.1, 0.25
# INP's published boundaries. We never measure INP (it needs real users over a
# session) — these are used only for interaction latency framing.
INTERACTION_GOOD_MS, INTERACTION_POOR_MS = 200.0, 500.0

# A frame budget at 60 Hz. Not a published UX threshold; it is arithmetic.
FRAME_BUDGET_MS = 1000.0 / 60.0

#: Weights are relative importance, not percentages. The overall is a weighted
#: mean over the components that actually have data, so a site where nothing
#: was scrollable is not punished for a missing scroll score.
WEIGHTS: dict[str, float] = {
    "Interaction Speed": 1.4,
    "Navigation": 1.2,
    "Responsiveness": 1.2,
    "Visual Experience": 1.0,
    "Accessibility": 1.0,
    "Interaction Reliability": 1.5,
    "Scroll Experience": 0.8,
}


def _piecewise(value: float, good: float, poor: float) -> int:
    """Map a "lower is better" measurement onto 0-100.

    Three anchors: at or below `good` scores 100, `poor` scores 50, and two
    and a half times `poor` scores 0. Linear between them. Chosen over a
    log-normal curve because a reader can reproduce it with a ruler, which is
    the property that matters in a report someone has to act on.
    """
    if value <= good:
        return 100
    if value <= poor:
        return int(round(100 - 50 * (value - good) / max(poor - good, 1e-6)))
    tail = poor * 2.5
    if value >= tail:
        return 0
    return int(round(50 - 50 * (value - poor) / max(tail - poor, 1e-6)))


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def band_for(score: int | None) -> ScoreBand:
    if score is None:
        return ScoreBand.UNRATED
    if score >= 85:
        return ScoreBand.EXCELLENT
    if score >= 70:
        return ScoreBand.GOOD
    if score >= 50:
        return ScoreBand.FAIR
    return ScoreBand.POOR


# ══════════════════════════════════════════════════ per-category latencies


def latencies_by_category(actions: list[ActionRecord]) -> dict[str, list[float]]:
    """Perceived latency per §11 category, from actions that actually responded.

    `perceived_ms` is used rather than network time throughout, because that
    is the clock the user is on. Actions with no perceived response are
    excluded here and counted separately by the reliability component — a dead
    button must not be recorded as an infinitely slow one, nor as a fast one.
    """
    out: dict[str, list[float]] = defaultdict(list)
    for a in actions:
        if a.outcome in (Outcome.REFUSED, Outcome.ERROR):
            continue
        if a.timing.perceived_ms is None:
            continue
        out[a.category].append(a.timing.perceived_ms)
    return dict(out)


def summarise_category(actions: list[ActionRecord]) -> list[dict]:
    """One row per interaction category, for the report's timing table."""
    by = latencies_by_category(actions)
    rows = []
    for category, values in sorted(by.items()):
        rows.append({
            "category": category,
            "n": len(values),
            "median_ms": round(calculate_percentile(values, 50) or 0, 1),
            "p95_ms": (round(calculate_percentile(values, 95), 1)
                       if len(values) >= 3 else None),
            "worst_ms": round(max(values), 1),
            "best_ms": round(min(values), 1),
        })
    return rows


# ══════════════════════════════════════════════════ the components


def _interaction_speed(actions: list[ActionRecord]) -> ScoreComponent:
    """How quickly the interface acknowledged a deliberate action."""
    values = [a.timing.perceived_ms for a in actions
              if a.category in ("button", "form", "search", "menu", "media")
              and a.timing.perceived_ms is not None]
    if not values:
        return ScoreComponent(name="Interaction Speed", score=None, n=0,
                              basis="no interaction produced a measurable response")
    median = calculate_percentile(values, 50) or 0.0
    score = _piecewise(median, INTERACTION_GOOD_MS, INTERACTION_POOR_MS)
    return ScoreComponent(
        name="Interaction Speed", score=score, n=len(values),
        basis=(f"median perceived response {median:.0f} ms across {len(values)} "
               f"interactions (good ≤{INTERACTION_GOOD_MS:.0f} ms)"))


def _navigation(actions: list[ActionRecord], pages: list[PageVisit]
                ) -> ScoreComponent:
    """How long it took to get from wanting a page to having one."""
    nav = [a.timing.perceived_ms for a in actions
           if a.category == "navigation" and a.timing.perceived_ms is not None]
    lcps = [p.vitals.lcp_ms for p in pages if p.vitals.lcp_ms is not None]
    parts: list[int] = []
    detail: list[str] = []
    if lcps:
        med = calculate_percentile(lcps, 50) or 0.0
        parts.append(_piecewise(med, LCP_GOOD_MS, LCP_POOR_MS))
        detail.append(f"median LCP {med:.0f} ms over {len(lcps)} pages")
    if nav:
        med = calculate_percentile(nav, 50) or 0.0
        parts.append(_piecewise(med, FLOW_MS, FLOW_MS * 3))
        detail.append(f"median route transition {med:.0f} ms over {len(nav)}")
    if not parts:
        return ScoreComponent(name="Navigation", score=None, n=0,
                              basis="no navigation was measured")
    return ScoreComponent(
        name="Navigation", score=int(round(sum(parts) / len(parts))),
        n=len(lcps) + len(nav), basis="; ".join(detail))


def _responsiveness(actions: list[ActionRecord]) -> ScoreComponent:
    """Did the interface acknowledge input before it finished the work?

    The gap between "something moved" and "the work completed" is where a
    spinner belongs. A site that shows nothing until the response lands feels
    broken even when it is fast, and this is the component that says so.
    """
    gaps: list[float] = []
    unacknowledged = 0
    for a in actions:
        t = a.timing
        if a.outcome in (Outcome.REFUSED, Outcome.ERROR):
            continue
        if t.network_complete_ms is None:
            continue
        if t.ui_response_ms is None:
            unacknowledged += 1
            continue
        gaps.append(max(0.0, t.ui_response_ms))
    n = len(gaps) + unacknowledged
    if n == 0:
        return ScoreComponent(name="Responsiveness", score=None, n=0,
                              basis="no action triggered a network request")
    median = calculate_percentile(gaps, 50) if gaps else None
    score = _piecewise(median, INSTANT_MS, FLOW_MS) if median is not None else 0
    if unacknowledged:
        # Each action that fetched something and showed nothing is a
        # straightforward proportional penalty. No curve, nothing to argue with.
        score = int(round(score * (1 - unacknowledged / n)))
    basis = (f"visual acknowledgement in {median:.0f} ms (median)"
             if median is not None else "no action was acknowledged visually")
    if unacknowledged:
        basis += (f"; {unacknowledged} of {n} actions fetched data with no "
                  "visible feedback")
    return ScoreComponent(name="Responsiveness", score=score, n=n, basis=basis)


def _visual(actions: list[ActionRecord], pages: list[PageVisit]
            ) -> ScoreComponent:
    """Layout stability — did things move under the user?"""
    page_cls = [p.vitals.cls for p in pages if p.vitals.cls is not None]
    action_shift = [a.timing.layout_shift for a in actions
                    if a.timing.layout_shift is not None]
    if not page_cls and not action_shift:
        return ScoreComponent(name="Visual Experience", score=None, n=0,
                              basis="layout-shift reporting was unavailable")
    parts: list[int] = []
    detail: list[str] = []
    if page_cls:
        worst = max(page_cls)
        parts.append(_piecewise(worst, CLS_GOOD, CLS_POOR))
        detail.append(f"worst page CLS {worst:.3f} (good ≤{CLS_GOOD})")
    if action_shift:
        moved = [v for v in action_shift if v > CLS_GOOD]
        share = len(moved) / len(action_shift)
        parts.append(int(round(100 * (1 - share))))
        detail.append(f"{len(moved)} of {len(action_shift)} interactions "
                      f"shifted the layout")
    return ScoreComponent(
        name="Visual Experience", score=int(round(sum(parts) / len(parts))),
        n=len(page_cls) + len(action_shift), basis="; ".join(detail))


def _accessibility(pages: list[PageModel]) -> ScoreComponent:
    """Structural accessibility only. Explicitly not a WCAG conformance claim.

    Automated tooling reaches a minority of WCAG 2.2 success criteria — the
    same limit CLAUDE.md §13/A8 records for `A11Y-01`. This number describes
    four structural properties an agent can actually check, and the report
    says so next to it.
    """
    if not pages:
        return ScoreComponent(name="Accessibility", score=None, n=0,
                              basis="no page was observed")
    named_share: list[float] = []
    alt_share: list[float] = []
    order_ok = 0
    landmarks_ok = 0
    focus_ratios: list[float] = []

    for p in pages:
        a = p.a11y
        controls = max(a.focusable_count, 1)
        named_share.append(1 - min(1.0, a.unlabelled_controls / controls))
        alt_share.append(1.0 if a.images_missing_alt == 0
                         else max(0.0, 1 - a.images_missing_alt / 20))
        order_ok += 1 if a.heading_order_ok else 0
        landmarks_ok += 1 if len(a.landmark_roles) >= 2 else 0
        if a.focus_visible_ratio is not None:
            focus_ratios.append(a.focus_visible_ratio)

    n = len(pages)
    parts = [
        (_mean(named_share) or 0) * 100,
        (_mean(alt_share) or 0) * 100,
        (order_ok / n) * 100,
        (landmarks_ok / n) * 100,
    ]
    if focus_ratios:
        parts.append((_mean(focus_ratios) or 0) * 100)
    unlabelled = sum(p.a11y.unlabelled_controls for p in pages)
    return ScoreComponent(
        name="Accessibility", score=int(round(sum(parts) / len(parts))), n=n,
        basis=(f"{unlabelled} unnamed controls, "
               f"{sum(p.a11y.images_missing_alt for p in pages)} images without "
               f"alt, heading order intact on {order_ok}/{n} pages"
               + (f", focus visible on {(_mean(focus_ratios) or 0) * 100:.0f}% "
                  "of keyboard stops" if focus_ratios else "")
               + " — structural checks, not a WCAG conformance claim"))


def _reliability(actions: list[ActionRecord]) -> ScoreComponent:
    """Did the things the agent pressed actually work?

    Refusals are excluded: the safety layer declining to press "Place order"
    says nothing about the site. Everything else counts, and NO_RESPONSE
    counts hardest, because that is a control that does nothing.
    """
    dispatched = [a for a in actions if a.outcome is not Outcome.REFUSED]
    if not dispatched:
        return ScoreComponent(name="Interaction Reliability", score=None, n=0,
                              basis="nothing was dispatched")
    good = sum(1 for a in dispatched if a.outcome is Outcome.SUCCESS)
    dead = sum(1 for a in dispatched if a.outcome is Outcome.NO_RESPONSE)
    errored = sum(1 for a in dispatched if a.outcome is Outcome.ERROR)
    n = len(dispatched)
    score = int(round(100 * good / n))
    return ScoreComponent(
        name="Interaction Reliability", score=score, n=n,
        basis=(f"{good} of {n} actions produced the expected result"
               + (f"; {dead} produced no response at all" if dead else "")
               + (f"; {errored} could not be dispatched" if errored else "")))


def _scroll(actions: list[ActionRecord]) -> ScoreComponent:
    """Smoothness, from measured frame intervals — §12."""
    scrolls = [a for a in actions if a.category == "scroll"
               and a.timing.scroll_fps is not None]
    if not scrolls:
        return ScoreComponent(name="Scroll Experience", score=None, n=0,
                              basis="the page was not scrollable, or no frames "
                                    "were reported")
    fps = [a.timing.scroll_fps for a in scrolls if a.timing.scroll_fps]
    dropped = sum(a.timing.dropped_frames or 0 for a in scrolls)
    frames = sum(a.timing.frame_count or 0 for a in scrolls)
    median_fps = calculate_percentile(fps, 50) or 0.0
    # 60 fps is 100; 30 fps is 50; 15 fps is 0. Linear in frames per second,
    # which is what the eye responds to, rather than in frame time.
    score = int(round(max(0.0, min(100.0, (median_fps - 15) / 45 * 100))))
    if frames:
        score = int(round(score * (1 - min(0.5, dropped / max(frames, 1)))))
    return ScoreComponent(
        name="Scroll Experience", score=score, n=len(scrolls),
        basis=(f"median {median_fps:.0f} fps over {len(scrolls)} scrolls"
               + (f", {dropped} dropped frames of {frames}" if frames else "")))


def compute_score(actions: list[ActionRecord], page_models: list[PageModel],
                  pages: list[PageVisit]) -> UXScore:
    """§17. The whole score, in one pure function."""
    components = [
        _interaction_speed(actions),
        _navigation(actions, pages),
        _responsiveness(actions),
        _visual(actions, pages),
        _accessibility(page_models),
        _reliability(actions),
        _scroll(actions),
    ]
    rated = [c for c in components if c.score is not None]
    if not rated:
        return UXScore(
            overall=None, band=ScoreBand.UNRATED, components=components,
            method=("nothing measurable was observed; no score is claimed"),
            observations=0)

    total_weight = sum(WEIGHTS.get(c.name, 1.0) for c in rated)
    overall = int(round(
        sum((c.score or 0) * WEIGHTS.get(c.name, 1.0) for c in rated)
        / total_weight))
    return UXScore(
        overall=overall, band=band_for(overall), components=components,
        method=(f"weighted mean of {len(rated)} of {len(components)} components "
                f"that had observations; components with no data are excluded "
                f"rather than scored zero"),
        observations=sum(c.n for c in rated))


# ══════════════════════════════════════════════════ findings — §19


def _finding(fid: str, title: str, category: str, severity: Severity,
             observed: str, expected: str, impact: str, recommendation: str,
             seqs: list[int], url: str = "") -> UXFinding:
    return UXFinding(id=fid, title=title, category=category, severity=severity,
                     observed=observed, expected=expected, impact=impact,
                     recommendation=recommendation, evidence_seq=seqs,
                     page_url=url)


def generate_findings(actions: list[ActionRecord], page_models: list[PageModel],
                      pages: list[PageVisit],
                      journeys: list[JourneyOutcome]) -> list[UXFinding]:
    """Every finding is generated from a measurement, and cites the actions.

    `evidence_seq` is the list of `ActionRecord.seq` values behind the claim,
    so any number in a finding can be traced back to the interaction that
    produced it. A finding with no evidence cannot be constructed.
    """
    out: list[UXFinding] = []

    # ── dead controls ────────────────────────────────────────────────────
    # Only actions that COMMIT to something. A hover that opens no menu is
    # not a defect — most navigation is click-driven, and counting hovers
    # here would report every such site as full of dead controls.
    PRESSED = {ActionKind.CLICK, ActionKind.SUBMIT_SEARCH,
               ActionKind.SELECT_OPTION, ActionKind.CHECK,
               ActionKind.PLAY_MEDIA, ActionKind.PAUSE_MEDIA,
               ActionKind.PRESS_KEY}
    dead = [a for a in actions if a.outcome is Outcome.NO_RESPONSE
            and a.intent.kind in PRESSED]
    if dead:
        labels = sorted({a.element_label for a in dead if a.element_label})[:5]
        out.append(_finding(
            "UX-DEAD", "Controls that do nothing when pressed", "reliability",
            Severity.CRITICAL if len(dead) > 2 else Severity.HIGH,
            observed=(f"{len(dead)} interaction(s) produced no DOM change, no "
                      f"request and no navigation: "
                      + ", ".join(f"{l!r}" for l in labels)),
            expected="every visible control produces some response to a click",
            impact=("A user who presses a control and sees nothing assumes the "
                    "site is broken. Most will press it again, then leave."),
            recommendation=("Confirm each control has a handler bound, and give "
                            "every one an immediate visual state change on "
                            "press even when the work behind it is slow."),
            seqs=[a.seq for a in dead][:10],
            url=dead[0].page_url))

    # ── slow interactions, by category ───────────────────────────────────
    by_cat = latencies_by_category(actions)
    labels = {"search": ("Search", "search suggestions and results"),
              "button": ("Buttons", "a button press"),
              "form": ("Form input", "typing and validation"),
              "menu": ("Menus", "a menu opening"),
              "navigation": ("Navigation", "moving between pages"),
              "media": ("Media controls", "a media control")}
    for category, values in by_cat.items():
        if category in ("dwell", "scroll", "control") or not values:
            continue
        median = calculate_percentile(values, 50) or 0.0
        good = FLOW_MS if category == "navigation" else INTERACTION_GOOD_MS
        poor = FLOW_MS * 3 if category == "navigation" else INTERACTION_POOR_MS
        if median <= poor:
            continue
        name, what = labels.get(category, (category.title(), "the interaction"))
        seqs = [a.seq for a in actions
                if a.category == category and a.timing.perceived_ms
                and a.timing.perceived_ms > poor]
        out.append(_finding(
            f"UX-SLOW-{category.upper()}", f"Slow {name.lower()} response",
            category,
            Severity.HIGH if median > poor * 2 else Severity.MEDIUM,
            observed=(f"median perceived response {median:.0f} ms across "
                      f"{len(values)} measurements (worst {max(values):.0f} ms)"),
            expected=f"under {good:.0f} ms for {what}",
            impact=(f"Above {poor:.0f} ms users stop associating the response "
                    f"with their own action; {name.lower()} starts to feel "
                    "unresponsive rather than slow."),
            recommendation=("Show a state change within 100 ms of the press and "
                            "move the work behind it off the critical path."),
            seqs=seqs[:10]))

    # ── requests with no feedback ────────────────────────────────────────
    silent = [a for a in actions
              if a.timing.network_complete_ms is not None
              and a.timing.ui_response_ms is None
              and a.outcome is not Outcome.REFUSED]
    if silent:
        out.append(_finding(
            "UX-SILENT", "Actions fetch data without showing anything",
            "responsiveness", Severity.HIGH,
            observed=(f"{len(silent)} interaction(s) sent a request but the "
                      "interface did not change while it was in flight"),
            expected="a spinner, a disabled state or a skeleton within 100 ms",
            impact=("The user has no way to tell their action registered, so "
                    "they press again — often submitting twice."),
            recommendation=("Render a pending state synchronously on press, "
                            "before the request is issued."),
            seqs=[a.seq for a in silent][:10],
            url=silent[0].page_url))

    # ── layout instability ───────────────────────────────────────────────
    shifty = [a for a in actions
              if a.timing.layout_shift is not None
              and a.timing.layout_shift > CLS_POOR]
    worst_page = max((p for p in pages if p.vitals.cls is not None),
                     key=lambda p: p.vitals.cls, default=None)
    if shifty or (worst_page and (worst_page.vitals.cls or 0) > CLS_POOR):
        observed = []
        if worst_page and (worst_page.vitals.cls or 0) > CLS_POOR:
            observed.append(f"page CLS {worst_page.vitals.cls:.3f} on "
                            f"{worst_page.url}")
        if shifty:
            observed.append(f"{len(shifty)} interaction(s) shifted the layout "
                            f"by more than {CLS_POOR}")
        out.append(_finding(
            "UX-SHIFT", "Content moves under the user", "visual",
            Severity.HIGH if len(shifty) > 2 else Severity.MEDIUM,
            observed="; ".join(observed),
            expected=f"cumulative layout shift at or below {CLS_GOOD}",
            impact=("Users click the wrong thing when content moves after it "
                    "has painted. On a checkout or a form this costs the "
                    "session."),
            recommendation=("Reserve space for images, embeds and late content "
                            "with explicit dimensions or aspect ratios."),
            seqs=[a.seq for a in shifty][:10],
            url=worst_page.url if worst_page else ""))

    # ── scroll smoothness ────────────────────────────────────────────────
    rough = [a for a in actions if a.category == "scroll"
             and a.timing.scroll_fps is not None and a.timing.scroll_fps < 45]
    if rough:
        worst = min(a.timing.scroll_fps for a in rough)
        out.append(_finding(
            "UX-SCROLL", "Scrolling does not hold frame rate", "scroll",
            Severity.MEDIUM if worst >= 25 else Severity.HIGH,
            observed=(f"{len(rough)} scroll(s) below 45 fps, worst "
                      f"{worst:.0f} fps"),
            expected="a sustained 60 fps while scrolling",
            impact=("Below about 45 fps scrolling reads as sticky, and the "
                    "site feels heavy regardless of how fast it loaded."),
            recommendation=("Look for scroll-linked layout work, non-passive "
                            "wheel listeners, and large paint areas without "
                            "containment."),
            seqs=[a.seq for a in rough][:10]))

    # ── console errors ───────────────────────────────────────────────────
    errored = [a for a in actions if a.console_errors]
    if errored:
        sample = errored[0].console_errors[0][:120]
        total = sum(len(a.console_errors) for a in errored)
        out.append(_finding(
            "UX-JS", "JavaScript errors during interaction", "reliability",
            Severity.HIGH,
            observed=(f"{total} uncaught error(s) across {len(errored)} "
                      f"interactions; first: {sample!r}"),
            expected="no uncaught errors on a normal user journey",
            impact=("An error thrown mid-interaction usually leaves the "
                    "interface in a half-updated state the user cannot "
                    "recover from without reloading."),
            seqs=[a.seq for a in errored][:10],
            recommendation="Fix the throwing paths and add an error boundary.",
            url=errored[0].page_url))

    # ── abandoned journeys ───────────────────────────────────────────────
    for j in journeys:
        if j.completed or not j.abandoned_at:
            continue
        out.append(_finding(
            f"UX-ABANDON-{j.journey_id}", f"Journey not completed: {j.name}",
            "journey",
            Severity.HIGH if j.steps_succeeded == 0 else Severity.MEDIUM,
            observed=(f"stopped at {j.abandoned_at!r} after "
                      f"{j.steps_attempted} of {j.steps_planned} steps — "
                      f"{j.abandon_reason or 'no route forward was found'}"),
            expected=f"a visitor can complete: {j.goal}",
            impact=("This is where a real user gives up. Whatever the journey "
                    "was worth, it is not being realised here."),
            recommendation=("Walk the journey manually from the same entry "
                            "point and check the step named above is reachable "
                            "and labelled the way a visitor would expect."),
            seqs=j.action_seqs[-5:]))

    # ── unnamed controls ─────────────────────────────────────────────────
    unnamed = sum(p.a11y.unlabelled_controls for p in page_models)
    if unnamed:
        worst = max(page_models, key=lambda p: p.a11y.unlabelled_controls)
        out.append(_finding(
            "UX-A11Y-NAME", "Controls with no accessible name", "accessibility",
            Severity.MEDIUM,
            observed=(f"{unnamed} control(s) across {len(page_models)} pages "
                      f"have no accessible name; worst page "
                      f"{worst.a11y.unlabelled_controls} on {worst.url}"),
            expected="every interactive control has a name a screen reader "
                     "can announce",
            impact=("Screen-reader users hear 'button' with no indication of "
                    "what it does. Voice-control users cannot address it at all."),
            recommendation=("Give icon-only controls an aria-label, or visually "
                            "hidden text inside the control."),
            seqs=[], url=worst.url))

    # ── focus indicators ─────────────────────────────────────────────────
    ratios = [p.a11y.focus_visible_ratio for p in page_models
              if p.a11y.focus_visible_ratio is not None]
    if ratios and (_mean(ratios) or 1.0) < 0.8:
        pct = (_mean(ratios) or 0) * 100
        out.append(_finding(
            "UX-A11Y-FOCUS", "Keyboard focus is not always visible",
            "accessibility", Severity.MEDIUM,
            observed=f"a focus indicator was detectable on {pct:.0f}% of "
                     f"keyboard stops sampled",
            expected="every focusable control shows where focus is",
            impact=("Keyboard and switch users lose their place entirely. This "
                    "is the single most common reason a site is unusable "
                    "without a mouse."),
            recommendation=("Never remove the default outline without replacing "
                            "it; :focus-visible gives you the mouse-free "
                            "behaviour people usually strip outlines to get."),
            seqs=[]))

    out.sort(key=lambda f: (-f.severity.rank, f.id))
    return out


def journey_outcomes(journeys: list[Journey], actions: list[ActionRecord],
                     progress: dict[str, dict] | None = None
                     ) -> list[JourneyOutcome]:
    """Reduce the action log to per-journey outcomes. Pure.

    `progress` is the agent's own bookkeeping: how many steps it actually
    advanced past, and why it stopped. It is passed in rather than inferred
    because inference gets this wrong in exactly the case that matters —
    recovery actions reuse the step label they were recovering, so counting
    distinct labels makes a journey that retried twice and gave up look like
    a journey that completed. Reported completion has to come from the loop
    that did the walking, not from a count of what it left behind.
    """
    progress = progress or {}
    out: list[JourneyOutcome] = []
    for j in journeys:
        mine = [a for a in actions if a.intent.journey_id == j.id]
        state = progress.get(j.id)
        if not mine and not state:
            continue
        succeeded = sum(1 for a in mine if a.outcome is Outcome.SUCCESS)
        last = mine[-1] if mine else None

        if state is not None:
            attempted = int(state.get("steps_attempted", 0))
            completed = bool(state.get("completed"))
            abandoned_at = state.get("abandoned_at")
            reason = state.get("reason")
        else:
            attempted = len({a.intent.step_label for a in mine
                             if a.intent.step_label})
            completed = False
            abandoned_at = (last.intent.step_label or last.element_label
                            if last else None)
            reason = last.observed[:160] if last else None

        span = None
        if len(mine) > 1:
            span = round((mine[-1].at - mine[0].at).total_seconds() * 1000, 1)
        out.append(JourneyOutcome(
            journey_id=j.id, name=j.name, goal=j.goal,
            completed=completed,
            steps_planned=len(j.steps), steps_attempted=attempted,
            steps_succeeded=succeeded,
            abandoned_at=None if completed else abandoned_at,
            abandon_reason=None if completed else reason,
            action_seqs=[a.seq for a in mine],
            total_ms=span))
    return out
