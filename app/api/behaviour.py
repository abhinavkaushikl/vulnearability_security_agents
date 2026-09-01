"""HTTP surface for the User Behaviour Agent.

    POST   /behaviour              -> {"session_id": ...}
    GET    /behaviour/{id}/stream  -> text/event-stream of BehaviourProgress
    GET    /behaviour/{id}         -> the UX report (409 while still running)
    DELETE /behaviour/{id}         -> cancel
    GET    /behaviour              -> list

Mounted alongside `/analyze` by `create_app()`. It is a separate router
rather than an extra mode on the existing one: the two produce different
reports, answer different questions and have different budgets, and folding
them together would eventually let a change to one alter the other.

Like `/analyze`, this is a shell. It validates a URL and calls the same
`run_session` the CLI calls, so the API cannot drift into running the agent
differently. Binding stays on 127.0.0.1 for the reason CLAUDE.md §5.8 gives:
exposing it publicly would let anyone point an autonomous browser agent at
anyone, which is the authorization boundary undone by deployment.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.behaviour.models import AgentState, BehaviourProgress
from app.behaviour.runner import InvalidTarget, SessionOptions, run_session
from app.behaviour.serializers import to_json
from app.safety.limits import TrafficBudget

log = logging.getLogger("behaviour.api")

_TERMINAL = {AgentState.COMPLETED.value, AgentState.BLOCKED.value,
             AgentState.FAILED.value}


class BehaviourRequest(BaseModel):
    """The browser sends only `url`; the rest mirror the CLI's flags."""

    url: str
    max_actions: int | None = Field(default=None, ge=4, le=200)
    max_steps_per_journey: int | None = Field(default=None, ge=2, le=25)
    pacing: float | None = Field(default=None, ge=0.0, le=3.0)
    no_llm: bool = False
    #: Ask the model for every step rather than only for the plan. Off by
    #: default for the reason BehaviourConfig.llm_decides_steps gives: it adds
    #: one model round trip per action.
    llm_decides_steps: bool | None = None
    seed: int | None = None


@dataclass
class Session:
    """One behaviour session, its live feed and its finished report."""

    id: str
    target: str
    options: SessionOptions
    created_at: float = field(default_factory=time.time)

    state: AgentState = AgentState.DISCOVERING
    report: dict[str, Any] | None = None
    error: str | None = None
    budget: TrafficBudget | None = None
    task: asyncio.Task | None = None

    _history: list[dict] = field(default_factory=list)
    _subscribers: set[asyncio.Queue] = field(default_factory=set)

    def publish(self, event: dict) -> None:
        self._history.append(event)
        # The thought stream is the interesting part of this feed and it is
        # append-only, so a late subscriber must be able to catch up. The
        # history is bounded to keep a long session from growing without limit.
        if len(self._history) > 400:
            del self._history[:100]
        for q in list(self._subscribers):
            q.put_nowait(event)

    def subscribe(self) -> asyncio.Queue:
        """Attach a listener, replaying what it missed.

        The browser POSTs and then opens the stream; without replay the first
        thoughts — the ones that explain what the agent decided the site was —
        would be lost to that race.
        """
        q: asyncio.Queue = asyncio.Queue()
        for event in self._history:
            q.put_nowait(event)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    @property
    def terminal(self) -> bool:
        return self.state.is_terminal


