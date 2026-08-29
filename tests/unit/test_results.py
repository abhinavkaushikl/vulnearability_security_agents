"""The six-value / four-value projection must be total and lossless."""
from __future__ import annotations

import pytest

from app.models import results as R
from app.models.results import (ContractResult, NativeResult, ResultTally,
                                SecurityResult, project)
from app.models.rules import Automation, Severity, TestLayer, SecurityRule


def make_rule(control_id="WEB-01", automation=Automation.PASSIVE):
    return SecurityRule(
        control_id=control_id, control="A control.", test_method="Inspect.",
        pass_criteria="Present.", evidence="Headers", automation=automation,
        severity=Severity.HIGH, family=control_id.split("-")[0],
        control_domain="d", source_file="Rules/x.md", source_line=1,
        test_layer=TestLayer.from_automation(automation),
        requires_authorization=not automation.is_fully_passive)


def test_projection_is_total_over_every_native_value():
    assert set(R._PROJECTION) == set(NativeResult)


@pytest.mark.parametrize("native,contract", [
    (NativeResult.PASS, ContractResult.YES),
    (NativeResult.FAIL, ContractResult.NO),
    (NativeResult.NA, ContractResult.NOT_APPLICABLE),
    (NativeResult.WARN, ContractResult.UNKNOWN),
    (NativeResult.NOT_TESTABLE, ContractResult.UNKNOWN),
    (NativeResult.INFORMATIONAL, ContractResult.UNKNOWN),
])
def test_projection_mapping(native, contract):
    assert project(native) is contract


def test_the_three_unknown_kinds_stay_distinguishable():
    """Collapsing six into four would destroy the distinction the pack needs."""
    natives = [NativeResult.WARN, NativeResult.NOT_TESTABLE,
               NativeResult.INFORMATIONAL]
    assert len({project(n) for n in natives}) == 1      # same contract value
    assert len(set(natives)) == 3                        # still tellable apart


def test_not_testable_helper_records_a_reason():
    r = SecurityResult.not_testable(
        assessment_id="a", rule=make_rule(), reason="needs staging")
    assert r.native_result is NativeResult.NOT_TESTABLE
    assert r.result is ContractResult.UNKNOWN
    assert r.unknown_reason == "needs staging"
    assert r.confidence == 1.0      # certain that it is not testable


def _result(native, **kw):
    rule = make_rule()
    return SecurityResult(
        assessment_id="a", rule_id=rule.control_id, rule_name="n",
        category="WEB", result=project(native), native_result=native,
        evidence="e", source_of_evidence="s", severity=Severity.HIGH,
        automation_tier=Automation.PASSIVE, **kw)


def test_tally_counts_both_vocabularies():
    t = ResultTally.of([
        _result(NativeResult.PASS), _result(NativeResult.PASS),
        _result(NativeResult.FAIL), _result(NativeResult.WARN),
        _result(NativeResult.NOT_TESTABLE), _result(NativeResult.NA),
        _result(NativeResult.INFORMATIONAL),
    ])
    assert t.total == 7
    assert (t.yes, t.no, t.not_applicable, t.unknown) == (2, 1, 1, 3)
    assert t.native_pass == 2 and t.native_not_testable == 1
    assert t.decided == 3
    assert t.coverage_pct == pytest.approx(42.9, abs=0.1)


def test_coverage_of_an_all_unknown_run_is_zero():
    t = ResultTally.of([_result(NativeResult.NOT_TESTABLE) for _ in range(10)])
    assert t.decided == 0 and t.coverage_pct == 0.0
