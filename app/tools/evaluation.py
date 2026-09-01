"""RuleEvaluationTool.

Two-stage, and the second stage is the important one.

  1. The LLM reads the rule text and the projected evidence and proposes a
     verdict. This is generic: no control-specific Python exists anywhere.
  2. A deterministic validator in Python checks the proposal. A FAIL or PASS
     whose observed_value does not appear in the evidence corpus is REJECTED
     and downgraded to UNKNOWN.

Stage 2 is why the system cannot fabricate a finding. It is a post-check in
code, not a plea in a prompt.

Controls the rule pack marks M or No are resolved to NOT_TESTABLE
deterministically, with no LLM call at all. That is roughly 102 of 144
controls, and it is driven by the Auto? column rather than by control
identity.
"""
from __future__ import annotations

import asyncio
import logging
import re

from pydantic import BaseModel, Field

from app.llm.base import LLMUnavailable
from app.llm.prompts import EVALUATOR_SYSTEM, evaluator_user
from app.models.evidence import EvidenceBundle
from app.models.results import NativeResult, SecurityResult, project
from app.models.rules import SecurityRule
from app.tools.evidence_projection import (evidence_corpus, project_for_rule,
                                           serialize_projection)

log = logging.getLogger(__name__)

#: Minimum length before we bother checking a citation against the evidence.
#: Below this a value is too generic for the check to mean anything.
_MIN_CITATION_LEN = 4


class EvaluationProposal(BaseModel):
    """What the model is allowed to return. Anything else fails validation."""

    result: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence: str = ""
    observed_value: str | None = None
    unknown_reason: str | None = None


def _normalise(value: str) -> str:
    """Strip everything but alphanumerics. Used for whole-string comparison."""
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _tokens(value: str) -> list[str]:
    """Split on non-alphanumeric boundaries.

    Tokenise BEFORE normalising: normalising first would strip the very
    separators we split on and collapse the citation into one giant token.
    """
    return [t for t in re.split(r"[^A-Za-z0-9]+", value.lower()) if t]


#: Share of substantive tokens that must be present for a citation to count.
_TOKEN_COVERAGE = 0.7


def citation_is_grounded(observed_value: str | None, corpus: str) -> bool:
    """Does the cited value actually appear in the evidence?

    Deliberately lenient about punctuation and formatting, strict about
    substance. A model that reformats a header it genuinely saw survives this;
    a model that invents one does not.

    Three passes, cheapest first:
      1. direct substring
      2. punctuation-insensitive whole-string
      3. token coverage — most substantive tokens must appear somewhere

    Short citations (a status code, a numeric max-age) skip straight to the
    strict substring test, because token coverage is meaningless for them.
    """
    if not observed_value:
        return False
    raw = observed_value.strip()
    if not raw:
        return False

    low = raw.lower()

    if len(raw) < _MIN_CITATION_LEN:
        # Substring matching is meaningless at this length ("ok" is inside
        # "cookies"). A short citation must match a WHOLE token, which is how
        # a genuine status code or numeric value appears in the evidence.
        return low in set(_tokens(corpus))

    if low in corpus:
        return True

    norm_raw, norm_corpus = _normalise(raw), _normalise(corpus)
    if norm_raw and norm_raw in norm_corpus:
        return True

    tokens = [t for t in _tokens(raw) if len(t) >= 3]
    if not tokens:
        return False
    hits = sum(1 for t in tokens if t in corpus or t in norm_corpus)
    return hits >= max(1, round(len(tokens) * _TOKEN_COVERAGE))


def validate_proposal(
    proposal: EvaluationProposal, corpus: str
) -> tuple[NativeResult, str | None]:
    """Deterministic gate on the model's proposal.

    Returns (final_result, downgrade_reason). A downgrade reason is set only
    when the proposal was rejected.
    """
    try:
        result = NativeResult(proposal.result.strip().upper()
                              if proposal.result.strip().upper() != "N/A"
                              else "N/A")
    except ValueError:
        return NativeResult.NOT_TESTABLE, (
            f"evaluator returned an unrecognised result {proposal.result!r}; "
            f"no verdict was recorded")

    # Only PASS and FAIL make a claim about the target. Those must be grounded.
    if result in (NativeResult.PASS, NativeResult.FAIL):
        if not citation_is_grounded(proposal.observed_value, corpus):
            return NativeResult.NOT_TESTABLE, (
                f"evaluator proposed {result.value} citing "
                f"{(proposal.observed_value or '(nothing)')!r}, which does not "
                f"appear in the collected evidence; downgraded to avoid "
                f"reporting an unverifiable finding")
    return result, None


