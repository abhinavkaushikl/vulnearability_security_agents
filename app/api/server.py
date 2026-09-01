"""HTTP surface for the assessment engine.

    python -m app.api.server                 # the entry point

Two independent surfaces, matching the contracts web/lib/api.ts and
web/lib/behaviourApi.ts already speak:

    POST   /analyze                -> {"assessment_id": "..."}
    GET    /analyze/{id}/stream    -> text/event-stream of Progress
    GET    /analyze/{id}           -> Report

    POST   /behaviour              -> {"session_id": "..."}
    GET    /behaviour/{id}/stream  -> text/event-stream of BehaviourProgress
    GET    /behaviour/{id}         -> the UX report

The second is the User Behaviour Agent (app/behaviour/, see app/api/behaviour.py).
It runs a different pipeline against a different question and shares only the
process, the safety layer and the traffic-budget accounting.

The service is a thin shell. It validates a URL, hands it to the same graph
the CLI runs, and projects the terminal state onto the JSON the interface
expects. It holds no rule knowledge, evaluates nothing, and cannot cause a
browser action that AssessmentPlan.actions does not authorise.

Authorization is unchanged and is not weakened by being reachable over HTTP:
passive mode is still the only default, and the operator is still responsible
for assessing only targets they are authorized to test. Binding this to a
public interface would let anyone point it at anyone, so it binds to
127.0.0.1 unless AGENTQA_HOST says otherwise.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.behaviour import BehaviourManager, build_router
from app.api.runner import InvalidTarget, RunManager, RunOptions

log = logging.getLogger("assessment.api")

#: Dev origins for `next dev`. 3001 is included because Next falls back to it
#: when 3000 is taken. Override with AGENTQA_CORS_ORIGINS (comma-separated).
_DEFAULT_ORIGINS = [f"http://{host}:{port}"
                    for host in ("localhost", "127.0.0.1")
                    for port in (3000, 3001)]


class AnalyzeRequest(BaseModel):
    """The browser sends only `url`; the rest mirror the CLI's flags."""

    url: str
    families: list[str] | None = None
    network_profiles: list[str] | None = None
    iterations: int | None = Field(default=None, ge=1, le=10)
    skip_performance: bool = False
    no_llm: bool = False


def create_app(*, config: str = "config.yaml",
               policy: str = "policy.yaml") -> FastAPI:
    app = FastAPI(
        title="AgentQA",
        description="Website security & performance assessment. Passive by "
                    "default. Assess only targets you are authorized to test.",
        version="0.1.0")

    origins = [o.strip() for o in os.environ.get(
        "AGENTQA_CORS_ORIGINS", ",".join(_DEFAULT_ORIGINS)).split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware, allow_origins=origins, allow_methods=["*"],
        allow_headers=["*"])

    manager = RunManager(config=config, policy=policy)
    app.state.manager = manager

    # The behaviour agent is mounted as its own router. Nothing below this
    # line is aware of it, and nothing in it is aware of the rule pack.
    behaviour = BehaviourManager(config=config, policy=policy)
    app.state.behaviour = behaviour
    app.include_router(build_router(behaviour))

    # ------------------------------------------------------------- health
    @app.get("/health")
    async def health() -> dict:
        return {
            "ok": True,
            "active": sum(1 for r in manager.list()
                          if not r.status.is_terminal),
            "behaviour_active": sum(1 for s in behaviour.list()
                                    if not s.terminal),
            "surfaces": ["analyze", "behaviour"],
        }

    # ------------------------------------------------------------ analyze
    @app.post("/analyze")
    async def analyze(req: AnalyzeRequest) -> dict:
        try:
            run = manager.start(req.url, RunOptions(
                families=req.families,
                network_profiles=req.network_profiles,
                iterations=req.iterations,
                skip_performance=req.skip_performance,
                no_llm=req.no_llm))
        except InvalidTarget as exc:
            # The CLI's exit code 2, as a status code.
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        log.info("accepted %s for %s", run.id, run.target)
        return {"assessment_id": run.id, "target": run.target,
                "status": run.status.value}

    @app.get("/analyze/{run_id}/stream")
    async def stream(run_id: str) -> StreamingResponse:
        run = manager.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="unknown assessment")

        async def events():
            q = run.subscribe()
            try:
                while True:
                    try:
                        event = await asyncio.wait_for(q.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        # Comment frame: keeps proxies from closing an idle
                        # stream without inventing a progress event.
                        yield ": keep-alive\n\n"
                        continue
                    yield f"data: {json.dumps(event)}\n\n"
                    if event["status"] in ("COMPLETED", "PARTIAL",
                                           "BLOCKED", "FAILED"):
                        return
            finally:
                run.unsubscribe(q)

        return StreamingResponse(
            events(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache",
                     "Connection": "keep-alive",
                     "X-Accel-Buffering": "no"})

    @app.get("/analyze/{run_id}")
    async def report(run_id: str) -> dict:
        run = manager.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="unknown assessment")
        if run.report is None:
            if run.error:
                raise HTTPException(status_code=500, detail=run.error)
            raise HTTPException(
                status_code=409,
                detail=f"assessment is still running ({run.status.value})")
        return run.report

    @app.delete("/analyze/{run_id}")
    async def cancel(run_id: str) -> dict:
        if not await manager.cancel(run_id):
            raise HTTPException(status_code=404,
                                detail="unknown or already finished")
        return {"assessment_id": run_id, "cancelled": True}

    @app.get("/analyze")
    async def runs() -> dict:
        return {"runs": [{"assessment_id": r.id, "target": r.target,
                          "status": r.status.value,
                          "created_at": r.created_at}
                         for r in manager.list()]}

    return app


app = create_app()


def main() -> None:
    import uvicorn

    logging.basicConfig(
        level=os.environ.get("AGENTQA_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)-7s %(name)-28s %(message)s",
        datefmt="%H:%M:%S")

    host = os.environ.get("AGENTQA_HOST", "127.0.0.1")
    port = int(os.environ.get("AGENTQA_PORT", "8000"))
    log.info("AgentQA API on http://%s:%d", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
