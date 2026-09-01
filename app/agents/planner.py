"""Planner Agent.

Optimises for MAXIMUM REQUIRED EVIDENCE with MINIMUM NECESSARY INTERACTION.
The agent is never rewarded for doing more actions; the plan is the union of
what the rules demand and nothing else.

Two stages:
  1. Interpret each rule into a collector set (LLM, cached forever on disk).
  2. Union those sets and emit the minimal action list (pure Python).

On a warm cache stage 1 costs zero LLM calls. Controls the pack marks M or No
skip interpretation entirely — that is ~102 of 144 resolved without a model.
"""
from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

from app.config.settings import Settings
from app.llm.base import LLMUnavailable
from app.llm.cache import InterpretationCache
from app.llm.prompts import INTERPRETER_SYSTEM, interpreter_user
from app.models.assessment import AssessmentPlan, PlannedAction
from app.models.rules import CollectorCode, RuleInterpretation, SecurityRule
from app.tools.inspection import registrable_host

log = logging.getLogger(__name__)

#: Collectors that are always gathered because they cost at most one request
#: and underpin the audit record itself (GOV-05, IN-07).
_BASELINE = {CollectorCode.SELF, CollectorCode.DOM, CollectorCode.HDR,
             CollectorCode.NET}


class Planner:
    def __init__(self, provider, settings: Settings, *, llm_available: bool):
        self.provider = provider
        self.settings = settings
        self.llm_available = llm_available
        self.cache = InterpretationCache(settings.llm.cache_dir)
        self.llm_calls = 0

    async def interpret(self, rule: SecurityRule) -> RuleInterpretation:
        """Interpret one rule. Cache first, model second, safe default third."""
        # Controls with no passive component need no interpretation: the pack
        # has already told us they cannot be reached from L1.
        if not rule.automation.has_passive_component:
            return RuleInterpretation(
                required_collectors=[], evaluable_at_l1=False,
                not_observable=[f"automation tier {rule.automation.value}: "
                                f"{rule.test_method}"])

        if cached := self.cache.get(rule.content_hash):
            return cached

        if not self.llm_available:
            return RuleInterpretation(required_collectors=[], evaluable_at_l1=False,
                                      not_observable=["no interpreter model available"])

        try:
            self.llm_calls += 1
            interp = await self.provider.complete_structured(
                INTERPRETER_SYSTEM, interpreter_user(rule), RuleInterpretation)
        except LLMUnavailable as exc:
            log.warning("interpretation of %s failed: %s", rule.control_id, exc)
            interp = None
        except Exception as exc:                                # noqa: BLE001
            log.warning("interpretation of %s raised: %s", rule.control_id, exc)
            interp = None

        if interp is None:
            return RuleInterpretation(
                required_collectors=[], evaluable_at_l1=False,
                not_observable=["interpreter did not return a usable mapping"])

        # A rule the pack marks passively automatable must map to at least one
        # collector. An empty set means the interpreter failed — small models
        # echo the schema's own placeholder text back as valid JSON — and
        # caching that would strand the control at NOT_TESTABLE on every future
        # run, since the cache is keyed on content_hash and never expires.
        # Return it for this run, but never persist it.
        if not interp.required_collectors:
            log.warning("interpreter returned no collectors for %s; not caching",
                        rule.control_id)
            return RuleInterpretation(
                required_collectors=[], evaluable_at_l1=False,
                not_observable=["interpreter returned an empty collector set"])

        self.cache.put(rule.content_hash, interp)
        return interp

    async def interpret_all(self, rules: list[SecurityRule]) -> None:
        """Attach interpretations in place, bounded concurrency."""
        sem = asyncio.Semaphore(self.settings.assessment.max_concurrent_evaluations)

        async def one(rule: SecurityRule):
            async with sem:
                rule.interpretation = await self.interpret(rule)

        await asyncio.gather(*[one(r) for r in rules])
        log.info("rule interpretation complete: %d LLM calls, cache %s",
                 self.llm_calls, self.cache.stats)

    def build_plan(self, target_url: str,
                   rules: list[SecurityRule]) -> AssessmentPlan:
        """Union the collector sets and emit the minimal action list."""
        plan = AssessmentPlan(
            target_url=target_url,
            in_scope_host=registrable_host(target_url),
            total_rules=len(rules))

        required: set[CollectorCode] = set(_BASELINE)
        for rule in rules:
            interp = rule.interpretation
            if interp and interp.required_collectors:
                plan.evaluable_rules.append(rule.control_id)
                required.update(interp.required_collectors)
            else:
                plan.not_testable_rules[rule.control_id] = (
                    f"automation tier {rule.automation.value}; "
                    f"no passive collector maps to this control")

        # Honour configuration switches: a disabled collector is never planned.
        a = self.settings.assessment
        if not a.collect_tls:
            required.discard(CollectorCode.TLS)
        if not a.collect_dns:
            required.discard(CollectorCode.DNS)
        if not a.probe_well_known:
            required.discard(CollectorCode.WK)
        if not a.probe_error_page:
            required.discard(CollectorCode.ERR)
        if not a.run_axe:
            required.discard(CollectorCode.A11)
        if not self.settings.screenshots.enabled:
            required.discard(CollectorCode.SHOT)

        plan.required_collectors = sorted(required, key=lambda c: c.value)

        # --- the action list. This is the ENTIRE interaction budget.
        by_collector: dict[CollectorCode, list[str]] = {}
        for rule in rules:
            for c in (rule.interpretation.required_collectors
                      if rule.interpretation else []):
                by_collector.setdefault(c, []).append(rule.control_id)

        plan.actions.append(PlannedAction(
            kind="navigate", target=target_url,
            reason="single instrumented page load feeding all in-page collectors",
            required_by=sorted({r for c in required if c not in
                                (CollectorCode.TLS, CollectorCode.DNS,
                                 CollectorCode.RDR, CollectorCode.WK,
                                 CollectorCode.ERR)
                                for r in by_collector.get(c, [])})[:40]))

        aux = 1  # the navigation itself
        if CollectorCode.CWV in required or CollectorCode.NET in required:
            plan.actions.append(PlannedAction(
                kind="scroll_to_fold", target=target_url,
                reason="settle lazy-loaded resources for LCP and mixed-content checks",
                required_by=by_collector.get(CollectorCode.CWV, [])[:10]))
        for code, kind, why in (
            (CollectorCode.RDR, "probe_http_scheme", "HTTP to HTTPS redirect chain"),
            (CollectorCode.WK, "fetch_well_known", "security.txt and robots.txt"),
            (CollectorCode.ERR, "probe_benign_404", "server error-page disclosure"),
        ):
            if code in required:
                plan.actions.append(PlannedAction(
                    kind=kind, target=target_url, reason=why,
                    required_by=by_collector.get(code, [])[:10]))
                aux += 2 if code is CollectorCode.WK else 1
        if CollectorCode.SHOT in required:
            plan.actions.append(PlannedAction(
                kind="screenshot", target=target_url,
                reason="visual evidence attachment"))

        perf = self.settings.performance
        perf_navs = (len(self.settings.active_profiles) * perf.iterations
                     if perf.enabled else 0)
        plan.estimated_requests = aux + perf_navs

        plan.notes.append(
            f"{len(plan.evaluable_rules)} of {len(rules)} controls have a passive "
            f"evidence route; {len(plan.not_testable_rules)} require staging, "
            f"organizational or operational evidence and will be reported "
            f"NOT_TESTABLE.")
        plan.notes.append(
            f"estimated target traffic: {aux} assessment requests + "
            f"{perf_navs} performance navigations = {plan.estimated_requests} total.")
        if self.settings.assessment.mode == "passive":
            plan.notes.append(
                "passive mode: no login is attempted, no form is submitted, and "
                "no link is followed.")
        return plan
