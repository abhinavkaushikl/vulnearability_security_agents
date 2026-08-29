r"""LangGraph workflow assembly.

    START
      -> LOAD_RULES
      -> PLAN_ASSESSMENT
      -> COLLECT_EVIDENCE
      -> fork ---> EVALUATE_RULES ------\
            \----> PERFORMANCE ---------/-> AGGREGATE -> PERSIST -> END

The fork is genuine concurrency between two lanes with very different
characters:

  * EVALUATE_RULES reads a frozen in-memory bundle and issues NO network
    traffic at all. It is safe to run beside anything.
  * PERFORMANCE owns the network. Inside it, profiles run strictly in series,
    because all four share one physical uplink — running them concurrently
    would measure contention rather than the profile, and would quadruple
    simultaneous load on the target.

A BLOCKED assessment short-circuits both lanes: every control is marked
NOT_TESTABLE with the recorded reason and no further traffic is generated.
"""
from __future__ import annotations

import logging

from langgraph.graph import END, START, StateGraph

from app.graph.nodes import (aggregate_node, collect_evidence_node,
                             evaluate_node, load_rules_node,
                             orchestrate_node, performance_node,
                             persist_node, plan_node)
from app.graph.state import AssessmentState
from app.models.assessment import AssessmentStatus

log = logging.getLogger(__name__)


def _after_load(state: AssessmentState) -> str:
    return "end" if state.get("status") is AssessmentStatus.FAILED else "plan"


def _after_collect(state: AssessmentState) -> list[str]:
    """Fan out to both lanes. Both run even when BLOCKED, and both no-op
    correctly in that case — evaluation records the reason on every control,
    performance declines to generate traffic."""
    if state.get("status") is AssessmentStatus.FAILED:
        return ["aggregate"]
    return ["evaluate", "performance"]


def build_workflow(*, agentic: bool = True):
    """Compile the assessment graph.

    agentic=True (default): orchestrator agent decides which rules to evaluate.
    agentic=False: deterministic planner evaluates all passive rules.
    """
    g = StateGraph(AssessmentState)

    g.add_node("load_rules", load_rules_node)
    g.add_node("plan", orchestrate_node if agentic else plan_node)
    g.add_node("collect_evidence", collect_evidence_node)
    g.add_node("evaluate", evaluate_node)
    g.add_node("performance", performance_node)
    g.add_node("aggregate", aggregate_node)
    g.add_node("persist", persist_node)

    g.add_edge(START, "load_rules")
    g.add_conditional_edges("load_rules", _after_load,
                            {"plan": "plan", "end": END})
    g.add_edge("plan", "collect_evidence")
    g.add_conditional_edges("collect_evidence", _after_collect,
                            ["evaluate", "performance", "aggregate"])
    # Both lanes must finish before aggregation; LangGraph joins them here.
    g.add_edge("evaluate", "aggregate")
    g.add_edge("performance", "aggregate")
    g.add_edge("aggregate", "persist")
    g.add_edge("persist", END)

    return g.compile()
