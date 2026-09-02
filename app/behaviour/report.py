"""UX Report Generator — §18, §20, §24.

Assembles the session into the report a person reads. Everything here is
derived from `ActionRecord`s and `PageModel`s; the one optional model call
(the executive summary) can rephrase but cannot change a score, a severity or
a measurement — `agent.py` composes the summary from an already-finished
report object.

§28 is the brief for this module. The report must not say "your website loads
in 1.8 seconds". It must say what the agent tried, what it expected, what
happened, and where the experience broke down.
"""
from __future__ import annotations

from app.behaviour.models import (ActionRecord, BehaviourReport, Outcome,
                                  Severity, UXFinding, UXScore)
from app.tools.statistics import calculate_percentile
from app.behaviour.scoring import (FLOW_MS, INSTANT_MS, INTERACTION_GOOD_MS,
                                   latencies_by_category)


def _feel(score: UXScore, actions: list[ActionRecord]) -> str:
    """§20's first question — "how does the website feel?" — answered from
    the two things that actually decide it: speed and whether things worked."""
    speed = next((c for c in score.components if c.name == "Interaction Speed"), None)
    reliab = next((c for c in score.components
                   if c.name == "Interaction Reliability"), None)
    fast = speed and speed.score is not None and speed.score >= 75
    slow = speed and speed.score is not None and speed.score < 50
    solid = reliab and reliab.score is not None and reliab.score >= 85
    flaky = reliab and reliab.score is not None and reliab.score < 60

    if flaky:
        return ("Friction-heavy. Controls did not reliably do what pressing "
                "them implied, which is felt long before slowness is.")
    if slow:
        return ("Slow. Actions were acknowledged late enough that the "
                "response stops feeling connected to the click.")
    if fast and solid:
        return "Fast and responsive. Actions were acknowledged promptly and did what they said."
    if fast:
        return ("Quick, but uneven — the fast paths are fast and the rest are "
                "noticeably not.")
    return ("Serviceable. Nothing was broken enough to stop a visitor, and "
            "nothing was quick enough to feel effortless.")


def behavioural_insights(report: BehaviourReport) -> dict[str, str]:
    """§20. Each answer names the evidence that produced it."""
    actions = report.actions
    findings = report.findings
    out: dict[str, str] = {}

    out["How does it feel?"] = _feel(report.score, actions)

    # Where does the user struggle?
    struggles = [f for f in findings
                 if f.severity.rank >= Severity.HIGH.rank]
    out["Where does a user struggle?"] = (
        "; ".join(f.title.lower() for f in struggles[:3]) + "."
        if struggles else
        "Nothing rose to a high-severity friction point in this session.")

    # Which interactions are slow?
    by_cat = latencies_by_category(actions)
    slow = sorted(
        ((c, calculate_percentile(v, 50) or 0) for c, v in by_cat.items()
         if c not in ("dwell", "control")),
        key=lambda kv: -kv[1])
    out["Which interactions are slow?"] = (
        ", ".join(f"{c} ({m:.0f} ms median)" for c, m in slow[:3]) + "."
        if slow else "No interaction produced a measurable response time.")

    # Which components feel unresponsive?
    dead = [a for a in actions if a.outcome is Outcome.NO_RESPONSE]
    silent = [a for a in actions if a.timing.ui_response_ms is None
              and a.timing.network_complete_ms is not None]
    if dead or silent:
        bits = []
        if dead:
            bits.append(f"{len(dead)} control(s) did nothing at all")
        if silent:
            bits.append(f"{len(silent)} fetched data with no visible feedback")
        out["Which components feel unresponsive?"] = "; ".join(bits) + "."
    else:
        out["Which components feel unresponsive?"] = (
            "Every control the agent pressed gave visible feedback.")

    # Where is a journey abandoned?
    abandoned = [j for j in report.journey_outcomes if not j.completed]
    out["Where does a journey break down?"] = (
        "; ".join(f"{j.name} — stopped at {j.abandoned_at or 'an unknown step'}"
                  for j in abandoned[:3]) + "."
        if abandoned else
        f"All {len(report.journey_outcomes)} journeys reached their goal.")

    # Are CTAs discoverable?
    first_click = next((a for a in actions if a.category == "button"), None)
    scrolls_before = (sum(1 for a in actions
                          if a.category == "scroll" and a.seq < first_click.seq)
                      if first_click else 0)
    out["Are the primary actions discoverable?"] = (
        f"The agent found its first actionable control after {scrolls_before} "
        f"scroll(s)." if first_click else
        "The agent found no primary action to press on the pages it saw.")

    # Navigation
    nav = by_cat.get("navigation", [])
    out["Does navigation feel intuitive?"] = (
        f"{len(report.pages)} pages were reached; route transitions ran at a "
        f"{calculate_percentile(nav, 50) or 0:.0f} ms median."
        if nav else
        "The agent did not complete a page-to-page transition.")

    # Scrolling
    scroll = next((c for c in report.score.components
                   if c.name == "Scroll Experience"), None)
    out["Does scrolling feel natural?"] = (
        scroll.basis + "." if scroll and scroll.score is not None else
        "Scrolling could not be measured on the pages visited.")

    # Immediate feedback
    perceived = [a.timing.perceived_ms for a in actions
                 if a.timing.perceived_ms is not None]
    if perceived:
        instant = sum(1 for v in perceived if v <= INSTANT_MS)
        out["Does the site give immediate feedback?"] = (
            f"{instant} of {len(perceived)} interactions responded within "
            f"{INSTANT_MS:.0f} ms — the threshold at which a response still "
            "feels like part of the click.")
    else:
        out["Does the site give immediate feedback?"] = (
            "No interaction produced an observable response to time.")

    return out


