"""Run manager: one assessment per request, streamed while it happens.

This is the same pipeline app/main.py drives from the CLI. It is deliberately
not a reimplementation — it builds the identical state dict and invokes the
identical compiled graph, so the API can never drift into evaluating rules
differently from the command line. The only additions are a progress feed and
a place to keep the finished report.

Safety properties carry over unchanged because they are structural: the
TrafficBudget still caps and attributes every request, the browser is still
closed in a `finally` on every path, and the API adds no code path that
performs a browser action outside AssessmentPlan.actions.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app import observability
from app.api.progress import ORDER, STAGES, Progress, Stage
from app.api.serializers import to_report
from app.config.settings import load_settings
from app.graph.state import AssessmentState
from app.graph.workflow import build_workflow
from app.llm.qwen import build_provider
from app.models.assessment import AssessmentStatus
from app.repositories.base import build_repository
from app.safety.limits import TrafficBudget
from app.tools.browser import BrowserSession

log = logging.getLogger("assessment.api")

#: The graph emits full state snapshots; a node is "done" once the key it
#: writes is present. Keyed on state rather than on node names so this stays
#: correct regardless of the LangGraph streaming API version, and correct for
#: the EVALUATE/PERFORMANCE fork whose lanes finish in either order.
_PROBES: list[tuple[str, str]] = [
    ("load_rules", "rules"),
    ("plan", "plan"),
    ("collect_evidence", "evidence"),
    ("evaluate", "security_results"),
    ("performance", "profile_outcomes"),
    ("aggregate", "tally"),
    ("persist", "report_path"),
]

HEARTBEAT_SECONDS = 1.2


class InvalidTarget(ValueError):
    """The URL is not a target this system will accept."""


def validate_target(url: str) -> str:
    """Same check as the CLI's exit code 2, raised instead of returned."""
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise InvalidTarget(
            "target must be an absolute http:// or https:// URL")
    return parsed.geturl()


@dataclass
class RunOptions:
    """The CLI flags the API exposes. Defaults match the CLI's defaults."""

    families: list[str] | None = None
    network_profiles: list[str] | None = None
    iterations: int | None = None
    skip_performance: bool = False
    no_llm: bool = False

    def overrides(self) -> dict:
        o: dict = {}
        if self.network_profiles:
            o.setdefault("performance", {})["profiles"] = self.network_profiles
        if self.iterations:
            o.setdefault("performance", {})["iterations"] = self.iterations
        if self.skip_performance:
            o.setdefault("performance", {})["enabled"] = False
        return o


@dataclass
class Run:
    """One assessment, its live progress feed and its finished report."""

    id: str
    target: str
    options: RunOptions
    created_at: float = field(default_factory=time.time)

    status: AssessmentStatus = AssessmentStatus.INITIALIZING
    report: dict[str, Any] | None = None
    error: str | None = None

    budget: TrafficBudget | None = None
    task: asyncio.Task | None = None

    _history: list[dict] = field(default_factory=list)
    _subscribers: set[asyncio.Queue] = field(default_factory=set)
    _stage: Stage | None = None
    _pct: float = 0.0
    _reached: int = -1          # index into ORDER; keeps progress monotonic

    # ---------------------------------------------------------------- feed
    def publish(self, progress: Progress) -> None:
        event = progress.as_dict()
        self._history.append(event)
        for q in list(self._subscribers):
            q.put_nowait(event)

    def subscribe(self) -> asyncio.Queue:
        """Attach a listener, replaying everything it missed.

        The browser POSTs, then opens the stream — by which time the run has
        usually already emitted events. Without replay the first stage would
        be lost to that race.
        """
        q: asyncio.Queue = asyncio.Queue()
        for event in self._history:
            q.put_nowait(event)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    @property
    def requests_made(self) -> int:
        return self.budget.total_requests if self.budget else 0

    def _emit(self, detail: str = "") -> None:
        stage = self._stage
        self.publish(Progress(
            status=(stage.status.value if stage else self.status.value),
            pct=round(self._pct, 1),
            label=(stage.code if stage else "STARTING"),
            detail=detail,
            requests=self.requests_made))

    def enter(self, node: str, detail: str = "") -> None:
        """Advance to a stage, never backwards."""
        idx = ORDER.index(node)
        if idx <= self._reached:
            return
        self._reached = idx
        self._stage = STAGES[node]
        self._pct = max(self._pct, self._stage.start_pct)
        self.status = self._stage.status
        self._emit(detail)

    def ease(self) -> None:
        """Nudge the bar toward the current stage's ceiling. Cosmetic only."""
        if self._stage is None:
            return
        gap = self._stage.end_pct - 0.5 - self._pct
        if gap > 0.1:
            self._pct += gap * 0.12
            self._emit(self._history[-1].get("detail", "") if self._history else "")

    def finish(self, status: AssessmentStatus, detail: str) -> None:
        self.status = status
        self._pct = 100.0
        self.publish(Progress(status=status.value, pct=100.0,
                              label="ASSESSMENT COMPLETE" if status in (
                                  AssessmentStatus.COMPLETED,
                                  AssessmentStatus.PARTIAL) else status.value,
                              detail=detail, requests=self.requests_made))


