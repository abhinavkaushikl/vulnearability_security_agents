"""Projection of a BehaviourReport onto the JSON web/lib/behaviourTypes.ts reads.

Same discipline as app/api/serializers.py: a metric that was not observed
serialises as `null`, never `0`. The interface is written to render a null as
"not measured", so the distinction survives all the way to the screen.
"""
from __future__ import annotations

from app.behaviour import report as report_mod
from app.behaviour.models import BehaviourReport, Outcome


def _timing(t) -> dict:
    return {
        "input_latency_ms": t.input_latency_ms,
        "ui_response_ms": t.ui_response_ms,
        "network_first_byte_ms": t.network_first_byte_ms,
        "network_complete_ms": t.network_complete_ms,
        "state_complete_ms": t.state_complete_ms,
        "perceived_ms": t.perceived_ms,
        "mutation_count": t.mutation_count,
        "request_count": t.request_count,
        "layout_shift": t.layout_shift,
        "long_task_ms": t.long_task_ms,
        "scroll_fps": t.scroll_fps,
        "dropped_frames": t.dropped_frames,
    }


def to_json(report: BehaviourReport) -> dict:
    """Everything the interface needs, and nothing it does not."""
    return {
        "session_id": report.session_id,
        "target": report.target,
        "state": report.state.value,
        "started_at": report.started_at.isoformat(),
        "duration_seconds": report.duration_seconds,

        "understanding": {
            "kind": report.understanding.kind.value,
            "confidence": report.understanding.confidence,
            "primary_goal": report.understanding.primary_goal,
            "secondary_goals": report.understanding.secondary_goals,
            "audience": report.understanding.audience,
            "key_affordances": report.understanding.key_affordances,
            "rationale": report.understanding.rationale,
            "derived_by": report.understanding.derived_by,
        },

        "score": {
            "overall": report.score.overall,
            "band": report.score.band.value,
            "method": report.score.method,
            "observations": report.score.observations,
            "components": [
                {"name": c.name, "score": c.score, "n": c.n, "basis": c.basis}
                for c in report.score.components],
        },

        "journeys": [
            {"id": j.id, "name": j.name, "goal": j.goal,
             "derived_by": j.derived_by,
             "steps": [{"label": s.label, "action": s.action,
                        "expectation": s.expectation, "optional": s.optional}
                       for s in j.steps]}
            for j in report.journeys],

        "journey_outcomes": [
            {"journey_id": o.journey_id, "name": o.name, "goal": o.goal,
             "completed": o.completed, "steps_planned": o.steps_planned,
             "steps_attempted": o.steps_attempted,
             "steps_succeeded": o.steps_succeeded,
             "abandoned_at": o.abandoned_at,
             "abandon_reason": o.abandon_reason,
             "total_ms": o.total_ms}
            for o in report.journey_outcomes],

        "timeline": report_mod.journey_timeline(report),
        "interactions": report_mod.interaction_analysis(report),
        "categories": _categories(report),

        "actions": [
            {"seq": a.seq,
             "kind": a.intent.kind.value,
             "category": a.category,
             "element": a.element_label,
             "element_kind": a.element_kind.value if a.element_kind else None,
             "reason": a.intent.reason,
             "expectation": a.expectation,
             "observed": a.observed,
             "outcome": a.outcome.value,
             "url": a.page_url,
             "new_url": a.new_url,
             "note": a.note,
             "console_errors": a.console_errors,
             "timing": _timing(a.timing)}
            for a in report.actions],

        "thoughts": [
            {"seq": t.seq, "state": t.state.value, "observation": t.observation,
             "action": t.action, "result": t.result,
             "latency_ms": t.latency_ms, "ok": t.ok}
            for t in report.thoughts],

        "pages": [
            {"url": p.url, "title": p.title, "visits": p.visits,
             "interactions": p.interactions, "errors": p.errors,
             "vitals": {
                 "ttfb_ms": p.vitals.ttfb_ms,
                 "fcp_ms": p.vitals.fcp_ms,
                 "lcp_ms": p.vitals.lcp_ms,
                 "cls": p.vitals.cls,
                 "load_ms": p.vitals.load_ms,
                 "dom_content_loaded_ms": p.vitals.dom_content_loaded_ms,
                 "transferred_bytes": p.vitals.transferred_bytes,
                 "request_count": p.vitals.request_count,
                 # Always null, always present. INP needs real users; a lab
                 # agent cannot produce one, and omitting the key would let a
                 # reader assume it simply was not collected this time.
                 "inp_ms": None,
             }}
            for p in report.pages],

        "findings": [
            {"id": f.id, "title": f.title, "category": f.category,
             "severity": f.severity.value, "observed": f.observed,
             "expected": f.expected, "impact": f.impact,
             "recommendation": f.recommendation,
             "evidence_seq": f.evidence_seq, "page_url": f.page_url}
            for f in report.findings],

        "insights": report.insights,
        "summary": report.summary,
        "mission": report_mod.mission_stats(report),

        "refusals": [
            {"seq": a.seq, "element": a.element_label, "reason": a.observed}
            for a in report.actions if a.outcome is Outcome.REFUSED],

        "requests_made": report.requests_made,
        "blocked_reason": report.blocked_reason,
        "errors": report.errors,
        "llm_model": report.llm_model,
        "browser_version": report.browser_version,
    }


def _categories(report: BehaviourReport) -> list[dict]:
    from app.behaviour.scoring import summarise_category
    return summarise_category(report.actions)