def deterministic_summary(report: BehaviourReport) -> str:
    """The summary that is always computed. The model's version replaces the
    prose, never the facts — and if the model is absent this is the report's
    summary, not a placeholder."""
    parts: list[str] = []
    score = report.score

    if report.blocked_reason:
        return (f"The session stopped early: {report.blocked_reason} "
                f"Findings cover only the {report.interactions_total} "
                "interactions completed before that point.")

    kind = report.understanding.kind.value
    parts.append(
        f"The agent treated {report.target} as a {kind} site whose visitor "
        f"wants to {report.understanding.primary_goal or 'find something'}, "
        f"and ran {report.journeys_run} journey(s) across "
        f"{report.pages_explored} page(s) with {report.interactions_total} "
        f"interactions.")

    if score.overall is not None:
        caveat = (" This session did not run to plan, so the number describes "
                  "less of the site than a full run would."
                  if score.degraded else "")
        parts.append(
            f"The experience scores {score.overall}/100 ({score.band.value.lower()}), "
            f"weighted over {len([c for c in score.components if c.score is not None])} "
            f"measured components.{caveat}")
    else:
        parts.append("Too little was observable to put a number on the "
                     "experience, so none is claimed.")

    if report.avg_response_ms is not None:
        parts.append(
            f"Interactions were acknowledged in {report.avg_response_ms:.0f} ms "
            f"on median" +
            (f", against the {INTERACTION_GOOD_MS:.0f} ms at which a response "
             "still reads as instant." if report.avg_response_ms > INTERACTION_GOOD_MS
             else " — comfortably inside the range that reads as instant."))

    crit = [f for f in report.findings if f.severity is Severity.CRITICAL]
    high = [f for f in report.findings if f.severity is Severity.HIGH]
    if crit or high:
        lead = (crit or high)[0]
        parts.append(
            f"{len(crit)} critical and {len(high)} high-severity issues were "
            f"found; the one that costs the most is {lead.title.lower()} "
            f"({lead.observed}).")
    elif report.findings:
        parts.append(f"{len(report.findings)} lower-severity issues were "
                     "found, none of them blocking.")
    else:
        parts.append("No issue crossed a reporting threshold in this session.")

    abandoned = [j for j in report.journey_outcomes if not j.completed]
    if abandoned:
        parts.append(
            f"{len(abandoned)} journey(s) did not reach their goal — "
            f"{abandoned[0].name} stopped at "
            f"{abandoned[0].abandoned_at or 'an unidentified step'}.")

    return " ".join(parts)


