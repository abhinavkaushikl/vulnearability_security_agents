"""Final graph state -> the JSON shape web/lib/types.ts already declares.

This module is a projection and nothing more. It performs no evaluation, no
counting and no rounding that the engine has not already done: every number
here is read from a model the graph produced. If a value is absent it is
serialised as null, never as zero — the same rule app/tools/statistics.py
follows, and for the same reason.
"""
from __future__ import annotations

from typing import Any

from app.models.assessment import AssessmentStatus
from app.models.performance import ProfileStatus
from app.models.results import ContractResult, NativeResult, ResultTally
from app.safety import antibot

#: Findings are ordered for a reader, worst first: evidenced failures by
#: severity, then partial evidence, then passes, then the controls a browser
#: was never able to reach. The pack's own emphasis, made into a sort key.
_RESULT_RANK: dict[NativeResult, int] = {
    NativeResult.FAIL: 0,
    NativeResult.WARN: 1,
    NativeResult.INFORMATIONAL: 2,
    NativeResult.PASS: 3,
    NativeResult.NA: 4,
    NativeResult.NOT_TESTABLE: 5,
}

_PROFILE_STATUS: dict[ProfileStatus, str] = {
    ProfileStatus.COMPLETED: "OK",
    ProfileStatus.PARTIAL: "PARTIAL",
    ProfileStatus.UNAVAILABLE: "UNAVAILABLE",
    ProfileStatus.FAILED: "UNAVAILABLE",
}


def _finding(r) -> dict[str, Any]:
    return {
        "control_id": r.rule_id,
        "family": r.category,
        "title": r.rule_name,
        "severity": r.severity.value,
        "native_result": r.native_result.value,
        "result": r.result.value,
        "observed_value": r.observed_value,
        "unknown_reason": r.unknown_reason,
        "evidence": r.evidence,
        "source_file": r.source_file,
        "source_line": r.source_line,
    }


def _sort_key(r) -> tuple[int, int, str]:
    return (_RESULT_RANK.get(r.native_result, 9), -r.severity.rank, r.rule_id)


def _families(state: dict) -> list[dict[str, Any]]:
    """Per-family coverage, labelled from the pack's own family titles.

    The label comes from `RuleFamily.title` rather than a hardcoded map, so a
    family added to Rules/ appears here with its real name and no code change.
    """
    titles = {f.family: f.title for f in state.get("families", [])}
    out = []
    for code, c in (state.get("family_coverage") or {}).items():
        out.append({
            "family": code,
            "label": titles.get(code, code),
            "decided": c.get("decided", 0),
            "total": c.get("total", 0),
            "failed": c.get("failed", 0),
        })
    out.sort(key=lambda f: (-f["failed"], -f["decided"], f["family"]))
    return out


def _stat(stats: list, profile: str, metric: str, field: str) -> float | None:
    for s in stats:
        if s.network_profile == profile and s.metric == metric:
            return getattr(s, field)
    return None


def _performance(state: dict) -> list[dict[str, Any]]:
    stats = state.get("performance_stats") or []
    outcomes = state.get("profile_outcomes") or []
    rows = []
    for o in outcomes:
        n = _stat(stats, o.name, "ttfb", "n")
        rows.append({
            "profile": o.name,
            "ttfb_p50": _stat(stats, o.name, "ttfb", "median"),
            "lcp_p50": _stat(stats, o.name, "lcp", "median"),
            "load_p95": _stat(stats, o.name, "page_load_time", "p95"),
            "n": int(n) if n is not None else o.iterations_completed,
            "status": _PROFILE_STATUS.get(o.status, "UNAVAILABLE"),
        })
    return rows


def _route(state: dict) -> list[dict[str, Any]]:
    plan = state.get("plan")
    if plan is None:
        return []
    return [{"kind": a.kind, "target": a.target or state.get("target_url", ""),
             "reason": a.reason, "required_by": list(a.required_by)}
            for a in plan.actions]


def to_report(state: dict, *, duration_seconds: float) -> dict[str, Any]:
    """Project the terminal graph state onto web/lib/types.ts :: Report."""
    results = sorted(state.get("security_results", []), key=_sort_key)
    tally: ResultTally = state.get("tally") or ResultTally.of(results)
    status: AssessmentStatus = state.get("status", AssessmentStatus.FAILED)
    evidence = state.get("evidence")
    signal = state.get("anti_bot")
    provider = state.get("provider")

    return {
        "assessment_id": state.get("assessment_id", ""),
        "target": state.get("target_url", ""),
        "status": status.value,
        "coverage_pct": tally.coverage_pct,
        "tally": {
            "total": tally.total,
            "yes": tally.yes,
            "no": tally.no,
            "not_applicable": tally.not_applicable,
            "unknown": tally.unknown,
            "native_pass": tally.native_pass,
            "native_fail": tally.native_fail,
            "native_warn": tally.native_warn,
            "native_na": tally.native_na,
            "native_informational": tally.native_informational,
            "native_not_testable": tally.native_not_testable,
        },
        "families": _families(state),
        "findings": [_finding(r) for r in results],
        "route": _route(state),
        "performance": _performance(state),
        "collectors_run": ([c.value for c in evidence.collectors_run]
                           if evidence is not None else []),
        "duration_seconds": round(duration_seconds, 1),
        "llm_model": (getattr(provider, "model", None)
                      if state.get("llm_available") else None),
        "blocked_reason": (antibot.blocked_reason(signal)
                           if signal is not None and signal.detected else None),
        # Beyond the UI contract, but produced by the run and cheap to carry:
        "summary_text": state.get("summary_text", ""),
        "report_path": state.get("report_path", ""),
        "errors": [{"component": e.component, "message": e.message,
                    "fatal": e.fatal} for e in state.get("errors", [])],
    }
