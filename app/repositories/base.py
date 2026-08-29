"""AssessmentRepository — the persistence seam.

No agent, node or tool imports openpyxl or asyncpg. They call these four
methods. Swapping Excel for PostgreSQL replaces one class and one config
line; the LangGraph workflow does not change.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.models.assessment import Assessment, AssessmentReport
from app.models.performance import PerformanceMeasurement, PerformanceStatistics
from app.models.results import SecurityResult


@runtime_checkable
class AssessmentRepository(Protocol):
    async def save_assessment(self, assessment: Assessment) -> None: ...
    async def save_security_results(self, results: list[SecurityResult]) -> None: ...
    async def save_performance_results(
        self, measurements: list[PerformanceMeasurement]) -> None: ...
    async def save_statistics(self, stats: list[PerformanceStatistics]) -> None: ...
    async def commit(self) -> str: ...


def build_repository(settings, assessment_id: str) -> AssessmentRepository:
    """Factory. `storage.type` selects the backend."""
    kind = settings.storage.type.lower()
    if kind == "excel":
        from app.repositories.excel import ExcelRepository
        return ExcelRepository(settings.excel_path(assessment_id))
    if kind in ("postgres", "postgresql"):
        from app.repositories.postgres import PostgresRepository
        return PostgresRepository(settings.storage.postgres_dsn)
    raise ValueError(f"unknown storage backend: {settings.storage.type!r}")
