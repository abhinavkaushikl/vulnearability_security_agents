"""Typed LangGraph state.

The EvidenceBundle is written exactly once, by collect_evidence, and is
read-only thereafter. No downstream node holds a browser handle, so reaching
COMPLETED structurally guarantees that browser activity has stopped.
"""
from __future__ import annotations

from typing import Annotated, TypedDict

from app.config.settings import Settings
from app.models.assessment import (AntiBotSignal, AssessmentPlan,
                                   AssessmentStatus, ComponentError)
from app.models.evidence import EvidenceBundle
from app.models.performance import (PerformanceMeasurement,
                                    PerformanceStatistics, ProfileOutcome)
from app.models.results import ResultTally, SecurityResult
from app.models.rules import RuleFamily, SecurityRule


def _extend(left: list, right: list) -> list:
    """Reducer for lists written by concurrently-running branches."""
    return (left or []) + (right or [])


class AssessmentState(TypedDict, total=False):
    # --- identity and configuration
    assessment_id: str
    target_url: str
    settings: Settings
    status: AssessmentStatus
    started_at: float

    # --- rules
    families: list[RuleFamily]
    rules: list[SecurityRule]
    plan: AssessmentPlan

    # --- evidence (write-once, then read-only)
    evidence: EvidenceBundle
    anti_bot: AntiBotSignal

    # --- results
    security_results: list[SecurityResult]
    tally: ResultTally
    performance_raw: list[PerformanceMeasurement]
    performance_stats: list[PerformanceStatistics]
    profile_outcomes: list[ProfileOutcome]
    family_coverage: dict

    # --- runtime collaborators
    provider: object
    llm_available: bool
    session: object
    budget: object
    repository: object

    # --- observability. Concurrent branches both append here.
    errors: Annotated[list[ComponentError], _extend]
    summary_text: str
    report_path: str
