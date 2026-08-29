"""Assessment-level model: status, plan, errors, report."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

from app.models.performance import (PerformanceMeasurement, PerformanceStatistics,
                                    ProfileOutcome)
from app.models.results import ResultTally, SecurityResult
from app.models.rules import CollectorCode


class AssessmentStatus(str, Enum):
    INITIALIZING = "INITIALIZING"
    PLANNING = "PLANNING"
    DISCOVERING = "DISCOVERING"
    COLLECTING_EVIDENCE = "COLLECTING_EVIDENCE"
    EVALUATING = "EVALUATING"
    MEASURING_PERFORMANCE = "MEASURING_PERFORMANCE"
    AGGREGATING = "AGGREGATING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"     # target challenged us; we stopped, by design
    FAILED = "FAILED"

    @property
    def is_terminal(self) -> bool:
        return self in (AssessmentStatus.COMPLETED, AssessmentStatus.PARTIAL,
                        AssessmentStatus.BLOCKED, AssessmentStatus.FAILED)


class ComponentError(BaseModel):
    """A failure scoped to one component. One failed rule never stops the run."""

    component: str            # "collector:TLS" | "rule:WEB-01" | "profile:3g"
    message: str
    fatal: bool = False
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PlannedAction(BaseModel):
    """One browser action the plan authorises. Nothing else may run.

    This list is the *entire* interaction budget. There is no code path that
    performs a browser action not present here.
    """

    kind: str                 # "navigate" | "scroll_to_fold" | "screenshot" | ...
    target: str = ""
    reason: str = ""          # which control needs this — required, never blank
    required_by: list[str] = Field(default_factory=list)


class AssessmentPlan(BaseModel):
    """Output of PLAN_ASSESSMENT. Maximum evidence, minimum interaction."""

    target_url: str
    in_scope_host: str = ""
    total_rules: int = 0
    evaluable_rules: list[str] = Field(default_factory=list)
    not_testable_rules: dict[str, str] = Field(default_factory=dict)  # id -> reason
    required_collectors: list[CollectorCode] = Field(default_factory=list)
    actions: list[PlannedAction] = Field(default_factory=list)
    estimated_requests: int = 0
    notes: list[str] = Field(default_factory=list)


class AntiBotSignal(BaseModel):
    """Recorded, never bypassed. See Rules/19_test_modes_safety.md."""

    detected: bool = False
    kind: str = ""            # "rate_limit" | "captcha" | "access_denied" | ...
    status: int | None = None
    url: str = ""
    detail: str = ""


class Assessment(BaseModel):
    """Sheet 1 row."""

    assessment_id: str
    target_url: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: AssessmentStatus = AssessmentStatus.INITIALIZING
    tally: ResultTally = Field(default_factory=ResultTally)
    pack_version: str = ""
    coverage_pct: float = 0.0
    browser_version: str = ""
    llm_model: str = ""
    blocked_reason: str | None = None
    duration_seconds: float = 0.0


class AssessmentReport(BaseModel):
    """Everything the run produced."""

    assessment: Assessment
    plan: AssessmentPlan | None = None
    security_results: list[SecurityResult] = Field(default_factory=list)
    performance_raw: list[PerformanceMeasurement] = Field(default_factory=list)
    performance_stats: list[PerformanceStatistics] = Field(default_factory=list)
    profile_outcomes: list[ProfileOutcome] = Field(default_factory=list)
    errors: list[ComponentError] = Field(default_factory=list)
    summary_text: str = ""
    family_coverage: dict[str, dict] = Field(default_factory=dict)
