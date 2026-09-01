"""Progress vocabulary for the streaming endpoint.

The stages are the graph's own nodes. Nothing here is decorative: every
event the API emits corresponds to a node that actually ran, and the
`requests` counter is read live from the TrafficBudget, so the number the
browser shows is the number of requests the target actually received.

The only interpolated value is `pct`. A progress bar that sits still for the
ninety seconds of the performance lane reads as a hang, so the heartbeat
eases it toward the next milestone. It is a UI affordance and it never
influences, gates or appears in a verdict.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from app.models.assessment import AssessmentStatus


@dataclass(frozen=True)
class Stage:
    """One graph node, as the interface sees it."""

    node: str
    status: AssessmentStatus
    code: str          # marquee, mirrors web/lib/stages.ts
    start_pct: float
    end_pct: float


#: Node name -> stage. Keys are the node names registered in
#: app/graph/workflow.py; adding a node without adding it here degrades to
#: "no progress event", never to a crash.
STAGES: dict[str, Stage] = {
    "load_rules": Stage("load_rules", AssessmentStatus.PLANNING,
                        "READING THE PACK", 2, 14),
    "plan": Stage("plan", AssessmentStatus.DISCOVERING,
                  "AGENT DEPLOYED", 14, 26),
    "collect_evidence": Stage("collect_evidence",
                              AssessmentStatus.COLLECTING_EVIDENCE,
                              "EVIDENCE COLLECTED", 26, 52),
    "evaluate": Stage("evaluate", AssessmentStatus.EVALUATING,
                      "CONTROLS EVALUATED", 52, 72),
    "performance": Stage("performance", AssessmentStatus.MEASURING_PERFORMANCE,
                         "NETWORK PROFILED", 72, 90),
    "aggregate": Stage("aggregate", AssessmentStatus.AGGREGATING,
                       "COVERAGE COMPUTED", 90, 97),
    "persist": Stage("persist", AssessmentStatus.AGGREGATING,
                     "REPORT WRITTEN", 97, 100),
}

#: Order used when two lanes report out of sequence. EVALUATE and PERFORMANCE
#: run concurrently, so their completions can arrive in either order; progress
#: is held monotonic against this order rather than against arrival time.
ORDER: list[str] = list(STAGES)


@dataclass
class Progress:
    """Mirrors web/lib/types.ts :: Progress exactly."""

    status: str
    pct: float
    label: str
    detail: str = ""
    requests: int = 0

    def as_dict(self) -> dict:
        return asdict(self)
