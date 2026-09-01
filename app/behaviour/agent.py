"""UserBehaviourAgent — the loop.

    OBSERVE → UNDERSTAND → PLAN → ACT → MEASURE → OBSERVE → ADAPT → REPORT

This is the only module that owns the sequence. It holds no browser knowledge
(that is `executor.py`), no reasoning (that is `brain.py`), no arithmetic
(that is `scoring.py`) and no page parsing (that is `observer.py`). What it
owns is the state machine and the decision to stop.

Stopping is the part worth reading. An autonomous loop with a browser and a
budget has exactly one interesting failure mode — it never finishes — so
there are four independent brakes, and any one of them ends the run cleanly:

  * the traffic budget (shared with the security engine, same accounting)
  * a per-journey step ceiling
  * a global action ceiling
  * consecutive-failure detection per journey

A block from the target is not one of these. It is not a brake, it is an
answer: the session halts, records the reason, and reports it (§11).
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

from playwright.async_api import BrowserContext, Page

from app.behaviour import report as report_mod
from app.behaviour import scoring
from app.behaviour.brain import AgentBrain
from app.behaviour.executor import ActionExecutor
from app.behaviour.measure import MeasurementEngine
from app.behaviour.memory import AgentMemory, normalise_url
from app.behaviour.models import (ActionIntent, ActionKind, ActionRecord,
                                  AgentState, BehaviourProgress,
                                  BehaviourReport, Journey, Outcome, PageModel,
                                  Severity, SiteUnderstanding, ThoughtEntry)
from app.behaviour.observer import WebsiteObserver
from app.safety import antibot
from app.safety.limits import BudgetExceeded, TrafficBudget
from app.tools.browser import BrowserSession
from app.tools.statistics import calculate_percentile

log = logging.getLogger(__name__)

#: Rough progress weights per state, for the interface's bar. Cosmetic; never
#: influences a measurement or a verdict (same rule as api/progress.py).
_PCT = {
    AgentState.DISCOVERING: (2, 14),
    AgentState.UNDERSTANDING: (14, 22),
    AgentState.PLANNING: (22, 30),
    AgentState.NAVIGATING: (30, 88),
    AgentState.INTERACTING: (30, 88),
    AgentState.OBSERVING: (30, 88),
    AgentState.MEASURING: (30, 88),
    AgentState.ADAPTING: (30, 88),
    AgentState.REPORTING: (88, 99),
    AgentState.COMPLETED: (100, 100),
}


class UserBehaviourAgent:
    """One autonomous session against one target."""

    def __init__(self, *, session: BrowserSession, budget: TrafficBudget,
                 settings, provider, target: str, session_id: str,
                 artifact_dir=None, progress=None, use_llm: bool = True,
                 max_actions: int = 60, max_steps_per_journey: int = 10,
                 pacing: float = 1.0, screenshots: bool = True,
                 seed: int | None = None, llm_decides_steps: bool = False,
                 llm_call_timeout: float = 45.0):
        self.session = session
        self.budget = budget
        self.settings = settings
        self.target = target
        self.session_id = session_id
        self.artifact_dir = artifact_dir
        self.progress = progress
        self.max_actions = max_actions
        self.max_steps_per_journey = max_steps_per_journey
        self.screenshots = screenshots

        self.brain = AgentBrain(provider, enabled=use_llm,
                                decide_with_model=llm_decides_steps,
                                call_timeout=llm_call_timeout)
        self.observer = WebsiteObserver()
        self.engine = MeasurementEngine()
        self.memory = AgentMemory()
        self.pacing = pacing
        self.seed = seed

        self.state = AgentState.DISCOVERING
        self.actions: list[ActionRecord] = []
        self.thoughts: list[ThoughtEntry] = []
        self.page_models: list[PageModel] = []
        self.journeys: list[Journey] = []
        self.errors: list[str] = []
        self.blocked_reason: str | None = None
        self.current_objective = "Reaching the target"
        self.current_action = ""
        self._journeys_done = 0
        #: journey id -> what the loop actually did. The single source of
        #: truth for whether a journey completed; see scoring.journey_outcomes.
        self._journey_progress: dict[str, dict] = {}
        self._node: str | None = None
        self._started = time.monotonic()
        self._root_host = urlparse(target).hostname or ""

    # ── progress plumbing ────────────────────────────────────────────────
    def _emit(self, *, thought: ThoughtEntry | None = None,
              map_nodes: list[dict] | None = None) -> None:
        if self.progress is None:
            return
        lo, hi = _PCT.get(self.state, (0, 100))
        if self.state in (AgentState.NAVIGATING, AgentState.INTERACTING,
                          AgentState.OBSERVING, AgentState.MEASURING,
                          AgentState.ADAPTING):
            span = max(1, self.max_actions)
            pct = lo + (hi - lo) * min(1.0, len(self.actions) / span)
        else:
            pct = lo
        perceived = [a.timing.perceived_ms for a in self.actions
                     if a.timing.perceived_ms is not None]
        try:
            self.progress(BehaviourProgress(
                state=self.state,
                pct=round(pct, 1),
                objective=self.current_objective,
                current_action=self.current_action,
                page_url=self.page_models[-1].url if self.page_models else self.target,
                pages_visited=self.memory.pages_explored,
                interactions=sum(1 for a in self.actions
                                 if a.outcome is not Outcome.REFUSED),
                actions_dispatched=len(self.actions),
                avg_response_ms=(round(calculate_percentile(perceived, 50), 1)
                                 if perceived else None),
                requests=self.budget.total_requests,
                journeys_done=self._journeys_done,
                journeys_total=len(self.journeys),
                thought=thought,
                node=self._node,
                map_nodes=map_nodes))
        except Exception as exc:                                # noqa: BLE001
            log.debug("progress sink raised, ignoring: %s", exc)

    def _think(self, observation: str, action: str, result: str = "",
               latency: float | None = None, ok: bool | None = None) -> None:
        """§16. Three statements of fact, assembled in Python.

        Not chain-of-thought and not a paraphrase of one: every field here is
        built from an ActionRecord or a PageModel, so the interface cannot
        show the agent narrating something it did not do.
        """
        entry = ThoughtEntry(
            seq=len(self.thoughts) + 1, state=self.state,
            observation=observation, action=action, result=result,
            latency_ms=latency, ok=ok)
        self.thoughts.append(entry)
        self._emit(thought=entry)

    def _enter(self, state: AgentState, objective: str = "",
               action: str = "") -> None:
        self.state = state
        if objective:
            self.current_objective = objective
        if action:
            self.current_action = action
        self._emit()

    # ── the run ──────────────────────────────────────────────────────────
    async def run(self) -> BehaviourReport:
        started_at = datetime.now(timezone.utc)
        ctx: BrowserContext | None = None
        page: Page | None = None
        try:
            ctx = await self.session.new_context(label="behaviour")
            page = await self.session.open_page(ctx)
            page.on("pageerror", lambda e: self.errors.append(
                f"page error: {str(e)[:160]}"))

            await self._discover(page)
            if self.blocked_reason:
                return self._finish(started_at, AgentState.BLOCKED)

            await self._understand()
            await self._plan()
            await self._explore(page)

        except BudgetExceeded as exc:
            self.errors.append(f"traffic budget reached: {exc}")
            log.info("behaviour session stopped by the budget: %s", exc)
        except asyncio.CancelledError:
            self.errors.append("cancelled")
            raise
        except Exception as exc:                                # noqa: BLE001
            self.errors.append(f"{type(exc).__name__}: {exc}")
            log.exception("behaviour session failed")
            if not self.actions:
                return self._finish(started_at, AgentState.FAILED)
        finally:
            if page is not None:
                try:
                    await self.engine.stop(page)
                except Exception:                               # noqa: BLE001
                    pass
            if ctx is not None:
                await self.session.close_context(ctx)

        return self._finish(started_at, AgentState.COMPLETED)

    # ── phase 1: discovery ───────────────────────────────────────────────
    async def _discover(self, page: Page) -> None:
        self._enter(AgentState.DISCOVERING, "Reaching the site",
                    f"Opening {self.target}")

        response = None
        try:
            self.budget.navigate(self.target, "behaviour agent: first contact")
            response = await page.goto(self.target, wait_until="domcontentloaded")
        except Exception as exc:                                # noqa: BLE001
            self.errors.append(f"could not open the target: {exc}")
            raise

        # Detect, stop, record, report — never route around. §11.
        try:
            body = await page.content()
        except Exception:                                       # noqa: BLE001
            body = ""
        signal = antibot.detect(
            status=response.status if response else None,
            headers=dict(response.headers) if response else {},
            body=body, url=page.url)
        if signal.detected:
            self.blocked_reason = antibot.blocked_reason(signal)
            self._think(
                f"The target answered with {signal.kind.replace('_', ' ')}.",
                "Halting the session.",
                "No bypass was attempted and no request was retried.",
                ok=False)
            self._enter(AgentState.BLOCKED, "Blocked by the target")
            return

        await self.session.wait_for_ready(page, settle_ms=900)
        self.current_action = "Reading the page"
        model = await self.observer.observe(page, with_vitals=True,
                                            with_keyboard=True)
        await self._capture(page, model, "01-landing")
        self.page_models.append(model)
        self.memory.record_visit(model)

        vitals = model.vitals
        speed = (f"{vitals.lcp_ms:.0f} ms to the largest paint"
                 if vitals.lcp_ms is not None
                 else f"{vitals.load_ms:.0f} ms to load"
                 if vitals.load_ms is not None else "timing unavailable")
        self._think(
            f"{len(model.elements)} interactive elements, "
            f"{len(model.forms)} form(s), "
            f"{'scrollable' if model.scrollable else 'a single screen'}.",
            f"Measured the landing page: {speed}.",
            f"{model.a11y.focusable_count} focusable controls, "
            f"{model.a11y.unlabelled_controls} of them unnamed.",
            latency=vitals.lcp_ms, ok=True)

    async def _capture(self, page: Page, model: PageModel, name: str) -> None:
        if not self.screenshots or self.artifact_dir is None:
            return
        try:
            shots = self.artifact_dir / "behaviour"
            shots.mkdir(parents=True, exist_ok=True)
            path = shots / f"{name}.png"
            await page.screenshot(path=str(path), full_page=False)
            model.screenshot = f"behaviour/{name}.png"
        except Exception as exc:                                # noqa: BLE001
            log.debug("screenshot failed: %s", exc)

    # ── phase 2: understanding ───────────────────────────────────────────
    async def _understand(self) -> None:
        self._enter(AgentState.UNDERSTANDING, "Working out what this site is",
                    "Interpreting the page")
        model = self.page_models[-1]
        self.understanding = await self.brain.understand(model)
        for a in self.understanding.key_affordances:
            self.memory.learn(f"{a} exists")
        self._think(
            f"Title, headings and {len(model.elements)} controls read.",
            f"Classified as {self.understanding.kind.value}.",
            f"A visitor comes here to {self.understanding.primary_goal}."
            + (f" ({', '.join(self.understanding.key_affordances)})"
               if self.understanding.key_affordances else ""),
            ok=True)

    # ── phase 3: planning ────────────────────────────────────────────────
    async def _plan(self) -> None:
        self._enter(AgentState.PLANNING, "Deciding what a visitor would do",
                    "Building journeys")
        self.journeys = await self.brain.plan_journeys(
            self.understanding, self.page_models[-1])
        for j in self.journeys:
            for s in j.steps:
                self.memory.defer(s.label)
        self._emit(map_nodes=self.map_nodes())
        self._think(
            f"{len(self.understanding.key_affordances)} affordances available.",
            f"Planned {len(self.journeys)} journey(s): "
            + ", ".join(j.name for j in self.journeys) + ".",
            f"{sum(len(j.steps) for j in self.journeys)} steps in total.",
            ok=True)

    def map_nodes(self) -> list[dict]:
        """§14's journey map, as structure. The frontend does the layout.

        Emitting coordinates from here would put a visual decision in the
        backend and freeze it; emitting the graph lets the interface lay it
        out for whatever space it has.
        """
        nodes: list[dict] = [{"id": "start", "label": "ENTRY",
                              "journey_id": None, "index": -1}]
        edges: list[dict] = []
        for j in self.journeys:
            prev = "start"
            for i, s in enumerate(j.steps):
                nid = f"{j.id}:{i}"
                nodes.append({"id": nid, "label": s.label[:28].upper(),
                              "journey_id": j.id, "journey": j.name,
                              "index": i, "action": s.action})
                edges.append({"from": prev, "to": nid})
                prev = nid
        return [{"nodes": nodes, "edges": edges}]

    # ── phase 4: the loop ────────────────────────────────────────────────
    async def _explore(self, page: Page) -> None:
        executor = ActionExecutor(page, self.budget, self.engine,
                                  root_host=self._root_host,
                                  entry_url=self.target,
                                  pacing=self.pacing, seed=self.seed)

        for journey in self.journeys:
            if len(self.actions) >= self.max_actions:
                log.info("action ceiling reached; %d journeys not attempted",
                         len(self.journeys) - self._journeys_done)
                break
            try:
                await self._run_journey(page, executor, journey)
            except BudgetExceeded:
                raise
            except Exception as exc:                            # noqa: BLE001
                # One journey failing is scoped, exactly like a ComponentError
                # in the security engine. The session continues.
                self.errors.append(f"journey {journey.id}: {exc}")
                log.warning("journey %s failed: %s", journey.id, exc)
            self._journeys_done += 1
            self._emit()

    async def _run_journey(self, page: Page, executor: ActionExecutor,
                           journey: Journey) -> None:
        self.current_objective = journey.goal or journey.name
        self._enter(AgentState.NAVIGATING, journey.goal or journey.name,
                    f"Starting: {journey.name}")

        # Every journey starts from the landing page, so one slow journey
        # cannot silently change the entry point of the next.
        if (self.page_models
                and normalise_url(self.page_models[-1].url)
                != normalise_url(self.target)):
            await self._return_home(page, executor)

        state = self._journey_progress.setdefault(journey.id, {
            "steps_attempted": 0, "completed": False,
            "abandoned_at": None, "reason": None})

        step_index = 0
        consecutive_failures = 0
        steps_taken = 0

        while (step_index < len(journey.steps)
               and steps_taken < self.max_steps_per_journey
               and len(self.actions) < self.max_actions):
            steps_taken += 1
            self.budget.check_time()

            self._node = f"{journey.id}:{min(step_index, len(journey.steps) - 1)}"
            step = journey.steps[step_index]

            # OBSERVE. First: are we still somewhere we can observe FROM?
            # A stranded browser reports a blank document as a site with no
            # controls, which reads as a catastrophic result rather than as
            # the navigation accident it is.
            if executor._stranded(page.url):
                self.errors.append(
                    f"the browser was on {page.url!r}; returned to the entry point")
                await self._return_home(page, executor)

            self._enter(AgentState.OBSERVING, journey.goal or journey.name,
                        f"Looking at {self._short_url(page.url)}")
            model = await self.observer.observe(page)
            self.page_models.append(model)
            first_time = self.memory.record_visit(model)
            if first_time and self.screenshots:
                await self._capture(page, model,
                                    f"{journey.id}-{step_index:02d}")

            # PLAN THIS STEP
            intent = await self.brain.decide(
                model, journey, step_index, self.memory, self.understanding,
                self.actions)
            self.current_action = intent.reason or step.label

            if intent.kind is ActionKind.DONE:
                self.memory.complete(step.label)
                state["completed"] = True
                self._think(f"On {self._short_url(model.url)}.",
                            "The journey's goal has been reached.",
                            journey.goal, ok=True)
                break

            # ACT + MEASURE
            self._enter(AgentState.INTERACTING, journey.goal or journey.name,
                        self.current_action)
            record = await executor.execute(intent, model)
            record.state = AgentState.INTERACTING
            self.actions.append(record)
            self.memory.record_action(self.memory.place(model), record)

            self._enter(AgentState.MEASURING, journey.goal or journey.name,
                        f"Measuring the response to {record.element_label or intent.kind.value}")
            self._report_action(record, model)

            if record.outcome is Outcome.SUCCESS:
                consecutive_failures = 0
                self.memory.complete(step.label)
                step_index += 1
                state["steps_attempted"] = step_index
                await self._settle(page)
                continue

            if record.outcome is Outcome.REFUSED:
                # Not a failure of the site. Skip the step and keep going —
                # but it is not a completed step either, so it is recorded as
                # attempted and never as succeeded.
                step_index += 1
                state["steps_attempted"] = step_index
                continue

            # An optional step is one a visitor might not take at all — a
            # hover on a click-driven menu, a variant picker on a product
            # with one variant. Failing it is information, not an obstacle,
            # so it advances the journey without counting against it.
            if step.optional:
                step_index += 1
                state["steps_attempted"] = step_index
                self._think(record.observed,
                            f"Skipping the optional step {step.label!r}.",
                            "A visitor would simply not do this here.",
                            ok=None)
                continue

            # ADAPT — §22
            consecutive_failures += 1
            if consecutive_failures >= 3:
                state["abandoned_at"] = step.label
                state["reason"] = (
                    f"three consecutive attempts failed; last: {record.observed}"
                )[:160]
                self._think(
                    f"Three consecutive steps failed on {journey.name}.",
                    "Abandoning this journey.",
                    "A journey that cannot be completed is a finding, not "
                    "something to keep retrying.", ok=False)
                break

            self._enter(AgentState.ADAPTING, journey.goal or journey.name,
                        "Working out what went wrong")
            model_now = await self.observer.observe(page)
            self.page_models.append(model_now)
            diagnosis, recovery, recovery_intent = await self.brain.adapt(
                model_now, journey, step_index, record, self.memory,
                self.understanding)

            self._think(f"{record.observed}", f"Diagnosis: {diagnosis}",
                        f"Recovery: {recovery.replace('_', ' ')}.", ok=False)

            if recovery == "abandon" or recovery_intent is None:
                state["abandoned_at"] = step.label
                state["reason"] = diagnosis[:160]
                break
            if recovery_intent.kind is ActionKind.DONE:
                # The recovery decided the goal is already met or is not
                # reachable from here. Either way the journey ends; it is not
                # dispatched, because DONE is not an action.
                state["completed"] = recovery == "retry"
                if not state["completed"]:
                    state["abandoned_at"] = step.label
                    state["reason"] = diagnosis[:160]
                break
            if recovery in ("alternate_route",):
                step_index += 1
                state["steps_attempted"] = step_index
            if recovery == "go_back":
                await self._return_home(page, executor)
                continue

            recovery_intent.journey_id = journey.id
            recovery_intent.step_label = step.label
            self._enter(AgentState.INTERACTING, journey.goal or journey.name,
                        recovery_intent.reason or "Recovering")
            rec = await executor.execute(recovery_intent, model_now)
            rec.state = AgentState.ADAPTING
            rec.note = (rec.note + " · recovery action").strip(" ·")
            self.actions.append(rec)
            self.memory.record_action(self.memory.place(model_now), rec)
            self._report_action(rec, model_now)
            if rec.outcome is Outcome.SUCCESS:
                consecutive_failures = 0
            await self._settle(page)

        # Falling out of the while loop with every step advanced is the other
        # way a journey completes: the agent walked the whole route.
        if step_index >= len(journey.steps):
            state["completed"] = True
            state["steps_attempted"] = len(journey.steps)
        elif not state["completed"] and state["abandoned_at"] is None:
            state["abandoned_at"] = journey.steps[step_index].label
            state["reason"] = (
                "the step ceiling was reached before the journey finished"
                if steps_taken >= self.max_steps_per_journey else
                "the session's action ceiling was reached")

    async def _settle(self, page: Page) -> None:
        """A beat between steps. People do not act twice in the same frame."""
        try:
            await page.wait_for_timeout(int(220 * max(self.pacing, 0.1)))
        except Exception:                                       # noqa: BLE001
            pass

    async def _return_home(self, page: Page, executor: ActionExecutor) -> None:
        try:
            record = await executor.execute(
                ActionIntent(kind=ActionKind.NAVIGATE, value=self.target,
                             expectation="the landing page loads again",
                             reason="returning to the entry point to start a "
                                    "journey from where a visitor would"),
                self.page_models[-1] if self.page_models else PageModel(url=self.target))
            self.actions.append(record)
            await self.session.wait_for_ready(page, settle_ms=500)
        except BudgetExceeded:
            raise
        except Exception as exc:                                # noqa: BLE001
            self.errors.append(f"could not return to the entry point: {exc}")

    def _report_action(self, record: ActionRecord, model: PageModel) -> None:
        """Turn one measured action into the three lines the interface shows."""
        t = record.timing
        subject = record.element_label or record.intent.kind.value
        observation = (f"{record.intent.kind.value.replace('_', ' ').title()} "
                       f"on {subject!r} — " + (record.expectation or
                                               "expecting a response"))
        action = record.intent.reason or record.intent.step_label or subject
        result = record.observed
        if t.perceived_ms is not None and record.outcome is Outcome.SUCCESS:
            result = f"{record.observed}"
        self._think(observation, action, result,
                    latency=t.perceived_ms,
                    ok=(record.outcome is Outcome.SUCCESS))

    @staticmethod
    def _short_url(url: str) -> str:
        try:
            p = urlparse(url)
            return (p.path or "/") + (f"?{p.query[:30]}" if p.query else "")
        except Exception:                                       # noqa: BLE001
            return url

    # ── phase 5: reporting ───────────────────────────────────────────────
    def _finish(self, started_at: datetime, state: AgentState
                ) -> BehaviourReport:
        self._enter(AgentState.REPORTING, "Writing the report",
                    "Scoring what was measured")

        understanding = getattr(self, "understanding", None)
        outcomes = scoring.journey_outcomes(self.journeys, self.actions,
                                            self._journey_progress)
        pages = list(self.memory.visits.values())
        # One PageModel per distinct place; repeated observations of the same
        # page would weight the accessibility score by how often the agent
        # happened to walk past it.
        unique_models: dict[str, PageModel] = {}
        for m in self.page_models:
            unique_models.setdefault(m.url, m)
        models = list(unique_models.values())

        score = scoring.compute_score(self.actions, models, pages)
        findings = scoring.generate_findings(self.actions, models, pages,
                                             outcomes)
        perceived = [a.timing.perceived_ms for a in self.actions
                     if a.timing.perceived_ms is not None]

        report = BehaviourReport(
            session_id=self.session_id,
            target=self.target,
            state=state if not self.blocked_reason else AgentState.BLOCKED,
            started_at=started_at,
            duration_seconds=round(time.monotonic() - self._started, 1),
            understanding=understanding or SiteUnderstanding(),
            journeys=self.journeys,
            journey_outcomes=outcomes,
            actions=self.actions,
            thoughts=self.thoughts,
            pages=pages,
            score=score,
            findings=findings,
            pages_explored=self.memory.pages_explored,
            interactions_total=sum(1 for a in self.actions
                                   if a.outcome is not Outcome.REFUSED),
            journeys_run=self._journeys_done,
            issues_detected=len(findings),
            critical_issues=sum(1 for f in findings
                                if f.severity is Severity.CRITICAL),
            avg_response_ms=(round(calculate_percentile(perceived, 50), 1)
                             if perceived else None),
            requests_made=self.budget.total_requests,
            blocked_reason=self.blocked_reason,
            errors=self.errors[:20],
            llm_model=(getattr(self.brain.provider, "model", None)
                       if self.brain.enabled else None),
            browser_version=self.session.browser_version,
        )
        if self.brain.model_timeouts:
            # Say so in the report rather than letting a heuristic plan pass
            # silently as a model one. GOV-05/IN-07 make the same demand of
            # the security engine: state which tools produced the result.
            report.errors.append(
                f"{self.brain.model_timeouts} model call(s) exceeded the "
                f"{self.brain.call_timeout:.0f}s deadline; the deterministic "
                "answer was used for those")
        report.summary = report_mod.deterministic_summary(report)
        report.insights = report_mod.behavioural_insights(report)
        self.state = report.state
        self._emit()
        return report

    async def write_summary(self, report: BehaviourReport) -> None:
        """One optional model call, after everything is measured.

        It runs on the finished report, so there is nothing left for it to
        change: the score, the findings and the severities already exist, and
        the deterministic summary is the fallback if it returns nothing.
        """
        if not self.brain.enabled:
            return
        facts = report_mod.summary_facts(report)
        report.summary = await self.brain.summarise(facts, report.summary)
