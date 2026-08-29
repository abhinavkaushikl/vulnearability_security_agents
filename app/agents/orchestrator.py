"""Orchestrator Agent — the agentic brain of the assessment.

Unlike the fixed pipeline, the orchestrator DECIDES:
  1. What kind of site is this? (recon)
  2. Which rules are relevant? (rule selection)
  3. Which tools to call? (tool selection)
  4. What to do with the results? (adapt)
  5. Should I dig deeper? (iterative refinement)

This is a ReAct (Reason + Act) agent: it thinks, acts, observes, and loops
until it decides the assessment is complete.

The deterministic safety guards are PRESERVED:
  - Anti-fabrication gate still validates every LLM verdict
  - Traffic budget still caps all requests
  - Redaction still happens at capture
  - Anti-bot detection still halts on a block
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.llm.base import LLMUnavailable, extract_json
from app.tools.registry import ToolRegistry

log = logging.getLogger(__name__)

# maximum iterations the orchestrator will run before forcing completion
MAX_REACT_STEPS = 15


class OrchestratorAction(str, Enum):
    """What the orchestrator can decide to do at each step."""

    CALL_TOOL = "call_tool"          # call a tool from the registry
    SELECT_RULES = "select_rules"    # choose which rules to evaluate
    EVALUATE = "evaluate"            # evaluate selected rules against evidence
    ANALYZE = "analyze"              # run an analyzer tool on collected data
    FINISH = "finish"                # assessment complete


@dataclass
class OrchestratorStep:
    """One step in the ReAct loop."""

    step: int
    thought: str
    action: OrchestratorAction
    tool_name: str | None = None
    tool_args: dict[str, Any] = field(default_factory=dict)
    result: Any = None
    error: str | None = None
    selected_rules: list[str] = field(default_factory=list)


@dataclass
class OrchestratorPlan:
    """The orchestrator's running plan — updated as it learns."""

    target_url: str
    site_type: str = ""              # "e-commerce", "blog", "api", etc.
    relevant_families: list[str] = field(default_factory=list)
    selected_rule_ids: list[str] = field(default_factory=list)
    tools_called: list[str] = field(default_factory=list)
    evidence_collected: dict[str, Any] = field(default_factory=dict)
    findings: list[str] = field(default_factory=list)
    steps: list[OrchestratorStep] = field(default_factory=list)
    done: bool = False
    done_reason: str = ""


def build_orchestrator_system_prompt(tool_listing: str) -> str:
    """System prompt for the orchestrator — gives it the tool catalog."""
    return f"""\
You are a Security Assessment Orchestrator. You drive a website security
assessment by deciding WHAT to check and WHICH tools to use.

You operate in a ReAct loop: think about what you know, decide an action,
observe the result, then think again.

AVAILABLE TOOLS:
{tool_listing}

At each step you MUST return exactly one JSON object:

To call a tool:
{{"thought": "why I want to call this tool",
  "action": "call_tool",
  "tool_name": "the_tool_name",
  "tool_args": {{"arg1": "value1"}}}}

To select which rules to evaluate:
{{"thought": "based on what I've seen, these rules are relevant",
  "action": "select_rules",
  "selected_rules": ["NET-01", "WEB-05", ...],
  "reasoning": "why these rules"}}

To run an analyzer on collected data:
{{"thought": "I have cookie data, let me analyze it",
  "action": "analyze",
  "tool_name": "analyze_cookies_security",
  "tool_args": {{"cookies": [...]}}}}

To finish the assessment:
{{"thought": "I have collected enough evidence and evaluated the relevant rules",
  "action": "finish",
  "summary": "what I found"}}

RULES:
- Start by understanding what kind of site the target is
- Select rules that are RELEVANT to this specific target
- Only call tools that are needed — don't collect everything blindly
- If a tool requires browser and you don't have one, skip it
- If you find something interesting, dig deeper with more tools
- You MUST eventually finish — don't loop forever
- Network tools (TLS, DNS, redirect) can run WITHOUT a browser
- Browser tools need an active page
- Analyzer tools work on already-collected data
"""


