"""The anti-fabrication gate — the system's integrity backbone."""
from __future__ import annotations

import pytest

from app.models.results import NativeResult
from app.tools.evaluation import (EvaluationProposal, citation_is_grounded,
                                  validate_proposal)

CORPUS = (
    '{"response_headers": {"observed": true, "status": 200, '
    '"security_headers_present": {"x-content-type-options": "nosniff", '
    '"referrer-policy": "strict-origin-when-cross-origin"}, '
    '"security_headers_absent": ["content-security-policy", '
    '"strict-transport-security"]}}'
).lower()


def prop(result, observed=None, conf=0.9):
    return EvaluationProposal(result=result, observed_value=observed,
                              confidence=conf, evidence="e")


# --- grounded verdicts survive -------------------------------------------

@pytest.mark.parametrize("result,value", [
    ("PASS", "nosniff"),
    ("PASS", "strict-origin-when-cross-origin"),
    ("FAIL", "content-security-policy"),
    ("FAIL", "strict-transport-security"),
])
def test_grounded_verdicts_are_accepted(result, value):
    final, downgrade = validate_proposal(prop(result, value), CORPUS)
    assert final is NativeResult(result)
    assert downgrade is None


def test_reformatted_citation_still_counts_as_grounded():
    """A model that reformats what it saw is fine; one that invents is not."""
    final, _ = validate_proposal(
        prop("PASS", "X-Content-Type-Options: nosniff"), CORPUS)
    assert final is NativeResult.PASS


# --- fabricated verdicts are rejected ------------------------------------

@pytest.mark.parametrize("result,value", [
    ("FAIL", "Strict-Transport-Security: max-age=31536000"),
    ("PASS", "default-src 'self'; frame-ancestors 'none'"),
    ("PASS", "Set-Cookie: sid=x; Secure; HttpOnly"),
])
def test_invented_values_are_downgraded(result, value):
    final, downgrade = validate_proposal(prop(result, value), CORPUS)
    assert final is NativeResult.NOT_TESTABLE
    assert downgrade and "does not appear in the collected evidence" in downgrade


@pytest.mark.parametrize("result", ["PASS", "FAIL"])
def test_uncited_verdicts_are_downgraded(result):
    final, downgrade = validate_proposal(prop(result, None), CORPUS)
    assert final is NativeResult.NOT_TESTABLE
    assert downgrade


def test_unrecognised_result_is_downgraded_not_crashed():
    final, downgrade = validate_proposal(prop("TOTALLY_BROKEN", "nosniff"),
                                         CORPUS)
    assert final is NativeResult.NOT_TESTABLE
    assert "unrecognised result" in downgrade


# --- non-claiming verdicts need no citation ------------------------------

@pytest.mark.parametrize("result", ["NOT_TESTABLE", "WARN", "INFORMATIONAL",
                                    "N/A"])
def test_non_claiming_results_pass_through_without_a_citation(result):
    final, downgrade = validate_proposal(prop(result, None), CORPUS)
    assert final is NativeResult(result)
    assert downgrade is None


# --- the grounding predicate itself --------------------------------------

def test_citation_grounding_rejects_trivial_values():
    assert not citation_is_grounded("", CORPUS)
    assert not citation_is_grounded(None, CORPUS)
    assert not citation_is_grounded("ok", CORPUS)      # too short to mean anything


def test_citation_grounding_is_case_insensitive():
    assert citation_is_grounded("NOSNIFF", CORPUS)


# --- regression: tokenising must not collapse the citation ---------------

def test_tokeniser_splits_on_punctuation_not_into_one_blob():
    """Regression: normalising before splitting collapsed every citation into
    a single token, which made the grounding check reject real evidence."""
    from app.tools.evaluation import _tokens
    assert _tokens("sessionid: secure=false, http_only=false") == [
        "sessionid", "secure", "false", "http", "only", "false"]


def test_reformatted_multi_field_citation_is_grounded():
    corpus = ('{"cookies": [{"name": "sessionid", "secure": false, '
              '"http_only": false, "same_site": "lax"}]}')
    assert citation_is_grounded(
        "sessionid: secure=false, http_only=false", corpus)


def test_short_numeric_citation_must_match_a_whole_token():
    corpus = '{"response_headers": {"status": 200}, "cookies": []}'
    assert citation_is_grounded("200", corpus)
    # "ok" is a substring of "cookies" but is not a token — must be rejected
    assert not citation_is_grounded("ok", corpus)
    assert not citation_is_grounded("42", corpus)
