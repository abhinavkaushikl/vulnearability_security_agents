"""LangGraph nodes.

One node per phase. Every node is defensive: a failure inside a node records a
ComponentError and returns a usable state rather than aborting the graph. One
failed rule, one failed collector or one failed profile never terminates the
assessment.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from app.agents.aggregator import (family_coverage, validate_results,
                                   write_summary)
from app.agents.browser_agent import EvidenceCollector
from app.agents.performance_agent import PerformanceAgent
from app.agents.planner import Planner
from app.graph.state import AssessmentState
from app.models.assessment import (Assessment, AssessmentStatus, ComponentError)
from app.models.evidence import EvidenceBundle
from app.models.results import ResultTally
from app.safety import antibot
from app.tools.evaluation import RuleEvaluator
from app.tools.rules import load_rules
from app.tools.statistics import summarise_measurements

log = logging.getLogger(__name__)


def _err(state: AssessmentState, component: str, exc: Exception,
         fatal: bool = False) -> ComponentError:
    log.error("%s failed: %s: %s", component, type(exc).__name__, exc)
    return ComponentError(component=component,
                          message=f"{type(exc).__name__}: {exc}", fatal=fatal)


# --------------------------------------------------------------------------
async def load_rules_node(state: AssessmentState) -> dict:
    """LOAD_RULES. Pure Python: parse the Markdown pack. No LLM."""
    s = state["settings"]
    try:
        families, rules = load_rules(s.project_root, s.rules.directory)
    except Exception as exc:                                    # noqa: BLE001
        return {"status": AssessmentStatus.FAILED,
                "errors": [_err(state, "load_rules", exc, fatal=True)]}
    log.info("LOAD_RULES: %d controls from %d families", len(rules), len(families))
    return {"families": families, "rules": rules,
            "status": AssessmentStatus.PLANNING}


# --------------------------------------------------------------------------
async def plan_node(state: AssessmentState) -> dict:
    """PLAN_ASSESSMENT. Interpret rules (cached), then union collector sets."""
    s = state["settings"]
    rules = state.get("rules", [])
    planner = Planner(state["provider"], s,
                      llm_available=state.get("llm_available", False))
    errors: list[ComponentError] = []
    try:
        await planner.interpret_all(rules)
    except Exception as exc:                                    # noqa: BLE001
        errors.append(_err(state, "rule_interpretation", exc))
    try:
        plan = planner.build_plan(state["target_url"], rules)
    except Exception as exc:                                    # noqa: BLE001
        return {"status": AssessmentStatus.FAILED,
                "errors": errors + [_err(state, "build_plan", exc, fatal=True)]}

    log.info("PLAN: %d evaluable, %d not testable, %d collectors, ~%d requests",
             len(plan.evaluable_rules), len(plan.not_testable_rules),
             len(plan.required_collectors), plan.estimated_requests)
    for note in plan.notes:
        log.info("PLAN: %s", note)
    return {"plan": plan, "rules": rules, "errors": errors,
            "status": AssessmentStatus.DISCOVERING}


# --------------------------------------------------------------------------
async def collect_evidence_node(state: AssessmentState) -> dict:
    """BROWSER_DISCOVERY + COLLECT_EVIDENCE. The only node that browses."""
    s = state["settings"]
    plan = state["plan"]
    artifact_dir = Path(s.artifact_dir(state["assessment_id"]))
    collector = EvidenceCollector(state["session"], s, state["budget"],
                                  artifact_dir)
    try:
        bundle, signal = await collector.collect(
            assessment_id=state["assessment_id"],
            target_url=state["target_url"],
            required=set(plan.required_collectors))
    except Exception as exc:                                    # noqa: BLE001
        empty = EvidenceBundle(assessment_id=state["assessment_id"],
                               target_url=state["target_url"])
        return {"evidence": empty, "status": AssessmentStatus.FAILED,
                "errors": [_err(state, "collect_evidence", exc, fatal=True)]}

    if signal.detected:
        log.warning("BLOCKED: %s", antibot.blocked_reason(signal))
        return {"evidence": bundle, "anti_bot": signal,
                "status": AssessmentStatus.BLOCKED}

    log.info("EVIDENCE: %d collectors ran, %d errors",
             len(bundle.collectors_run), len(bundle.collector_errors))
    return {"evidence": bundle, "anti_bot": signal,
            "status": AssessmentStatus.EVALUATING}


# --------------------------------------------------------------------------
async def evaluate_node(state: AssessmentState) -> dict:
    """PARALLEL_RULE_EVALUATION. Fan out over the frozen bundle. No traffic."""
    s = state["settings"]
    rules = state.get("rules", [])
    bundle = state["evidence"]
    signal = state.get("anti_bot")

    evaluator = RuleEvaluator(
        state["provider"], llm_available=state.get("llm_available", False),
        max_concurrency=s.assessment.max_concurrent_evaluations)

    # If we were blocked, every control becomes NOT_TESTABLE with the reason.
    if signal is not None and signal.detected:
        from app.models.results import SecurityResult
        reason = antibot.blocked_reason(signal)
        return {"security_results": [
            SecurityResult.not_testable(assessment_id=state["assessment_id"],
                                        rule=r, reason=reason,
                                        source="assessment halted")
            for r in rules]}

    try:
        results = await evaluator.evaluate_all(rules, bundle,
                                               state["assessment_id"])
    except Exception as exc:                                    # noqa: BLE001
        return {"security_results": [],
                "errors": [_err(state, "evaluate_rules", exc)]}

    log.info("EVALUATE: %d results, %d LLM calls, %d downgraded for "
             "unverifiable citations",
             len(results), evaluator.llm_calls, evaluator.downgrades)
    return {"security_results": results}


# --------------------------------------------------------------------------
async def performance_node(state: AssessmentState) -> dict:
    """PERFORMANCE + STATISTICS. Profiles run in series; stats are pure Python."""
    s = state["settings"]
    if not s.performance.enabled:
        return {"performance_raw": [], "performance_stats": [],
                "profile_outcomes": []}
    signal = state.get("anti_bot")
    if signal is not None and signal.detected:
        log.warning("performance skipped: assessment is BLOCKED")
        return {"performance_raw": [], "performance_stats": [],
                "profile_outcomes": []}

    agent = PerformanceAgent(state["session"], s, state["budget"])
    try:
        raw, outcomes = await agent.run(assessment_id=state["assessment_id"],
                                        target_url=state["target_url"])
    except Exception as exc:                                    # noqa: BLE001
        return {"performance_raw": [], "performance_stats": [],
                "profile_outcomes": [],
                "errors": [_err(state, "performance", exc)]}

    try:
        stats = summarise_measurements(raw, state["assessment_id"])
    except Exception as exc:                                    # noqa: BLE001
        stats = []
        return {"performance_raw": raw, "performance_stats": [],
                "profile_outcomes": outcomes,
                "errors": [_err(state, "statistics", exc)]}

    log.info("PERFORMANCE: %d measurements across %d profiles, %d statistics rows",
             len(raw), len(outcomes), len(stats))
    return {"performance_raw": raw, "performance_stats": stats,
            "profile_outcomes": outcomes}


# --------------------------------------------------------------------------
async def aggregate_node(state: AssessmentState) -> dict:
    """RESULT_VALIDATION + AGGREGATION. Counts in Python; prose from the LLM."""
    results = validate_results(state.get("security_results", []))
    rules = state.get("rules", [])
    tally = ResultTally.of(results)
    coverage = family_coverage(results, rules)

    try:
        summary = await write_summary(
            state["provider"], llm_available=state.get("llm_available", False),
            target=state["target_url"], tally=tally, results=results,
            coverage=coverage)
    except Exception as exc:                                    # noqa: BLE001
        from app.agents.aggregator import deterministic_summary
        summary = deterministic_summary(state["target_url"], tally, results)
        log.warning("summary fell back to deterministic text: %s", exc)

    log.info("AGGREGATE: %d/%d decided (%.1f%% coverage) — "
             "%d PASS, %d FAIL, %d WARN, %d INFO, %d NOT_TESTABLE",
             tally.decided, tally.total, tally.coverage_pct,
             tally.native_pass, tally.native_fail, tally.native_warn,
             tally.native_informational, tally.native_not_testable)
    return {"security_results": results, "tally": tally,
            "family_coverage": coverage, "summary_text": summary,
            "status": AssessmentStatus.AGGREGATING}


# --------------------------------------------------------------------------
async def persist_node(state: AssessmentState) -> dict:
    """EXCEL_PERSISTENCE via the repository seam. No node imports openpyxl."""
    s = state["settings"]
    repo = state["repository"]
    signal = state.get("anti_bot")
    tally = state.get("tally", ResultTally())
    errors: list[ComponentError] = []

    if signal is not None and signal.detected:
        status = AssessmentStatus.BLOCKED
    elif any(e.fatal for e in state.get("errors", [])):
        status = AssessmentStatus.FAILED
    elif state.get("errors") or tally.native_not_testable == tally.total:
        status = AssessmentStatus.PARTIAL
    else:
        status = AssessmentStatus.COMPLETED

    assessment = Assessment(
        assessment_id=state["assessment_id"],
        target_url=state["target_url"],
        status=status,
        tally=tally,
        pack_version=(state["rules"][0].pack_version
                      if state.get("rules") else ""),
        coverage_pct=tally.coverage_pct,
        browser_version=getattr(state.get("session"), "browser_version", ""),
        llm_model=(getattr(state.get("provider"), "model", "")
                   if state.get("llm_available") else "none (deterministic only)"),
        blocked_reason=(antibot.blocked_reason(signal)
                        if signal is not None and signal.detected else None),
        duration_seconds=time.monotonic() - state.get("started_at", time.monotonic()),
    )

    try:
        if hasattr(repo, "summary_text"):
            repo.summary_text = state.get("summary_text", "")
        await repo.save_assessment(assessment)
        await repo.save_security_results(state.get("security_results", []))
        await repo.save_performance_results(state.get("performance_raw", []))
        await repo.save_statistics(state.get("performance_stats", []))
        path = await repo.commit()
    except Exception as exc:                                    # noqa: BLE001
        errors.append(_err(state, "persistence", exc))
        path = ""

    log.info("PERSIST: status=%s report=%s", status.value, path or "(failed)")
    return {"status": status, "report_path": path, "errors": errors}