def build_step_user_prompt(
    plan: OrchestratorPlan,
    rules_summary: str,
    step_number: int,
) -> str:
    """User prompt at each ReAct step — shows the orchestrator what it knows."""
    collected = list(plan.evidence_collected.keys()) if plan.evidence_collected else ["nothing yet"]
    tools_used = plan.tools_called or ["none yet"]
    findings = plan.findings[:10] or ["none yet"]

    return f"""Step {step_number}/{MAX_REACT_STEPS}. Decide your next action.

TARGET: {plan.target_url}
SITE TYPE: {plan.site_type or "not yet determined"}
RELEVANT FAMILIES: {", ".join(plan.relevant_families) or "not yet decided"}

EVIDENCE COLLECTED SO FAR: {", ".join(collected)}
TOOLS ALREADY CALLED: {", ".join(tools_used)}
FINDINGS SO FAR: {chr(10).join(findings)}

SELECTED RULES: {len(plan.selected_rule_ids)} selected
{chr(10).join(f"  - {r}" for r in plan.selected_rule_ids[:20]) if plan.selected_rule_ids else "  none yet"}

AVAILABLE RULES (from the rule pack):
{rules_summary}

What should we do next?"""


def format_rules_for_orchestrator(rules) -> str:
    """Compact summary of all rules grouped by family."""
    by_family: dict[str, list] = {}
    for r in rules:
        by_family.setdefault(r.family, []).append(r)

    lines = []
    for fam, fam_rules in sorted(by_family.items()):
        passive = [r for r in fam_rules if r.automation.has_passive_component]
        manual = [r for r in fam_rules if not r.automation.has_passive_component]
        lines.append(f"\n{fam} ({len(fam_rules)} rules, {len(passive)} automatable):")
        for r in passive:
            lines.append(
                f"  [{r.automation.value}] {r.control_id} [{r.severity.value}] "
                f"{r.control[:80]}")
        if manual:
            lines.append(f"  ... + {len(manual)} manual-only rules")
    return "\n".join(lines)


