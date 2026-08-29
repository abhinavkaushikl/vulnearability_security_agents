"""Performance model.

Statistics are pure Python (StatisticsTool). The LLM never sees a number it
is asked to reduce — required by the brief and by basic determinism.
"""
from __future__ import annotations

from enum import Enum
from typing import ClassVar

from pydantic import BaseModel, Field


class NetworkProfile(BaseModel):
    """A throttling profile. Bandwidth lives in config, never in business logic."""

    name: str
    download_mbps: float
    upload_mbps: float
    latency_ms: float

    @property
    def download_bps(self) -> float:
        """CDP wants bytes/second."""
        return self.download_mbps * 1_000_000 / 8

    @property
    def upload_bps(self) -> float:
        return self.upload_mbps * 1_000_000 / 8


class ProfileStatus(str, Enum):
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"        # budget exceeded; completed iterations retained
    UNAVAILABLE = "UNAVAILABLE"  # throttling unsupported on this browser
    FAILED = "FAILED"


class PerformanceMeasurement(BaseModel):
    """One page load under one profile. Missing metrics stay None, never zero."""

    assessment_id: str
    network_profile: str
    iteration: int
    succeeded: bool = False
    error: str | None = None

    # navigation timing (ms)
    dns_time: float | None = None
    tcp_time: float | None = None
    tls_time: float | None = None
    ttfb: float | None = None
    dom_content_loaded: float | None = None
    page_load_time: float | None = None

    # lab vitals — PERF-01 asks for field p75, which we cannot supply
    lcp: float | None = None
    cls: float | None = None
    inp: None = None           # not measurable without real user input

    # network volume
    transferred_bytes: int = 0
    request_count: int = 0
    response_count: int = 0
    failed_requests: int = 0
    redirect_count: int = 0

    #: Metric fields that StatisticsTool aggregates. ClassVar, not a field.
    METRICS: ClassVar[tuple[str, ...]] = (
        "dns_time", "tcp_time", "tls_time", "ttfb",
        "dom_content_loaded", "page_load_time", "lcp", "cls",
        "transferred_bytes", "request_count", "failed_requests",
    )


class PerformanceStatistics(BaseModel):
    """Deterministic reduction of raw measurements for one profile+metric."""

    assessment_id: str
    network_profile: str
    metric: str
    n: int                       # sample size — always reported beside p95
    mean: float | None = None
    median: float | None = None
    min: float | None = None
    max: float | None = None
    stddev: float | None = None  # sample stddev (n-1); None when n < 2
    p95: float | None = None
    success_rate: float = 0.0
    failure_rate: float = 0.0


class ProfileOutcome(BaseModel):
    """Per-profile roll-up, so a partial profile reads as partial."""

    name: str
    status: ProfileStatus
    iterations_requested: int
    iterations_completed: int
    note: str | None = None
