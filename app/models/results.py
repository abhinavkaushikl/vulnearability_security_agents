"""Assessment result model.

Two vocabularies, deliberately. `Rules/00_README.md` and every family file
define six result values and explain why NOT_TESTABLE must stay distinct:
"keeping NOT_TESTABLE as a scanner-internal status prevents false claims of
compliance." The delivery contract asks for four. Collapsing six into four
destroys that distinction, so we carry both: the evaluator emits the
pack-native verdict and a pure function projects it to the contract value.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

from app.models.rules import Automation, Severity


class NativeResult(str, Enum):
    """The rule pack's own vocabulary (00_README.md, 18_rule_object_schema.md)."""

    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    NA = "N/A"
    INFORMATIONAL = "INFORMATIONAL"
    NOT_TESTABLE = "NOT_TESTABLE"


class ContractResult(str, Enum):
    """The four-value delivery contract."""

    YES = "YES"
    NO = "NO"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"


#: Total function. Every native value has exactly one contract projection.
_PROJECTION: dict[NativeResult, ContractResult] = {
    NativeResult.PASS: ContractResult.YES,
    NativeResult.FAIL: ContractResult.NO,
    NativeResult.NA: ContractResult.NOT_APPLICABLE,
    NativeResult.WARN: ContractResult.UNKNOWN,
    NativeResult.NOT_TESTABLE: ContractResult.UNKNOWN,
    NativeResult.INFORMATIONAL: ContractResult.UNKNOWN,
}


def project(native: NativeResult) -> ContractResult:
    """Map a pack-native verdict onto the four-value contract.

    Pure and total: no information is lost because both values are persisted
    side by side in Excel Sheet 2.
    """
    return _PROJECTION[native]


class SecurityResult(BaseModel):
    """One evaluated control."""

    assessment_id: str
    rule_id: str
    rule_name: str
    category: str                      # family code, e.g. "WEB"

    result: ContractResult             # four-value contract
    native_result: NativeResult        # pack-native verdict

    evidence: str                      # factual, quoted from what was observed
    observed_value: str | None = None  # verbatim value that drove the verdict
    source_of_evidence: str            # e.g. "HDR@https://example.com/"
    unknown_reason: str | None = None  # why we could not decide, when applicable

    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    severity: Severity
    automation_tier: Automation
    source_file: str = ""
    source_line: int = 0
    evaluated_by: str = "deterministic"   # "deterministic" | "llm:<model>"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def not_testable(
        cls,
        *,
        assessment_id: str,
        rule,
        reason: str,
        source: str = "assessment-plan",
    ) -> "SecurityResult":
        """Build the standard NOT_TESTABLE result.

        Used for the ~102 controls that need staging, contracts, SIEM exports
        or tabletop exercises. This is the honest default, not a failure mode.
        """
        return cls(
            assessment_id=assessment_id,
            rule_id=rule.control_id,
            rule_name=rule.name,
            category=rule.family,
            result=ContractResult.UNKNOWN,
            native_result=NativeResult.NOT_TESTABLE,
            evidence=reason,
            source_of_evidence=source,
            unknown_reason=reason,
            confidence=1.0,   # we are certain it is not testable here
            severity=rule.severity,
            automation_tier=rule.automation,
            source_file=rule.source_file,
            source_line=rule.source_line,
        )


class ResultTally(BaseModel):
    """Deterministic counts. Computed in Python; the LLM never counts."""

    total: int = 0
    yes: int = 0
    no: int = 0
    not_applicable: int = 0
    unknown: int = 0

    # native breakdown, so "unknown" can be read honestly
    native_pass: int = 0
    native_fail: int = 0
    native_warn: int = 0
    native_na: int = 0
    native_informational: int = 0
    native_not_testable: int = 0

    @classmethod
    def of(cls, results: list[SecurityResult]) -> "ResultTally":
        t = cls(total=len(results))
        for r in results:
            if r.result is ContractResult.YES:
                t.yes += 1
            elif r.result is ContractResult.NO:
                t.no += 1
            elif r.result is ContractResult.NOT_APPLICABLE:
                t.not_applicable += 1
            else:
                t.unknown += 1
            match r.native_result:
                case NativeResult.PASS: t.native_pass += 1
                case NativeResult.FAIL: t.native_fail += 1
                case NativeResult.WARN: t.native_warn += 1
                case NativeResult.NA: t.native_na += 1
                case NativeResult.INFORMATIONAL: t.native_informational += 1
                case NativeResult.NOT_TESTABLE: t.native_not_testable += 1
        return t

    @property
    def decided(self) -> int:
        """Controls where a real verdict was reached."""
        return self.native_pass + self.native_fail

    @property
    def coverage_pct(self) -> float:
        """Share of controls this run could actually decide."""
        return round(100.0 * self.decided / self.total, 1) if self.total else 0.0
