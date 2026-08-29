"""Traffic budget.

Every outbound action is counted and capped. Exhausting a budget stops the
assessment cleanly and marks the remaining evidence unavailable — it never
degrades into "just one more request".
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


class BudgetExceeded(Exception):
    """Raised when a hard limit is reached. Caught by the graph, not fatal."""


@dataclass
class TrafficBudget:
    """Counts every navigation, auxiliary request and page opened."""

    max_navigations: int = 20
    max_pages: int = 10
    timeout_seconds: float = 900.0

    navigations: int = 0
    aux_requests: int = 0
    pages_opened: int = 0
    started_at: float = field(default_factory=time.monotonic)
    _log: list[str] = field(default_factory=list)

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started_at

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.timeout_seconds - self.elapsed)

    def check_time(self) -> None:
        if self.elapsed > self.timeout_seconds:
            raise BudgetExceeded(
                f"assessment timeout of {self.timeout_seconds}s exceeded")

    def navigate(self, url: str, reason: str) -> None:
        """Record one navigation. `reason` is mandatory and is logged.

        Every browser action must justify itself against a control. There is
        no unattributed traffic.
        """
        self.check_time()
        if self.navigations >= self.max_navigations:
            raise BudgetExceeded(
                f"navigation budget of {self.max_navigations} exhausted")
        self.navigations += 1
        self._log.append(f"nav#{self.navigations} {url} :: {reason}")
        log.info("navigate [%d/%d] %s — %s",
                 self.navigations, self.max_navigations, url, reason)

    def aux(self, url: str, reason: str) -> None:
        """Record one auxiliary (non-navigation) request."""
        self.check_time()
        self.aux_requests += 1
        self._log.append(f"aux#{self.aux_requests} {url} :: {reason}")
        log.info("aux request %s — %s", url, reason)

    def open_page(self) -> None:
        if self.pages_opened >= self.max_pages:
            raise BudgetExceeded(f"page budget of {self.max_pages} exhausted")
        self.pages_opened += 1

    @property
    def total_requests(self) -> int:
        return self.navigations + self.aux_requests

    def report(self) -> list[str]:
        """The full attributed traffic log, for the assessment record."""
        return list(self._log)