class RuleEvaluator:
    """Evaluates rules against a frozen evidence bundle."""

    def __init__(self, provider, *, llm_available: bool,
                 max_concurrency: int = 4):
        self.provider = provider
        self.llm_available = llm_available
        self._sem = asyncio.Semaphore(max_concurrency)
        self.llm_calls = 0
        self.downgrades = 0

    async def evaluate_rule(self, rule: SecurityRule, bundle: EvidenceBundle,
                            assessment_id: str) -> SecurityResult:
        """One control. Never raises: a failure becomes an UNKNOWN result."""
        # --- deterministic short-circuit -------------------------------
        # Driven by the pack's own Auto? column, not by control identity.
        if not rule.automation.has_passive_component:
            return SecurityResult.not_testable(
                assessment_id=assessment_id, rule=rule,
                reason=(f"the rule pack marks {rule.control_id} as automation "
                        f"tier '{rule.automation.value}' ({rule.test_layer.value}): "
                        f"it requires {rule.test_method.lower().rstrip('.')}, "
                        f"which a passive browser assessment cannot supply"),
                source="rule-pack automation tier")

        if rule.interpretation is None or not rule.interpretation.required_collectors:
            return SecurityResult.not_testable(
                assessment_id=assessment_id, rule=rule,
                reason=("no evidence collector maps to this control at the "
                        "passive test layer"),
                source="assessment-plan")

        projection = project_for_rule(rule, bundle)
        corpus = evidence_corpus(projection)

        if not self.llm_available:
            return SecurityResult.not_testable(
                assessment_id=assessment_id, rule=rule,
                reason=("evidence was collected but no evaluator model was "
                        "available to interpret it against this control"),
                source="evidence collected, evaluation unavailable")

        async with self._sem:
            try:
                self.llm_calls += 1
                proposal = await self.provider.complete_structured(
                    EVALUATOR_SYSTEM,
                    evaluator_user(rule, serialize_projection(projection)),
                    EvaluationProposal)
            except LLMUnavailable as exc:
                return SecurityResult.not_testable(
                    assessment_id=assessment_id, rule=rule,
                    reason=f"evaluator model unavailable: {exc}",
                    source="evaluation unavailable")
            except Exception as exc:                            # noqa: BLE001
                log.warning("evaluation of %s raised: %s", rule.control_id, exc)
                return SecurityResult.not_testable(
                    assessment_id=assessment_id, rule=rule,
                    reason=f"evaluation failed: {type(exc).__name__}",
                    source="evaluation error")

        if proposal is None:
            return SecurityResult.not_testable(
                assessment_id=assessment_id, rule=rule,
                reason=("the evaluator model did not return a valid structured "
                        "verdict after retries"),
                source="evaluation unparseable")

        final, downgrade = validate_proposal(proposal, corpus)
        if downgrade:
            self.downgrades += 1
            log.info("downgraded %s: %s", rule.control_id, downgrade)

        collectors = ",".join(c.value for c in rule.interpretation.required_collectors)
        return SecurityResult(
            assessment_id=assessment_id,
            rule_id=rule.control_id,
            rule_name=rule.name,
            category=rule.family,
            result=project(final),
            native_result=final,
            evidence=(downgrade or proposal.evidence
                      or "no evidence statement was produced"),
            observed_value=None if downgrade else proposal.observed_value,
            source_of_evidence=f"collectors[{collectors}] @ {bundle.final_url or bundle.target_url}",
            # An undecided verdict must always say why: §7 rests on the reader
            # being able to tell "we looked and could not decide" from "this is
            # out of scope for a browser". Small models often omit the field,
            # so fall back rather than emit a reasonless UNKNOWN.
            unknown_reason=(downgrade or proposal.unknown_reason
                            or proposal.evidence
                            or "the evaluator returned no reason for the "
                               "undecided verdict"
                            if final in (NativeResult.NOT_TESTABLE,
                                         NativeResult.WARN,
                                         NativeResult.INFORMATIONAL)
                            else None),
            confidence=0.0 if downgrade else proposal.confidence,
            severity=rule.severity,
            automation_tier=rule.automation,
            source_file=rule.source_file,
            source_line=rule.source_line,
            evaluated_by=f"llm:{getattr(self.provider, 'model', 'unknown')}",
        )

    async def evaluate_all(self, rules: list[SecurityRule],
                           bundle: EvidenceBundle,
                           assessment_id: str) -> list[SecurityResult]:
        """Fan out across all controls.

        Safe to parallelise because the bundle is frozen and read-only, and
        because the pack defines no dependencies between controls.
        """
        results = await asyncio.gather(
            *[self.evaluate_rule(r, bundle, assessment_id) for r in rules],
            return_exceptions=True)
        out: list[SecurityResult] = []
        for rule, res in zip(rules, results):
            if isinstance(res, BaseException):
                log.error("rule %s failed hard: %s", rule.control_id, res)
                out.append(SecurityResult.not_testable(
                    assessment_id=assessment_id, rule=rule,
                    reason=f"evaluation raised {type(res).__name__}",
                    source="evaluation error"))
            else:
                out.append(res)
        return out