def _detail(node: str, state: dict) -> str:
    """A human sentence for a stage, built from what the stage produced."""
    match node:
        case "load_rules":
            return (f"{len(state.get('rules', []))} controls parsed from "
                    f"{len(state.get('families', []))} families.")
        case "plan":
            plan = state.get("plan")
            if plan is None:
                return ""
            return (f"{len(plan.evaluable_rules)} controls have a passive "
                    f"evidence route · {plan.estimated_requests} requests planned.")
        case "collect_evidence":
            ev = state.get("evidence")
            if ev is None:
                return ""
            return (f"{len(ev.collectors_run)} collectors ran on one "
                    f"instrumented navigation.")
        case "evaluate":
            results = state.get("security_results", [])
            decided = sum(1 for r in results
                          if r.native_result.value in ("PASS", "FAIL"))
            return f"{decided} of {len(results)} controls decided. Zero traffic."
        case "performance":
            outcomes = state.get("profile_outcomes", [])
            done = sum(1 for o in outcomes if o.status.value == "COMPLETED")
            return f"{done} of {len(outcomes)} network profiles completed."
        case "aggregate":
            tally = state.get("tally")
            if tally is None:
                return ""
            return (f"{tally.decided} of {tally.total} controls decided "
                    f"({tally.coverage_pct}% coverage).")
        case "persist":
            return f"Report written to {state.get('report_path') or '(failed)'}."
    return ""


