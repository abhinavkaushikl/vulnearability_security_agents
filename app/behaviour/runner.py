"""Session runner — one behaviour session, driven the same way from anywhere.

The CLI and the HTTP API both call `run_session`, for the same reason
`app/api/runner.py` invokes the security graph rather than reimplementing it:
two entry points that build the pipeline separately will eventually build it
differently, and the difference will be a safety property.

The traffic budget is the shared one. A behaviour session and a security
assessment against the same target draw from the same cap, so running both
cannot exceed what either alone was allowed to spend.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from app.behaviour.agent import UserBehaviourAgent
from app.behaviour.measure import MeasurementEngine
from app.behaviour.models import AgentState, BehaviourReport
from app.behaviour.observer import WebsiteObserver
from app.config.settings import Settings, load_settings
from app.llm.qwen import build_provider
from app.safety.limits import TrafficBudget
from app.tools.browser import BrowserSession

log = logging.getLogger("behaviour")


class InvalidTarget(ValueError):
    """The URL is not a target this system will accept."""


def validate_target(url: str) -> str:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise InvalidTarget("target must be an absolute http:// or https:// URL")
    return parsed.geturl()


@dataclass
class SessionOptions:
    """What a caller may vary. Everything else comes from config.yaml."""

    max_actions: int | None = None
    max_steps_per_journey: int | None = None
    pacing: float | None = None
    no_llm: bool = False
    llm_decides_steps: bool | None = None
    headed: bool = False
    screenshots: bool | None = None
    seed: int | None = None

    def overrides(self) -> dict:
        b: dict = {}
        if self.max_actions is not None:
            b["max_actions"] = self.max_actions
        if self.max_steps_per_journey is not None:
            b["max_steps_per_journey"] = self.max_steps_per_journey
        if self.pacing is not None:
            b["pacing"] = self.pacing
        if self.screenshots is not None:
            b["screenshots"] = self.screenshots
        if self.seed is not None:
            b["seed"] = self.seed
        if self.llm_decides_steps is not None:
            b["llm_decides_steps"] = self.llm_decides_steps
        out: dict = {}
        if b:
            out["behaviour"] = b
        if self.headed:
            out["browser"] = {"headless": False}
        return out


async def run_session(target: str, *, session_id: str | None = None,
                      config: str = "config.yaml", policy: str = "policy.yaml",
                      options: SessionOptions | None = None,
                      progress=None,
                      settings: Settings | None = None,
                      budget: TrafficBudget | None = None,
                      session: BrowserSession | None = None
                      ) -> BehaviourReport:
    """Run one session and return its report.

    `settings`, `budget` and `session` may be supplied by a caller that
    already owns them — that is how a combined security + behaviour run keeps
    one browser and one budget rather than two of each.
    """
    options = options or SessionOptions()
    target = validate_target(target)
    sid = session_id or uuid.uuid4().hex[:16]

    owns_session = session is None
    settings = settings or load_settings(config, policy, options.overrides())
    cfg = settings.behaviour

    artifact_dir = settings.artifact_dir(sid)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    provider = build_provider(settings.llm)
    llm_available = False
    if not options.no_llm:
        try:
            llm_available, msg = await provider.health_check()
            log.info("LLM: %s", msg)
        except Exception as exc:                                # noqa: BLE001
            log.warning("LLM unavailable, running on heuristics: %s", exc)

    if budget is None:
        budget = TrafficBudget(
            max_navigations=cfg.max_navigations,
            max_pages=settings.assessment.max_pages,
            timeout_seconds=cfg.timeout_seconds)

    if session is None:
        session = BrowserSession(settings, budget, artifact_dir)
        await session.start()

    agent = UserBehaviourAgent(
        session=session, budget=budget, settings=settings, provider=provider,
        target=target, session_id=sid, artifact_dir=artifact_dir,
        progress=progress, use_llm=llm_available and not options.no_llm,
        max_actions=cfg.max_actions,
        max_steps_per_journey=cfg.max_steps_per_journey,
        pacing=cfg.pacing, screenshots=cfg.screenshots, seed=cfg.seed,
        llm_decides_steps=cfg.llm_decides_steps,
        llm_call_timeout=cfg.llm_call_timeout_seconds)
    agent.observer = WebsiteObserver(
        max_elements=cfg.max_elements,
        keyboard_walk_steps=cfg.keyboard_walk_steps)
    agent.engine = MeasurementEngine(
        quiet_ms=cfg.settle_quiet_ms, max_settle_ms=cfg.settle_max_ms)

    try:
        report = await agent.run()
        # The prose call runs after the browser work, on a finished report.
        await agent.write_summary(report)
        return report
    finally:
        if owns_session:
            await session.close()
