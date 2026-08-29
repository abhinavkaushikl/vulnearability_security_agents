"""Result validator + aggregator.

Counts are computed in Python. The LLM writes prose and cannot alter a single
verdict or number — it is handed the finished tally and asked to describe it.
"""
from __future__ import annotations

import logging

from app.llm.base import LLMUnavailable
from app.llm.prompts import AGGREGATOR_SYSTEM
from app.models.results import (NativeResult, ResultTally, SecurityResult,
                                project)
from app.models.rules import SecurityRule

log = logging.getLogger(__name__)


def validate_results(results: list[SecurityResult]) -> list[SecurityResult]:
    """Final consistency gate before persistence.

    Enforces two invariants that must hold no matter what any model returned:
      1. `result` is always the correct projection of `native_result`.
      2. A PASS or FAIL always carries an observed_value. If one does not,
         it is downgraded — a verdict with no cited evidence is not a verdict.
    """
    out: list[SecurityResult] = []
    for r in results:
        expected = project(r.native_result)
        if r.result != expected:
            log.warning("%s: result/native mismatch, correcting %s -> %s",
                        r.rule_id, r.result.value, expected.value)
            r.result = expected

        if r.native_result in (NativeResult.PASS, NativeResult.FAIL) \
                and not (r.observed_value or "").strip():
            log.warning("%s: %s carried no observed value — downgrading",
                        r.rule_id, r.native_result.value)
            r.unknown_reason = (
                f"a {r.native_result.value} verdict was produced without a cited "
                f"observed value; downgraded because an uncited verdict is not "
                f"reportable evidence")
            r.evidence = r.unknown_reason
            r.native_result = NativeResult.NOT_TESTABLE
            r.result = project(NativeResult.NOT_TESTABLE)
            r.confidence = 0.0
        out.append(r)
    return out


def family_coverage(results: list[SecurityResult],
                    rules: list[SecurityRule]) -> dict[str, dict]:
    """Per-family roll-up.

    The report leads with coverage rather than a score, because a single
    site-wide number over a pack that is 71% organizational evidence would be
    actively misleading. PCI-10 says so explicitly.
    """
    by_family: dict[str, dict] = {}
    rule_by_id = {r.control_id: r for r in rules}
    for r in results:
        fam = by_family.setdefault(r.category, {
            "total": 0, "decided": 0, "passed": 0, "failed": 0,
            "warn": 0, "informational": 0, "not_testable": 0,
            "not_applicable": 0, "critical_failures": [],
        })
        fam["total"] += 1
        match r.native_result:
            case NativeResult.PASS:
                fam["passed"] += 1; fam["decided"] += 1
            case NativeResult.FAIL:
                fam["failed"] += 1; fam["decided"] += 1
                if r.severity.rank >= 3:
                    fam["critical_failures"].append(r.rule_id)
            case NativeResult.WARN:
                fam["warn"] += 1
            case NativeResult.INFORMATIONAL:
                fam["informational"] += 1
            case NativeResult.NA:
                fam["not_applicable"] += 1
            case _:
                fam["not_testable"] += 1
    for fam in by_family.values():
        fam["coverage_pct"] = (round(100 * fam["decided"] / fam["total"], 1)
                               if fam["total"] else 0.0)
    return by_family


def deterministic_summary(target: str, tally: ResultTally,
                          results: list[SecurityResult]) -> str:
    """Summary that never needs a model. Always produced; used as fallback."""
    fails = sorted([r for r in results if r.native_result is NativeResult.FAIL],
                   key=lambda r: -r.severity.rank)
    lines = [
        f"Assessed {target} against {tally.total} controls from the rule pack.",
        f"A verdict was reached for {tally.decided} ({tally.coverage_pct}% "
        f"coverage): {tally.native_pass} PASS, {tally.native_fail} FAIL.",
        f"{tally.native_not_testable} controls were NOT_TESTABLE because they "
        f"require staging environments, contracts, SIEM exports or interviews "
        f"that a passive browser assessment cannot reach; "
        f"{tally.native_warn} returned WARN and "
        f"{tally.native_informational} INFORMATIONAL.",
    ]
    if fails:
        top = ", ".join(f"{r.rule_id} ({r.severity.value})" for r in fails[:6])
        lines.append(f"Confirmed failures: {top}.")
    lines.append("Controls not evaluated are NOT implied to pass. This "
                 "assessment reports observed technical facts only and does "
                 "not establish compliance with any framework.")
    return " ".join(lines)


async def write_summary(provider, *, llm_available: bool, target: str,
                        tally: ResultTally, results: list[SecurityResult],
                        coverage: dict) -> str:
    """One LLM call for prose. Falls back to the deterministic summary."""
    baseline = deterministic_summary(target, tally, results)
    if not llm_available:
        return baseline

    fails = [r for r in results if r.native_result is NativeResult.FAIL]
    passes = [r for r in results if r.native_result is NativeResult.PASS]
    user = f"""Target: {target}

DETERMINISTIC COUNTS (authoritative — do not recompute):
  total controls        {tally.total}
  verdict reached       {tally.decided}  ({tally.coverage_pct}% coverage)
  PASS                  {tally.native_pass}
  FAIL                  {tally.native_fail}
  WARN                  {tally.native_warn}
  INFORMATIONAL         {tally.native_informational}
  NOT_TESTABLE          {tally.native_not_testable}
  N/A                   {tally.native_na}

CONFIRMED FAILURES:
{chr(10).join(f'  {r.rule_id} [{r.severity.value}] {r.rule_name} — {r.evidence[:160]}' for r in fails[:15]) or '  none'}

CONFIRMED PASSES:
{chr(10).join(f'  {r.rule_id} {r.rule_name}' for r in passes[:15]) or '  none'}

PER-FAMILY COVERAGE:
{chr(10).join(f'  {k}: {v["decided"]}/{v["total"]} decided ({v["coverage_pct"]}%)' for k, v in sorted(coverage.items()))}

Write the executive summary."""
    try:
        text = await provider.complete(AGGREGATOR_SYSTEM, user)
        return text.strip() or baseline
    except (LLMUnavailable, Exception) as exc:                  # noqa: BLE001
        log.warning("summary generation failed, using deterministic summary: %s", exc)
        return baseline