class RunManager:
    """Owns every in-flight and finished run for the life of the process."""

    def __init__(self, *, config: str = "config.yaml",
                 policy: str = "policy.yaml", max_concurrent: int = 2,
                 keep: int = 50) -> None:
        self.config = config
        self.policy = policy
        self.keep = keep
        self._runs: dict[str, Run] = {}
        self._gate = asyncio.Semaphore(max_concurrent)

    # ------------------------------------------------------------- lookup
    def get(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    def list(self) -> list[Run]:
        return sorted(self._runs.values(), key=lambda r: r.created_at,
                      reverse=True)

    def _evict(self) -> None:
        """Bound memory. Only finished runs are ever evicted."""
        finished = [r for r in self.list() if r.status.is_terminal]
        for r in finished[self.keep:]:
            self._runs.pop(r.id, None)

    # -------------------------------------------------------------- start
    def start(self, url: str, options: RunOptions | None = None) -> Run:
        target = validate_target(url)
        run = Run(id=uuid.uuid4().hex[:16], target=target,
                  options=options or RunOptions())
        self._runs[run.id] = run
        run.task = asyncio.create_task(self._execute(run))
        self._evict()
        return run

    async def cancel(self, run_id: str) -> bool:
        run = self._runs.get(run_id)
        if run is None or run.task is None or run.task.done():
            return False
        run.task.cancel()
        return True

    # ------------------------------------------------------------ execute
    async def _execute(self, run: Run) -> None:
        """Drive the graph. Mirrors app/main.py::run_assessment."""
        heartbeat: asyncio.Task | None = None
        session: BrowserSession | None = None
        #: The run's logging scope. Explicit lifecycle, unwound in `finally`
        #: on every path — the same discipline the browser session follows.
        log_scope = None
        started = time.monotonic()

        try:
            async with self._gate:
                settings = load_settings(self.config, self.policy,
                                         run.options.overrides())
                artifact_dir = settings.artifact_dir(run.id)
                artifact_dir.mkdir(parents=True, exist_ok=True)

                # Per-run log, isolated by a contextvar rather than by hope.
                # The previous approach attached this handler to the root
                # logger unfiltered, so with two runs in flight — which the
                # semaphore explicitly allows — each run's file collected the
                # other's lines. run_scope binds the run to this task and
                # admits only records emitted inside it.
                log_scope = observability.run_scope(
                    run.id, kind="assessment", target=run.target,
                    log_path=settings.log_path(run.id))
                log_scope.__enter__()

                observability.event(
                    log, "run_started", f"run {run.id} starting — target {run.target}",
                    target=run.target, families=list(run.families or []),
                    skip_performance=bool(run.skip_performance))

                provider = build_provider(settings.llm)
                llm_available = False
                if not run.options.no_llm:
                    try:
                        llm_available, msg = await provider.health_check()
                        log.info("LLM: %s", msg)
                    except Exception as exc:                    # noqa: BLE001
                        log.warning("LLM unavailable: %s", exc)
                    if not llm_available and settings.llm.required:
                        raise RuntimeError(
                            "llm.required is true but no model is available")

                run.budget = TrafficBudget(
                    max_navigations=settings.assessment.max_navigation_count,
                    max_pages=settings.assessment.max_pages,
                    timeout_seconds=settings.assessment.timeout_seconds)

                session = BrowserSession(settings, run.budget, artifact_dir)
                repository = build_repository(settings, run.id)
                use_agent = llm_available and not run.options.no_llm
                workflow = build_workflow(agentic=use_agent)

                state: AssessmentState = {
                    "assessment_id": run.id,
                    "target_url": run.target,
                    "settings": settings,
                    "status": AssessmentStatus.INITIALIZING,
                    "started_at": time.monotonic(),
                    "provider": provider,
                    "llm_available": llm_available,
                    "session": session,
                    "budget": run.budget,
                    "repository": repository,
                    "errors": [],
                }

                run.publish(Progress(
                    status=AssessmentStatus.PLANNING.value, pct=1.0,
                    label="STARTING", detail="Loading the rule pack.",
                    requests=0))
                # The graph reports the two forked lanes itself; their
                # completions are invisible in state snapshots.
                state["progress"] = run.enter
                heartbeat = asyncio.create_task(self._heartbeat(run))

                await session.start()
                final: dict = {}
                try:
                    async for snapshot in workflow.astream(
                            state, {"recursion_limit": 50},
                            stream_mode="values"):
                        final = snapshot
                        for node, key in _PROBES:
                            if snapshot.get(key) is not None:
                                run.enter(node, _detail(node, snapshot))
                finally:
                    await session.close()
                    session = None

                if run.options.families:
                    wanted = {f.upper() for f in run.options.families}
                    final["security_results"] = [
                        r for r in final.get("security_results", [])
                        if r.category in wanted]

                duration = time.monotonic() - started
                run.report = to_report(final, duration_seconds=duration)
                status = final.get("status", AssessmentStatus.FAILED)
                run.finish(status, run.report.get("summary_text", "")[:280]
                           or _detail("aggregate", final))
                log.info("run %s finished: %s", run.id, status.value)

        except asyncio.CancelledError:
            run.error = "cancelled by the client"
            run.finish(AssessmentStatus.FAILED, run.error)
            log.warning("run %s cancelled", run.id)
            raise
        except Exception as exc:                                # noqa: BLE001
            run.error = f"{type(exc).__name__}: {exc}"
            run.finish(AssessmentStatus.FAILED, run.error)
            log.exception("run %s failed", run.id)
        finally:
            if heartbeat is not None:
                heartbeat.cancel()
            if session is not None:
                await session.close()
            if log_scope is not None:
                log_scope.__exit__(None, None, None)

    async def _heartbeat(self, run: Run) -> None:
        """Keep the SSE connection warm and the request counter live."""
        try:
            while not run.status.is_terminal:
                await asyncio.sleep(HEARTBEAT_SECONDS)
                run.ease()
        except asyncio.CancelledError:
            pass
