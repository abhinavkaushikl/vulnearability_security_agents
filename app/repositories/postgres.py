"""PostgresRepository — v2 persistence.

Deliberately a thin, unfinished implementation: the point of this file is that
the SEAM exists and the migration touches nothing else. The four sheets map
one-to-one onto four tables keyed on assessment_id.

To activate: `pip install asyncpg`, set storage.type: postgres and a DSN in
config.yaml, then fill in the marked sections. No agent, node or tool changes.
"""
from __future__ import annotations

import logging

from app.models.assessment import Assessment
from app.models.performance import PerformanceMeasurement, PerformanceStatistics
from app.models.results import SecurityResult

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS assessments (
    assessment_id     TEXT PRIMARY KEY,
    target_url        TEXT NOT NULL,
    timestamp         TIMESTAMPTZ NOT NULL,
    status            TEXT NOT NULL,
    total_rules       INT, passed INT, failed INT,
    not_applicable    INT, unknown INT,
    coverage_pct      REAL,
    pack_version      TEXT, browser_version TEXT, llm_model TEXT,
    duration_seconds  REAL, blocked_reason TEXT
);
CREATE TABLE IF NOT EXISTS security_results (
    id                BIGSERIAL PRIMARY KEY,
    assessment_id     TEXT NOT NULL REFERENCES assessments(assessment_id)
                      ON DELETE CASCADE,
    rule_id           TEXT NOT NULL, rule_name TEXT, category TEXT,
    result            TEXT NOT NULL, native_result TEXT NOT NULL,
    confidence        REAL, evidence TEXT, observed_value TEXT,
    source_of_evidence TEXT, unknown_reason TEXT,
    severity          TEXT, automation_tier TEXT, evaluated_by TEXT,
    source_file       TEXT, source_line INT, timestamp TIMESTAMPTZ,
    UNIQUE (assessment_id, rule_id)
);
CREATE TABLE IF NOT EXISTS performance_results (
    id                BIGSERIAL PRIMARY KEY,
    assessment_id     TEXT NOT NULL REFERENCES assessments(assessment_id)
                      ON DELETE CASCADE,
    network_profile   TEXT NOT NULL, iteration INT NOT NULL,
    dns_time REAL, tcp_time REAL, tls_time REAL, ttfb REAL,
    dom_content_loaded REAL, page_load_time REAL,
    transferred_bytes BIGINT, request_count INT, failed_requests INT,
    lcp REAL, cls REAL, redirect_count INT, succeeded BOOL, error TEXT
);
CREATE TABLE IF NOT EXISTS performance_statistics (
    id                BIGSERIAL PRIMARY KEY,
    assessment_id     TEXT NOT NULL REFERENCES assessments(assessment_id)
                      ON DELETE CASCADE,
    network_profile   TEXT NOT NULL, metric TEXT NOT NULL,
    mean REAL, median REAL, min REAL, max REAL, stddev REAL, p95 REAL,
    n INT, success_rate REAL, failure_rate REAL
);
CREATE INDEX IF NOT EXISTS ix_sec_assessment ON security_results(assessment_id);
CREATE INDEX IF NOT EXISTS ix_sec_result     ON security_results(native_result);
CREATE INDEX IF NOT EXISTS ix_perf_assessment ON performance_results(assessment_id);
"""


class PostgresRepository:
    """Implements the same Protocol as ExcelRepository."""

    def __init__(self, dsn: str | None):
        if not dsn:
            raise ValueError("storage.postgres_dsn is required for the "
                             "postgres backend")
        self.dsn = dsn
        self._assessment: Assessment | None = None
        self._security: list[SecurityResult] = []
        self._performance: list[PerformanceMeasurement] = []
        self._stats: list[PerformanceStatistics] = []
        self.summary_text = ""

    async def save_assessment(self, assessment: Assessment) -> None:
        self._assessment = assessment

    async def save_security_results(self, results: list[SecurityResult]) -> None:
        self._security.extend(results)

    async def save_performance_results(
            self, measurements: list[PerformanceMeasurement]) -> None:
        self._performance.extend(measurements)

    async def save_statistics(self, stats: list[PerformanceStatistics]) -> None:
        self._stats.extend(stats)

    async def commit(self) -> str:
        raise NotImplementedError(
            "PostgresRepository is a schema-complete stub. The interface, "
            "table schema and call sites are all in place; wire asyncpg here "
            "to activate. Excel remains the default backend.")
