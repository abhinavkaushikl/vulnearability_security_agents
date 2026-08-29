"""Statistics must be deterministic and must never fabricate a measurement."""
from __future__ import annotations

import pytest

from app.models.performance import PerformanceMeasurement
from app.tools.statistics import (calculate_percentile, calculate_percentiles,
                                  calculate_statistics, summarise_measurements)


@pytest.mark.parametrize("values,pct,expected", [
    ([1, 2, 3, 4], 50, 2.5),
    ([1, 2, 3, 4, 5], 0, 1.0),
    ([1, 2, 3, 4, 5], 100, 5.0),
    ([10], 95, 10.0),
    ([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 95, 9.55),
    ([100, 200, 300], 95, 290.0),
])
def test_percentile_matches_hand_computed_values(values, pct, expected):
    assert calculate_percentile(values, pct) == pytest.approx(expected)


def test_percentile_of_empty_sample_is_none_not_zero():
    assert calculate_percentile([], 95) is None


def test_calculate_percentiles_returns_all_requested():
    out = calculate_percentiles([1, 2, 3, 4], [50, 95])
    assert set(out) == {50, 95}


def _stats(values, attempts=None):
    return calculate_statistics(assessment_id="a", network_profile="fast",
                                metric="ttfb", values=values,
                                total_attempts=attempts)


def test_basic_reduction_is_exact():
    s = _stats([100.0, 200.0, 300.0])
    assert (s.mean, s.median, s.min, s.max, s.n) == (200.0, 200.0, 100.0, 300.0, 3)
    assert s.stddev == pytest.approx(100.0)
    assert s.success_rate == 1.0 and s.failure_rate == 0.0


def test_sample_stddev_is_none_for_a_single_point():
    """n=1 has no sample deviation. Zero would imply perfect consistency."""
    assert _stats([42.0]).stddev is None


def test_empty_sample_fabricates_nothing():
    """A zero here would read as '0 ms' — a measurement we never took."""
    s = _stats([], attempts=3)
    assert s.mean is s.median is s.min is s.max is s.p95 is s.stddev is None
    assert s.n == 0 and s.failure_rate == 1.0


def test_failure_rate_reflects_attempts_not_samples():
    s = _stats([100.0, 200.0], attempts=3)
    assert s.success_rate == pytest.approx(2 / 3, abs=1e-4)
    assert s.failure_rate == pytest.approx(1 / 3, abs=1e-4)


def test_failed_iterations_are_excluded_from_central_tendency():
    """A profile failing 2 of 3 loads must read as unstable, not as fast."""
    ms = [
        PerformanceMeasurement(assessment_id="a", network_profile="3g",
                               iteration=1, succeeded=True, ttfb=900.0),
        PerformanceMeasurement(assessment_id="a", network_profile="3g",
                               iteration=2, succeeded=False, error="timeout"),
        PerformanceMeasurement(assessment_id="a", network_profile="3g",
                               iteration=3, succeeded=False, error="timeout"),
    ]
    ttfb = next(s for s in summarise_measurements(ms, "a") if s.metric == "ttfb")
    assert ttfb.n == 1
    assert ttfb.mean == 900.0
    assert ttfb.failure_rate == pytest.approx(2 / 3, abs=1e-4)


def test_summarise_covers_every_profile_and_metric():
    ms = [PerformanceMeasurement(assessment_id="a", network_profile=p,
                                 iteration=1, succeeded=True, ttfb=10.0)
          for p in ("fast", "3g")]
    stats = summarise_measurements(ms, "a")
    assert len(stats) == 2 * len(PerformanceMeasurement.METRICS)
    assert {s.network_profile for s in stats} == {"fast", "3g"}


def test_none_metrics_are_skipped_not_coerced():
    """INP is never measured; it must not become 0.0 in the statistics."""
    ms = [PerformanceMeasurement(assessment_id="a", network_profile="fast",
                                 iteration=1, succeeded=True,
                                 ttfb=10.0, lcp=None)]
    lcp = next(s for s in summarise_measurements(ms, "a") if s.metric == "lcp")
    assert lcp.n == 0 and lcp.mean is None