class BehaviourManager:
    """Owns every in-flight and finished session for the life of the process."""

    def __init__(self, *, config: str = "config.yaml",
                 policy: str = "policy.yaml", max_concurrent: int = 2,
                 keep: int = 50) -> None:
        self.config = config
        self.policy = policy
        self.keep = keep
        self._sessions: dict[str, Session] = {}
        self._gate = asyncio.Semaphore(max_concurrent)

    def get(self, sid: str) -> Session | None:
        return self._sessions.get(sid)

    def list(self) -> list[Session]:
        return sorted(self._sessions.values(), key=lambda s: s.created_at,
                      reverse=True)

    def _evict(self) -> None:
        finished = [s for s in self.list() if s.terminal]
        for s in finished[self.keep:]:
            self._sessions.pop(s.id, None)

    def start(self, url: str, options: SessionOptions | None = None) -> Session:
        from app.behaviour.runner import validate_target
        target = validate_target(url)
        s = Session(id=uuid.uuid4().hex[:16], target=target,
                    options=options or SessionOptions())
        self._sessions[s.id] = s
        s.task = asyncio.create_task(self._execute(s))
        self._evict()
        return s

    async def cancel(self, sid: str) -> bool:
        s = self._sessions.get(sid)
        if s is None or s.task is None or s.task.done():
            return False
        s.task.cancel()
        return True

    async def _execute(self, s: Session) -> None:
        handler: logging.Handler | None = None
        try:
            async with self._gate:
                from app.config.settings import load_settings
                settings = load_settings(self.config, self.policy,
                                         s.options.overrides())
                log_path = settings.log_path(s.id)
                if log_path:
                    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
                    handler = logging.FileHandler(log_path)
                    handler.setFormatter(logging.Formatter(
                        "%(asctime)s %(levelname)-7s %(name)-24s %(message)s"))
                    logging.getLogger().addHandler(handler)

                s.budget = TrafficBudget(
                    max_navigations=settings.behaviour.max_navigations,
                    max_pages=settings.assessment.max_pages,
                    timeout_seconds=settings.behaviour.timeout_seconds)

                def sink(p: BehaviourProgress) -> None:
                    s.state = p.state
                    event = p.model_dump(mode="json")
                    # The counter on screen is read from the budget, so it is
                    # the number of requests the target actually received.
                    event["requests"] = (s.budget.total_requests
                                         if s.budget else 0)
                    s.publish(event)

                log.info("behaviour session %s starting — %s", s.id, s.target)
                report = await run_session(
                    s.target, session_id=s.id, config=self.config,
                    policy=self.policy, options=s.options, progress=sink,
                    settings=settings, budget=s.budget)

                s.report = to_json(report)
                s.state = report.state
                s.publish({
                    "state": report.state.value, "pct": 100.0,
                    "objective": "Mission complete",
                    "current_action": "",
                    "page_url": report.target,
                    "pages_visited": report.pages_explored,
                    "interactions": report.interactions_total,
                    "actions_dispatched": len(report.actions),
                    "avg_response_ms": report.avg_response_ms,
                    "requests": report.requests_made,
                    "journeys_done": report.journeys_run,
                    "journeys_total": len(report.journeys),
                    "thought": None, "node": None, "map_nodes": None,
                })
                log.info("behaviour session %s finished: %s", s.id,
                         report.state.value)

        except asyncio.CancelledError:
            s.error = "cancelled by the client"
            s.state = AgentState.FAILED
            s.publish({"state": s.state.value, "pct": 100.0,
                       "objective": "Cancelled", "current_action": "",
                       "page_url": s.target, "pages_visited": 0,
                       "interactions": 0, "actions_dispatched": 0,
                       "avg_response_ms": None,
                       "requests": s.budget.total_requests if s.budget else 0,
                       "journeys_done": 0, "journeys_total": 0,
                       "thought": None, "node": None, "map_nodes": None})
            raise
        except Exception as exc:                                # noqa: BLE001
            s.error = f"{type(exc).__name__}: {exc}"
            s.state = AgentState.FAILED
            log.exception("behaviour session %s failed", s.id)
            s.publish({"state": s.state.value, "pct": 100.0,
                       "objective": "Session failed",
                       "current_action": s.error[:160],
                       "page_url": s.target, "pages_visited": 0,
                       "interactions": 0, "actions_dispatched": 0,
                       "avg_response_ms": None,
                       "requests": s.budget.total_requests if s.budget else 0,
                       "journeys_done": 0, "journeys_total": 0,
                       "thought": None, "node": None, "map_nodes": None})
        finally:
            if handler is not None:
                logging.getLogger().removeHandler(handler)
                handler.close()


def build_router(manager: BehaviourManager) -> APIRouter:
    router = APIRouter(prefix="/behaviour", tags=["behaviour"])

    @router.post("")
    async def start(req: BehaviourRequest) -> dict:
        try:
            s = manager.start(req.url, SessionOptions(
                max_actions=req.max_actions,
                max_steps_per_journey=req.max_steps_per_journey,
                pacing=req.pacing, no_llm=req.no_llm, seed=req.seed,
                llm_decides_steps=req.llm_decides_steps))
        except InvalidTarget as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"session_id": s.id, "target": s.target, "state": s.state.value}

    @router.get("/{sid}/stream")
    async def stream(sid: str) -> StreamingResponse:
        s = manager.get(sid)
        if s is None:
            raise HTTPException(status_code=404, detail="unknown session")

        async def events():
            q = s.subscribe()
            try:
                while True:
                    try:
                        event = await asyncio.wait_for(q.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
                        continue
                    yield f"data: {json.dumps(event, default=str)}\n\n"
                    if event.get("state") in _TERMINAL:
                        return
            finally:
                s.unsubscribe(q)

        return StreamingResponse(
            events(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive",
                     "X-Accel-Buffering": "no"})

    @router.get("/{sid}")
    async def report(sid: str) -> dict:
        s = manager.get(sid)
        if s is None:
            raise HTTPException(status_code=404, detail="unknown session")
        if s.report is None:
            if s.error:
                raise HTTPException(status_code=500, detail=s.error)
            raise HTTPException(
                status_code=409,
                detail=f"the session is still running ({s.state.value})")
        return s.report

    @router.delete("/{sid}")
    async def cancel(sid: str) -> dict:
        if not await manager.cancel(sid):
            raise HTTPException(status_code=404,
                                detail="unknown or already finished")
        return {"session_id": sid, "cancelled": True}

    @router.get("")
    async def sessions() -> dict:
        return {"sessions": [{"session_id": s.id, "target": s.target,
                              "state": s.state.value,
                              "created_at": s.created_at}
                             for s in manager.list()]}

    return router
