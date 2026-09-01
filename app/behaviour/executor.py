"""Browser Executor — the only thing in this package that touches the page.

Takes an `ActionIntent`, resolves it against the element the observer already
classified, dispatches it with the measurement probe running, and returns an
`ActionRecord` describing what actually happened.

Two boundaries are enforced here and nowhere else:

  * **The intent cannot escape the inventory.** An intent names a `ref`. A ref
    only exists because `observer.py` saw that element, stamped it and
    classified it. There is no path from a model response to a selector, a
    URL or a script.
  * **The safety classification is final.** `safety.guard()` runs before every
    dispatch. A FORBIDDEN element produces an `Outcome.REFUSED` record — the
    refusal is data in the report, not a silent skip.

On human pacing: the agent hovers before it clicks, pauses after a
navigation, and scrolls in steps rather than jumping. This is a *measurement*
requirement, not an evasion one — a site's hover menu never opens if you
teleport the cursor onto the link, and its lazy-loaded content never arrives
if you jump to the footer, so a robotic agent would measure a page no user
ever sees. The browser still identifies itself normally, carries no stealth
patches, and `antibot` detection still halts the session (CLAUDE.md §11).
"""
from __future__ import annotations

import asyncio
import logging
import random
from urllib.parse import urljoin

from playwright.async_api import Page

from app.behaviour import js, safety
from app.behaviour.measure import MeasurementEngine, compute_timing
from app.behaviour.models import (ActionIntent, ActionKind, ActionRecord,
                                  AgentState, ElementKind, InteractionTiming,
                                  INTERACTION_CATEGORY, InteractiveElement,
                                  Outcome, PageModel, Risk)
from app.behaviour.safety import ActionRefused
from app.safety.limits import BudgetExceeded, TrafficBudget

log = logging.getLogger(__name__)

#: Actions that can change the document. Used to decide whether to re-observe
#: from scratch and whether a URL change is expected or a surprise.
_NAVIGATIONAL = {ActionKind.NAVIGATE, ActionKind.BACK, ActionKind.CLICK,
                 ActionKind.SUBMIT_SEARCH}

#: Fields whose latency belongs to the search experience, not the form one.
_SEARCH_KINDS = {ElementKind.SEARCH_INPUT}


def _category_for(intent: ActionIntent, el: InteractiveElement | None) -> str:
    """Which §11 bucket an action's timings belong in.

    The action alone is not enough: typing is a form interaction in general
    and a search interaction when the field is a search box, and users judge
    those against completely different expectations. Getting this wrong files
    a slow search under "forms", where nobody looking for the search problem
    will find it.
    """
    if el is not None and el.kind in _SEARCH_KINDS:
        return "search"
    return INTERACTION_CATEGORY.get(intent.kind, "other")