class Orchestrator:
    """ReAct agent that drives the assessment.

    Instead of a fixed pipeline, the orchestrator:
      1. Analyzes the target
      2. Selects relevant rules
      3. Decides which tools to call
      4. Collects evidence dynamically
      5. Adapts based on findings
    """

    def __init__(
        self,
        provider,
        registry: ToolRegistry,
        *,
        llm_available: bool,
        max_steps: int = MAX_REACT_STEPS,
    ):
        self.provider = provider
        self.registry = registry
        self.llm_available = llm_available
        self.max_steps = max_steps
        self.system_prompt = build_orchestrator_system_prompt(
            registry.describe_all_for_llm())

    async def run(
        self,
        target_url: str,
        rules: list,
        *,
        context: dict | None = None,
    ) -> OrchestratorPlan:
        """Run the ReAct loop. Returns the orchestrator's plan and findings."""
        plan = OrchestratorPlan(target_url=target_url)
        rules_summary = format_rules_for_orchestrator(rules)
        ctx = context or {}

        if not self.llm_available:
            log.warning("orchestrator: no LLM available, falling back to "
                        "deterministic rule selection")
            return self._deterministic_fallback(plan, rules)

        for step_num in range(1, self.max_steps + 1):
            user_prompt = build_step_user_prompt(plan, rules_summary, step_num)

            try:
                raw = await self.provider.complete(
                    self.system_prompt, user_prompt, json_mode=True)
                decision = extract_json(raw)
            except LLMUnavailable as exc:
                log.warning("orchestrator LLM unavailable at step %d: %s",
                            step_num, exc)
                break
            except Exception as exc:                                # noqa: BLE001
                log.warning("orchestrator step %d failed: %s", step_num, exc)
                break

            if not decision:
                log.warning("orchestrator returned unparseable response at step %d",
                            step_num)
                break

            step = self._parse_step(step_num, decision)
            plan.steps.append(step)
            log.info("orchestrator step %d: %s — %s",
                     step_num, step.action.value,
                     step.tool_name or step.thought[:80])

            if step.action == OrchestratorAction.FINISH:
                plan.done = True
                plan.done_reason = decision.get("summary", "orchestrator decided to finish")
                break

            if step.action == OrchestratorAction.SELECT_RULES:
                plan.selected_rule_ids = step.selected_rules
                # Also infer relevant families
                plan.relevant_families = sorted({
                    rid.split("-")[0] for rid in step.selected_rules
                    if "-" in rid})
                continue

            if step.action in (OrchestratorAction.CALL_TOOL,
                               OrchestratorAction.ANALYZE):
                await self._execute_tool_step(step, plan, ctx)
                continue

        if not plan.done:
            plan.done = True
            plan.done_reason = f"reached max steps ({self.max_steps})"
            log.warning("orchestrator hit max steps, forcing completion")

        # If no rules were selected, fall back to passive-automatable rules
        if not plan.selected_rule_ids:
            plan = self._deterministic_fallback(plan, rules)

        return plan

    def _parse_step(self, step_num: int, decision: dict) -> OrchestratorStep:
        """Parse the LLM's JSON decision into a typed step."""
        action_str = decision.get("action", "finish")
        try:
            action = OrchestratorAction(action_str)
        except ValueError:
            action = OrchestratorAction.FINISH

        return OrchestratorStep(
            step=step_num,
            thought=decision.get("thought", ""),
            action=action,
            tool_name=decision.get("tool_name"),
            tool_args=decision.get("tool_args", {}),
            selected_rules=decision.get("selected_rules", []),
        )

    async def _execute_tool_step(
        self,
        step: OrchestratorStep,
        plan: OrchestratorPlan,
        ctx: dict,
    ) -> None:
        """Execute a tool call and record the result."""
        if not step.tool_name:
            step.error = "no tool_name provided"
            return

        spec = self.registry.get(step.tool_name)
        if not spec:
            step.error = f"unknown tool: {step.tool_name}"
            plan.findings.append(f"tried to call unknown tool: {step.tool_name}")
            return

        # Safety: check if tool requirements are met
        if spec.requires_browser and "page" not in ctx and "session" not in ctx:
            step.error = "tool requires browser but no session available"
            plan.findings.append(
                f"skipped {step.tool_name}: needs browser (not available yet)")
            return

        # Inject context objects that tools need but LLM can't provide
        args = dict(step.tool_args)
        for key in ("page", "context", "session", "artifact_dir", "evaluator"):
            if key in spec.parameters and key in ctx and key not in args:
                args[key] = ctx[key]

        try:
            result = await self.registry.call(step.tool_name, **args)
            step.result = result
            plan.tools_called.append(step.tool_name)

            # Store evidence keyed by collector code or tool name
            key = spec.collector_code or step.tool_name
            plan.evidence_collected[key] = _safe_summary(result)
            plan.findings.append(
                f"{step.tool_name}: completed — {_one_line_summary(result)}")
        except Exception as exc:                                    # noqa: BLE001
            step.error = f"{type(exc).__name__}: {exc}"
            plan.findings.append(f"{step.tool_name} failed: {step.error}")
            log.warning("orchestrator tool %s failed: %s", step.tool_name, exc)

    def _deterministic_fallback(
        self,
        plan: OrchestratorPlan,
        rules: list,
    ) -> OrchestratorPlan:
        """When LLM is unavailable, select all passive-automatable rules."""
        plan.selected_rule_ids = [
            r.control_id for r in rules
            if r.automation.has_passive_component
        ]
        plan.relevant_families = sorted({
            r.family for r in rules
            if r.automation.has_passive_component
        })
        plan.done = True
        plan.done_reason = "deterministic fallback: all passive rules selected"
        return plan

    def get_selected_rules(self, plan: OrchestratorPlan, all_rules: list) -> list:
        """Filter the full rule list to just what the orchestrator selected."""
        if not plan.selected_rule_ids:
            return all_rules
        selected = set(plan.selected_rule_ids)
        return [r for r in all_rules if r.control_id in selected]


def _safe_summary(result: Any, max_len: int = 500) -> str:
    """Summarize a tool result for the orchestrator's context window."""
    if result is None:
        return "null"
    if isinstance(result, str):
        return result[:max_len]
    if isinstance(result, (list, tuple)):
        return f"[{len(result)} items]"
    try:
        if hasattr(result, "model_dump"):
            d = result.model_dump()
        elif hasattr(result, "__dict__"):
            d = {k: v for k, v in result.__dict__.items()
                 if not k.startswith("_")}
        else:
            d = result
        text = json.dumps(d, default=str, ensure_ascii=False)
        return text[:max_len] + ("..." if len(text) > max_len else "")
    except Exception:                                               # noqa: BLE001
        return str(result)[:max_len]


def _one_line_summary(result: Any) -> str:
    """One-line summary for the findings log."""
    s = _safe_summary(result, max_len=120)
    return s.replace("\n", " ")[:120]
