"""StatisticsTool — deterministic reduction of raw measurements.

The LLM never computes a statistic. This module is pure: same input, same
output, no I/O, no model. Everything in the performance report traces back
to here.

Two deliberate choices worth knowing about:

* `stddev` is the SAMPLE deviation (n-1). With the default 3 iterations this
  is a weak estimate, so `n` is always reported beside it.
* `p95` uses linear interpolation between closest ranks (the same method as
  numpy's default). With n=3 the "95th percentile" is barely more than the
  maximum. We report it because the spec asks for it, and we report `n` so
  nobody mistakes it for a population percentile.
"""
from __future__ import annotations

import math
import statistics as py_stats

from app.models.performance import PerformanceMeasurement, PerformanceStatistics


def calculate_percentile(values: list[float], percentile: float) -> float | None:
    """Linear interpolation between closest ranks.

    >>> calculate_percentile([1, 2, 3, 4], 50)
    2.5
    >>> calculate_percentile([10], 95)
    10.0
    """
    if not values:
        return None
    if percentile <= 0:
        return float(min(values))
    if percentile >= 100:
        return float(max(values))

    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]

    rank = (percentile / 100.0) * (len(ordered) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def calculate_percentiles(
    values: list[float], percentiles: list[float]
) -> dict[float, float | None]:
    """Several percentiles over one sample."""
    return {p: calculate_percentile(values, p) for p in percentiles}


def calculate_statistics(
    *,
    assessment_id: str,
    network_profile: str,
    metric: str,
    values: list[float],
    total_attempts: int | None = None,
) -> PerformanceStatistics:
    """Reduce one metric's samples to a statistics row.

    `values` must contain only successful, non-None samples. `total_attempts`
    is the number of iterations attempted, used for success/failure rate; it
    defaults to len(values), i.e. "everything we tried, worked".
    """
    attempts = len(values) if total_attempts is None else total_attempts
    n = len(values)

    stats = PerformanceStatistics(
        assessment_id=assessment_id,
        network_profile=network_profile,
        metric=metric,
        n=n,
        success_rate=round(n / attempts, 4) if attempts else 0.0,
        failure_rate=round((attempts - n) / attempts, 4) if attempts else 0.0,
    )
    if n == 0:
        # No samples: every field stays None. We do not emit zeros — a zero
        # would read as "0 ms", which is a fabricated measurement.
        return stats

    floats = [float(v) for v in values]
    stats.mean = py_stats.fmean(floats)
    stats.median = py_stats.median(floats)
    stats.min = min(floats)
    stats.max = max(floats)
    stats.stddev = py_stats.stdev(floats) if n > 1 else None
    stats.p95 = calculate_percentile(floats, 95)
    return stats


def summarise_measurements(
    measurements: list[PerformanceMeasurement],
    assessment_id: str,
) -> list[PerformanceStatistics]:
    """Full reduction: every profile x every metric.

    Failed iterations are excluded from central tendency but counted in
    `failure_rate`, so a profile that fails two of three loads reads as
    unstable rather than fast.
    """
    by_profile: dict[str, list[PerformanceMeasurement]] = {}
    for m in measurements:
        by_profile.setdefault(m.network_profile, []).append(m)

    out: list[PerformanceStatistics] = []
    for profile, rows in by_profile.items():
        attempts = len(rows)
        successful = [r for r in rows if r.succeeded]
        for metric in PerformanceMeasurement.METRICS:
            values = [
                getattr(r, metric) for r in successful
                if getattr(r, metric, None) is not None
            ]
            out.append(calculate_statistics(
                assessment_id=assessment_id,
                network_profile=profile,
                metric=metric,
                values=values,
                total_attempts=attempts,
            ))
    return out