class ActionExecutor:
    """Dispatches one intent at a time, with a probe running around it."""

    def __init__(self, page: Page, budget: TrafficBudget,
                 engine: MeasurementEngine, *, root_host: str,
                 entry_url: str = "", pacing: float = 1.0,
                 seed: int | None = None):
        self.page = page
        self.budget = budget
        self.engine = engine
        self.root_host = root_host
        #: Where the session started. The one URL the executor may navigate to
        #: without an element to justify it, and only to recover.
        self.entry_url = entry_url
        #: 0 disables every human pause; 1 is the default cadence. Lowering it
        #: speeds a run up and makes hover-driven menus less likely to open —
        #: the report says which pacing produced it.
        self.pacing = max(0.0, pacing)
        self._rng = random.Random(seed)
        self.seq = 0
        #: Documents this session has actually pushed onto the history stack.
        #: `history.length` cannot be used for this: a fresh Playwright context
        #: already reports 2 after one goto, so trusting it lets the first
        #: `back` walk out of the site and strand the session on about:blank.
        self._depth = 0

    # ── pacing ───────────────────────────────────────────────────────────
    async def _pause(self, base_ms: int, spread: float = 0.35) -> None:
        """A human beat. Jittered, because a fixed cadence is its own tell —
        and, more to the point, because a fixed cadence lands every sample on
        the same point of a site's animation cycle."""
        if self.pacing <= 0:
            return
        ms = base_ms * self.pacing * (1 + self._rng.uniform(-spread, spread))
        await self.page.wait_for_timeout(max(0, int(ms)))

    async def _approach(self, el: InteractiveElement) -> None:
        """Move the pointer to the element in a couple of steps, then rest.

        Playwright's own `hover` teleports. Many menus open on `mouseover` of
        an ancestor and close on `mouseleave`, so the intermediate positions
        are the difference between measuring a menu and measuring nothing.
        """
        if self.pacing <= 0:
            return
        cx = el.x + el.width / 2
        cy = el.y + el.height / 2
        try:
            await self.page.mouse.move(cx, cy, steps=self._rng.randint(4, 9))
        except Exception:                                       # noqa: BLE001
            pass

    # ── resolution ───────────────────────────────────────────────────────
    def _locator(self, el: InteractiveElement):
        """Address the exact element the observer classified.

        The stamped attribute is the primary handle. A re-render can drop it,
        so role+name is the fallback — and if that matches several elements
        we take the first, which is what a user reading top to bottom would
        also reach.
        """
        loc = self.page.locator(el.selector)
        return loc

    async def _resolve(self, el: InteractiveElement):
        loc = self._locator(el)
        try:
            if await loc.count() > 0:
                return loc.first
        except Exception:                                       # noqa: BLE001
            pass
        # Fallback: the accessible identity, which survives a re-render.
        if el.role and el.name:
            try:
                alt = self.page.get_by_role(el.role, name=el.name, exact=False)
                if await alt.count() > 0:
                    return alt.first
            except Exception:                                   # noqa: BLE001
                pass
        if el.text:
            try:
                alt = self.page.get_by_text(el.text[:40], exact=False)
                if await alt.count() > 0:
                    return alt.first
            except Exception:                                   # noqa: BLE001
                pass
        return None

    # ── the public call ──────────────────────────────────────────────────
    async def execute(self, intent: ActionIntent, page_model: PageModel
                      ) -> ActionRecord:
        """Dispatch one intent. Never raises: a failure is a finding."""
        self.seq += 1
        el = page_model.by_ref(intent.element_ref) if intent.element_ref else None
        record = ActionRecord(
            seq=self.seq,
            state=AgentState.INTERACTING,
            intent=intent,
            page_url=page_model.url,
            element_label=el.label if el else "",
            element_kind=el.kind if el else None,
            category=_category_for(intent, el),
            expectation=intent.expectation or (
                el and f"a response from {el.label!r}") or "",
        )

        # 1. Safety. A refusal is recorded and reported, never worked around.
        try:
            safety.guard(el, intent.kind.value)
            self._guard_intent(intent, el, page_model)
        except ActionRefused as exc:
            record.outcome = Outcome.REFUSED
            record.observed = str(exc)
            record.note = "declined by the safety layer; the run continued"
            log.info("refused: %s", exc)
            return record

        if intent.element_ref and el is None:
            record.outcome = Outcome.ERROR
            record.observed = f"element {intent.element_ref} was no longer on the page"
            return record

        # 2. Probe up, wait for stillness, mark, dispatch.
        url_before = self.page.url
        await self.engine.install(self.page)
        settled = await self.engine.isolate(self.page)
        if not settled:
            record.note = ("the page was still changing when this action was "
                           "dispatched; its timings include that movement")
        is_scroll = intent.kind in (ActionKind.SCROLL, ActionKind.SCROLL_BACK)
        if is_scroll:
            await self.engine.start_frames(self.page)
        await self.engine.mark(self.page)

        try:
            await self._dispatch(intent, el, record)
        except ActionRefused as exc:
            record.outcome = Outcome.REFUSED
            record.observed = str(exc)
            return record
        except BudgetExceeded:
            raise
        except Exception as exc:                                # noqa: BLE001
            record.outcome = Outcome.ERROR
            record.observed = f"{type(exc).__name__}: {str(exc)[:180]}"
            record.note = "the action could not be dispatched"
            log.debug("dispatch failed: %s", exc)
            await self.engine.stop_frames(self.page)
            return record

        # 3a. A deliberate navigation is measured from the new document.
        if intent.kind in (ActionKind.NAVIGATE, ActionKind.BACK):
            wanted = (urljoin(url_before, intent.value or (el.href if el else ""))
                      if intent.kind is ActionKind.NAVIGATE else None)
            await self._measure_navigation(record, url_before,
                                           expected=wanted)
            return record

        # 3b. Everything else: wait for the DOM to go quiet, then read the probe.
        raw, state_ms, quiesced = await self.engine.settle(self.page)
        if is_scroll:
            await self.engine.stop_frames(self.page)
            raw = await self.engine.read(self.page) or raw

        # A click on a link replaces the document, which takes the probe with
        # it. That is a SUCCESSFUL navigation, not an unreadable probe. The
        # load state has to be awaited before the URL is compared: mid-flight,
        # the old URL is still the current one, and comparing too early
        # reports a working link as inconclusive.
        if raw is None:
            try:
                await self.page.wait_for_load_state("load", timeout=6000)
            except Exception:                                   # noqa: BLE001
                pass
            if self.page.url != url_before:
                await self._measure_navigation(record, url_before)
                self._depth += 1
                record.note = ("the click navigated; measured from the new "
                               "document's own timing")
                return record

        record.timing = compute_timing(raw, is_scroll=is_scroll,
                                       state_complete_ms=state_ms)
        if not quiesced:
            record.note = ("the page was still changing when the settle "
                           "window closed; completion time is unknown")

        # 4. Decide what happened. Never optimistic.
        self._judge(intent, el, record, raw)
        return record

    @staticmethod
    def _same_place(a: str, b: str) -> bool:
        """URL equality as a person means it: the fragment and a trailing
        slash are not different pages."""
        def norm(u: str) -> str:
            u = u.split("#")[0]
            base, _, query = u.partition("?")
            return (base.rstrip("/") or "/") + (f"?{query}" if query else "")
        return norm(a) == norm(b)

    async def _measure_navigation(self, record: ActionRecord, url_before: str,
                                  *, expected: str | None = None) -> None:
        """Judge and time a document replacement, from Python's side of it."""
        try:
            await self.page.wait_for_load_state("load", timeout=8000)
        except Exception:                                       # noqa: BLE001
            pass
        record.timing = await self.engine.navigation_timing(self.page)
        after = self.page.url
        record.url_changed = not self._same_place(after, url_before)
        record.new_url = after if record.url_changed else None
        speed = (f" in {record.timing.perceived_ms:.0f} ms"
                 if record.timing.perceived_ms is not None else "")

        if record.url_changed:
            record.outcome = Outcome.SUCCESS
            record.observed = f"arrived at {after}{speed}"
            return
        if "left-site" in record.note:
            # Going back walked out of the site's history entirely. The agent
            # was returned to the entry point, so the URL looks unchanged —
            # but nothing about that is a normal "back".
            record.note = record.note.replace("left-site", "").strip(" ·")
            record.outcome = Outcome.UNEXPECTED
            record.observed = (
                "going back left the site altogether; the session was "
                f"returned to {after}")
            return
        if expected is not None and self._same_place(after, expected):
            # Asked for a page and got it, having already been on it. That is
            # a reload, not a failure — the entry point is re-entered at the
            # start of every journey precisely so they all begin in the same
            # place.
            record.outcome = Outcome.SUCCESS
            record.observed = f"reloaded {after}{speed}"
            return
        record.outcome = Outcome.UNEXPECTED
        record.observed = (f"the URL did not change from {url_before} — "
                           "the destination was the same page")

    # ── safety, at the level of the whole intent ─────────────────────────
    def _guard_intent(self, intent: ActionIntent, el: InteractiveElement | None,
                      page_model: PageModel) -> None:
        """Rules that need more than one element to decide."""
        if intent.kind is ActionKind.NAVIGATE:
            url = intent.value or (el.href if el else None)
            if not url:
                raise ActionRefused("navigate without a target")
            absolute = urljoin(self.page.url, url)
            if not safety.in_scope(absolute, self.root_host):
                raise ActionRefused(
                    f"{absolute} is outside {self.root_host} — the agent "
                    "explores one site, it does not follow the web")

        if intent.kind is ActionKind.TYPE and el is not None:
            if el.risk is Risk.FORBIDDEN:
                raise ActionRefused(f"never types into {el.label!r}")
            form = next((f for f in page_model.forms
                         if el.ref in f.field_refs), None)
            if form and form.risk is Risk.FORBIDDEN:
                raise ActionRefused(
                    f"{el.label!r} belongs to a payment form; never filled")

        # There is no code path that submits a form. The one exception is a
        # search box, whose entire payload is a query the agent wrote itself.
        if intent.kind is ActionKind.SUBMIT_SEARCH:
            if el is None or el.kind is not ElementKind.SEARCH_INPUT:
                raise ActionRefused(
                    "submit is only ever dispatched on a search field")

    # ── dispatch ─────────────────────────────────────────────────────────
    async def _dispatch(self, intent: ActionIntent,
                        el: InteractiveElement | None,
                        record: ActionRecord) -> None:
        kind = intent.kind
        page = self.page

        if kind is ActionKind.NAVIGATE:
            url = urljoin(page.url, intent.value or (el.href if el else ""))
            self.budget.navigate(url, intent.reason or "behaviour journey step")
            await page.goto(url, wait_until="domcontentloaded")
            self._depth += 1
            await self._pause(700)
            return

        if kind is ActionKind.BACK:
            # Going back from the first page in a fresh context lands on
            # about:blank, and every subsequent action then measures a blank
            # document — scrolls that do not scroll, controls that are not
            # there. The session does not crash; it silently reports the
            # target as broken. So: refuse when there is no history, and
            # recover if the browser leaves the site anyway.
            if self._depth <= 0:
                raise ActionRefused(
                    "there is no previous page to return to — the session has "
                    "not navigated away from where it started")
            self.budget.aux(page.url, "return to the previous page")
            await page.go_back(wait_until="domcontentloaded")
            self._depth -= 1
            await self._pause(500)
            if self._stranded(page.url):
                await self._recover_to_entry(record)
                record.note = (record.note + " · left-site").strip(" ·")
            return

        if kind is ActionKind.READ:
            # A deliberate dwell. It measures nothing about the site directly,
            # but it is where lazy content and deferred scripts land, and the
            # probe catches those.
            await self._pause(int(1100 + 900 * self._rng.random()), 0.2)
            return

        if kind in (ActionKind.SCROLL, ActionKind.SCROLL_BACK):
            await self._scroll(intent, record)
            return

        if el is None:
            raise ActionRefused(f"{kind.value} needs an element")

        loc = await self._resolve(el)
        if loc is None:
            raise ActionRefused(f"{el.label!r} could not be located any more")

        try:
            await loc.scroll_into_view_if_needed(timeout=2500)
        except Exception:                                       # noqa: BLE001
            pass
        await self._approach(el)

        if kind is ActionKind.HOVER:
            await self._pause(120)
            await self.engine.mark(page)
            await loc.hover(timeout=4000)
            await self._pause(420)
            return

        if kind is ActionKind.CLICK:
            await self._pause(180)          # the beat before committing
            await self.engine.mark(page)
            # No force: a click that Playwright cannot land because something
            # covers the control is a real usability defect, and forcing it
            # would hide exactly the finding we are here to make.
            await loc.click(timeout=6000, no_wait_after=True)
            return

        if kind is ActionKind.TYPE:
            text = intent.value or ""
            await loc.click(timeout=4000)
            await self._pause(160)
            await self.engine.mark(page)
            # Per-keystroke, because a site's suggestion latency is a response
            # to typing, not to a value being pasted in.
            await loc.type(text, delay=int(55 * max(self.pacing, 0.2)))
            return

        if kind is ActionKind.CLEAR:
            await self.engine.mark(page)
            await loc.fill("", timeout=4000)
            return

        if kind is ActionKind.SUBMIT_SEARCH:
            await loc.click(timeout=4000)
            await self._pause(140)
            self.budget.aux(page.url, "search submission from the agent's own query")
            await self.engine.mark(page)
            await loc.press("Enter")
            return

        if kind is ActionKind.SELECT_OPTION:
            await self.engine.mark(page)
            value = intent.value
            try:
                if value:
                    await loc.select_option(label=value, timeout=4000)
                else:
                    await loc.select_option(index=1, timeout=4000)
            except Exception:
                await loc.select_option(index=1, timeout=4000)
            return

        if kind is ActionKind.CHECK:
            await self.engine.mark(page)
            await loc.check(timeout=4000)
            return

        if kind is ActionKind.PRESS_KEY:
            await loc.focus(timeout=3000)
            await self.engine.mark(page)
            await loc.press(intent.value or "Enter")
            return

        if kind in (ActionKind.PLAY_MEDIA, ActionKind.PAUSE_MEDIA):
            await self.engine.mark(page)
            # Muted: the agent never makes noise on someone's machine, and an
            # unmuted autoplay is blocked by the browser anyway, which would
            # have been measured as a broken control.
            action = "play" if kind is ActionKind.PLAY_MEDIA else "pause"
            await loc.evaluate(
                "(el, a) => { try { el.muted = true; el[a](); } catch (e) {} }",
                action)
            await self._pause(600)
            return

        raise ActionRefused(f"{kind.value} is not a dispatchable action")

    def _stranded(self, url: str) -> bool:
        """Is the browser somewhere the session cannot continue from?"""
        if not url or url.startswith(("about:", "chrome:", "data:")):
            return True
        return bool(self.root_host) and not safety.in_scope(url, self.root_host)

    async def _recover_to_entry(self, record: ActionRecord) -> None:
        """Put the browser back on the site. Recorded, never silent."""
        if not self.entry_url:
            return
        self.budget.navigate(
            self.entry_url,
            "recovering the session: the browser left the site")
        await self.page.goto(self.entry_url, wait_until="domcontentloaded")
        record.note = (record.note +
                       " · the browser left the site and was returned to the "
                       "entry point").strip(" ·")

    async def _scroll(self, intent: ActionIntent, record: ActionRecord) -> None:
        """Paced scrolling — §12. Never `scrollTo(0, 10000)`.

        Steps are sized as a fraction of the viewport and separated by real
        pauses, because that is the only way lazy loaders, sticky headers and
        scroll-linked animations behave the way they do for a person. A single
        jump measures the browser's ability to set `scrollY`, which is not a
        question anyone is asking.
        """
        page = self.page
        vh = await page.evaluate("() => window.innerHeight") or 800
        fraction = intent.amount if intent.amount else 0.85
        direction = -1 if intent.kind is ActionKind.SCROLL_BACK else 1
        total = vh * fraction * direction

        steps = max(2, min(8, int(abs(fraction) * 5) + 2))
        per_step = total / steps
        await self.engine.mark(page)
        for _ in range(steps):
            await page.evaluate(js.SCROLL_BY, per_step)
            # Varying the beat is the point: a constant cadence samples the
            # same phase of every scroll-linked animation and reports it as
            # smooth.
            await self._pause(int(70 + 90 * self._rng.random()), 0.4)
        await self._pause(320)

    # ── judgement ────────────────────────────────────────────────────────
    def _judge(self, intent: ActionIntent, el: InteractiveElement | None,
               record: ActionRecord, raw: dict | None) -> None:
        """Decide the outcome from what was observed. Never from what was hoped.

        The default is INCONCLUSIVE. SUCCESS requires a positive observation:
        a URL change, DOM mutations, a modal, or movement. NO_RESPONSE is
        itself a positive observation — the probe ran, nothing moved — and it
        is the finding that catches a dead control.
        """
        if raw is None:
            record.outcome = Outcome.INCONCLUSIVE
            record.observed = "the measurement probe could not be read"
            return

        start_url = raw.get("startUrl") or record.page_url
        now_url = raw.get("url") or start_url
        record.url_changed = (start_url.split("#")[0] != now_url.split("#")[0])
        if record.url_changed:
            record.new_url = now_url
        record.console_errors = [e for e in (raw.get("errors") or []) if e][:5]

        mutations = record.timing.mutation_count
        requests = record.timing.request_count
        scrolled = abs(float(raw.get("scrollY") or 0)
                       - float(raw.get("startScroll") or 0)) > 4
        modal = bool(raw.get("modalOpen"))

        # Clicking a text field is SUPPOSED to give you a caret and nothing
        # else. That is a complete, correct response, and without this the
        # agent reports every search box on the web as a dead control.
        # Deliberately narrow: focus moves on every click, so allowing it for
        # a button would hide exactly the defect this judgement exists to find.
        FIELDS = (ElementKind.TEXT_INPUT, ElementKind.SEARCH_INPUT,
                  ElementKind.EMAIL_INPUT, ElementKind.TEXTAREA)
        focused_field = (
            el is not None and el.kind in FIELDS
            and raw.get("firstFocus") is not None
            and (raw.get("focusRef") or "") == el.ref)

        t = record.timing
        speed = (f"{t.perceived_ms:.0f} ms" if t.perceived_ms is not None
                 else "no visible response")

        if intent.kind in (ActionKind.SCROLL, ActionKind.SCROLL_BACK):
            if not scrolled:
                record.outcome = Outcome.NO_RESPONSE
                record.observed = ("the page did not move — it is not "
                                   "scrollable here, or the scroll was captured")
            else:
                record.outcome = Outcome.SUCCESS
                fps = t.scroll_fps
                record.observed = (
                    f"scrolled {abs(float(raw.get('scrollY') or 0) - float(raw.get('startScroll') or 0)):.0f}px"
                    + (f" at {fps:.0f} fps" if fps is not None else "")
                    + (f", {t.dropped_frames} dropped frames"
                       if t.dropped_frames else ""))
            return

        if intent.kind is ActionKind.READ:
            record.outcome = Outcome.SUCCESS
            record.observed = (f"dwelled on the page; {mutations} changes and "
                               f"{requests} requests arrived unprompted"
                               if mutations or requests else
                               "dwelled on the page; nothing loaded late")
            return

        if intent.kind in (ActionKind.NAVIGATE, ActionKind.BACK):
            record.outcome = (Outcome.SUCCESS if record.url_changed
                              else Outcome.UNEXPECTED)
            record.observed = (f"arrived at {now_url}" if record.url_changed
                               else f"the URL did not change from {start_url}")
            return

        if focused_field and mutations == 0 and requests == 0:
            record.outcome = Outcome.SUCCESS
            latency = record.timing.input_latency_ms
            # For a text field this IS what the user perceives, so it belongs
            # in the perceived clock and therefore in the interaction-speed
            # score. Leaving it out would exclude every "click the search box"
            # from the very component it belongs in.
            record.timing.perceived_ms = latency
            record.timing.ui_response_ms = latency
            record.observed = (
                "the field took focus"
                + (f" in {latency:.0f} ms" if latency is not None else "")
                + " — a caret is the whole of the expected response")
            return

        # Everything else: did anything at all happen?
        if mutations == 0 and requests == 0 and not record.url_changed \
                and not modal and not scrolled:
            record.outcome = Outcome.NO_RESPONSE
            record.observed = (
                "nothing changed — no DOM update, no request, no navigation "
                f"within {self.engine.no_response_ms} ms")
            return

        if record.url_changed:
            record.outcome = Outcome.SUCCESS
            record.observed = f"navigated to {now_url} in {speed}"
            return
        if modal:
            record.outcome = Outcome.SUCCESS
            record.observed = f"a dialog opened in {speed}"
            return
        if mutations:
            record.outcome = Outcome.SUCCESS
            record.observed = (f"{mutations} DOM updates, first visible in "
                               f"{speed}")
            return

        # Requests fired but the interface never showed anything. That is a
        # real experience: the user pressed something and saw nothing.
        record.outcome = Outcome.UNEXPECTED
        record.observed = (f"{requests} request(s) were sent but the interface "
                           "did not visibly change")