def summary_facts(report: BehaviourReport) -> str:
    """The fact sheet handed to the model for the executive summary.

    Only measurements and already-generated findings. The model is not shown
    the deterministic summary's prose, so it cannot simply echo it, and it is
    not shown raw timings it might try to re-average.
    """
    lines = [
        f"Target: {report.target}",
        f"Site kind: {report.understanding.kind.value} "
        f"(confidence {report.understanding.confidence})",
        f"Visitor goal: {report.understanding.primary_goal}",
        f"Pages explored: {report.pages_explored}",
        f"Interactions: {report.interactions_total}",
        f"Journeys run: {report.journeys_run}, completed: "
        f"{sum(1 for j in report.journey_outcomes if j.completed)}",
    ]
    if report.score.overall is not None:
        lines.append(f"UX score: {report.score.overall}/100 "
                     f"({report.score.band.value})")
        for c in report.score.components:
            if c.score is not None:
                lines.append(f"  - {c.name}: {c.score} (n={c.n}) — {c.basis}")
    if report.avg_response_ms is not None:
        lines.append(f"Median perceived response: {report.avg_response_ms:.0f} ms")
    if report.blocked_reason:
        lines.append(f"BLOCKED: {report.blocked_reason}")

    lines.append("Findings:")
    for f in report.findings[:10]:
        lines.append(f"  - [{f.severity.value}] {f.title}: {f.observed}")
    if not report.findings:
        lines.append("  (none)")

    lines.append("Journeys:")
    for j in report.journey_outcomes:
        lines.append(
            f"  - {j.name}: "
            + ("completed" if j.completed
               else f"abandoned at {j.abandoned_at or 'unknown'} "
                    f"({j.abandon_reason or 'no reason recorded'})")
            + f" — {j.steps_succeeded}/{j.steps_planned} steps succeeded")
    return "\n".join(lines)


def journey_timeline(report: BehaviourReport) -> list[dict]:
    """§18's journey diagram, as data.

    One row per action that moved the journey along, carrying the latency the
    interface actually showed. The frontend draws the arrows; the numbers on
    them come from here.
    """
    rows: list[dict] = []
    for a in report.actions:
        if a.outcome is Outcome.REFUSED:
            continue
        if a.category in ("dwell", "control"):
            continue
        rows.append({
            "seq": a.seq,
            "journey_id": a.intent.journey_id,
            "label": (a.intent.step_label or a.element_label
                      or a.intent.kind.value),
            "action": a.intent.kind.value,
            "category": a.category,
            "ms": a.timing.perceived_ms,
            # A scroll that moved the page has no "perceived response" to
            # quote, and a dead button has no timing either. Without the
            # outcome a renderer cannot tell those two apart, and would print
            # the same words for a working scroll and a broken control.
            "outcome": a.outcome.value,
            "ok": a.outcome is Outcome.SUCCESS,
            "slow": (a.timing.perceived_ms is not None
                     and a.timing.perceived_ms > (
                         FLOW_MS if a.category == "navigation"
                         else INTERACTION_GOOD_MS * 2)),
            "url": a.new_url or a.page_url,
        })
    return rows


def interaction_analysis(report: BehaviourReport) -> list[dict]:
    """§18's per-interaction table: expectation vs observation vs verdict."""
    rows: list[dict] = []
    for a in report.actions:
        if a.category in ("dwell", "control"):
            continue
        ms = a.timing.perceived_ms
        good = FLOW_MS if a.category == "navigation" else INTERACTION_GOOD_MS
        if a.outcome is Outcome.REFUSED:
            assessment, severity = "Not attempted — declined by the safety layer", "INFO"
        elif a.outcome is Outcome.NO_RESPONSE:
            assessment, severity = "No response at all", "CRITICAL"
        elif ms is None:
            assessment, severity = "No timing was observable", "INFO"
        elif ms <= good:
            assessment, severity = "Within expectation", "INFO"
        elif ms <= good * 2.5:
            assessment, severity = "Needs improvement", "MEDIUM"
        else:
            assessment, severity = "Well outside expectation", "HIGH"
        rows.append({
            "seq": a.seq,
            "interaction": a.element_label or a.intent.kind.value,
            "category": a.category,
            "expectation": a.expectation or "a visible response",
            "observed": a.observed,
            "ms": ms,
            "assessment": assessment,
            "severity": severity,
        })
    return rows


def mission_stats(report: BehaviourReport) -> dict:
    """§24. The closing card."""
    return {
        "pages_explored": report.pages_explored,
        "interactions": report.interactions_total,
        "journeys": report.journeys_run,
        "issues_detected": report.issues_detected,
        "critical_issues": report.critical_issues,
        "avg_response_ms": report.avg_response_ms,
        "requests_made": report.requests_made,
        "score": report.score.overall,
        "band": report.score.band.value,
    }
