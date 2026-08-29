"""Performance Agent.

Profiles run STRICTLY IN SERIES. This is the one place where the obvious
parallelism is actively wrong: all profiles share one physical uplink, so a
3G-throttled context running beside a fast context measures contention rather
than the profile — and it quadruples simultaneous load on the target.

Each profile gets its own budget. Exceeding it retains the completed
iterations and marks the profile PARTIAL. A slow target degrades the report;
it never aborts the run.
"""
from __future__ import annotations

import asyncio
import logging
import time

from app.config.settings import Settings
from app.models.performance import (PerformanceMeasurement, ProfileOutcome,
                                    ProfileStatus)
from app.safety.limits import BudgetExceeded, TrafficBudget
from app.tools import inspection
from app.tools.browser import BrowserSession
from app.tools.performance import ThrottleUnavailable, measure_page_load

log = logging.getLogger(__name__)


class PerformanceAgent:
    def __init__(self, session: BrowserSession, settings: Settings,
                 budget: TrafficBudget):
        self.session = session
        self.settings = settings
        self.budget = budget

    async def run(self, *, assessment_id: str, target_url: str
                  ) -> tuple[list[PerformanceMeasurement], list[ProfileOutcome]]:
        cfg = self.settings.performance
        measurements: list[PerformanceMeasurement] = []
        outcomes: list[ProfileOutcome] = []
        scope_host = inspection.registrable_host(target_url)

        if not self.settings.browser.supports_throttling:
            reason = (f"{self.settings.browser.type} cannot emulate network "
                      f"conditions; throttled profiles were not measured")
            log.warning(reason)
            return [], [ProfileOutcome(
                name=p.name, status=ProfileStatus.UNAVAILABLE,
                iterations_requested=cfg.iterations, iterations_completed=0,
                note=reason) for p in self.settings.active_profiles]

        for profile in self.settings.active_profiles:
            started = time.monotonic()
            completed = 0
            status = ProfileStatus.COMPLETED
            note = None

            # Fresh context per profile: a warm cache would make the slow
            # profiles fiction.
            async with self.session.context(label=f"perf:{profile.name}") as ctx:
                for i in range(1, cfg.iterations + 1):
                    elapsed = time.monotonic() - started
                    if elapsed > cfg.per_profile_budget_seconds:
                        status = ProfileStatus.PARTIAL
                        note = (f"per-profile budget of "
                                f"{cfg.per_profile_budget_seconds}s exceeded after "
                                f"{completed} of {cfg.iterations} iterations")
                        log.warning("profile %s: %s", profile.name, note)
                        break
                    try:
                        m = await measure_page_load(
                            session=self.session, context=ctx, url=target_url,
                            profile=profile, iteration=i,
                            assessment_id=assessment_id, scope_host=scope_host)
                    except ThrottleUnavailable as exc:
                        status = ProfileStatus.UNAVAILABLE
                        note = str(exc)
                        log.warning("profile %s unavailable: %s", profile.name, exc)
                        break
                    except BudgetExceeded as exc:
                        status = ProfileStatus.PARTIAL
                        note = f"traffic budget exhausted: {exc}"
                        log.warning("profile %s: %s", profile.name, note)
                        break

                    measurements.append(m)
                    if m.succeeded:
                        completed += 1

                    if i < cfg.iterations and cfg.cooldown_seconds > 0:
                        await asyncio.sleep(cfg.cooldown_seconds)

            if completed == 0 and status is ProfileStatus.COMPLETED:
                status = ProfileStatus.FAILED
                note = "no iteration produced a usable measurement"

            outcomes.append(ProfileOutcome(
                name=profile.name, status=status,
                iterations_requested=cfg.iterations,
                iterations_completed=completed, note=note))
            log.info("profile %s: %s (%d/%d iterations)",
                     profile.name, status.value, completed, cfg.iterations)

        return measurements, outcomes
