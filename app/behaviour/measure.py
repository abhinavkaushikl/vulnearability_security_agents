"""Measurement Engine — three clocks, none of them invented.

§10 of the brief is the reason this module exists separately from the
executor. "How fast is the site?" has at least three different answers and
they routinely disagree by an order of magnitude:

    dispatch ──► something reacted            input latency
             ──► the user could SEE it        UI response
             ──► the request came back        network response
             ──► the page stopped changing    state completion

A button whose network call returns in 90 ms but whose spinner does not
appear for 600 ms is a slow button, and only the second clock says so.

Everything here is pure arithmetic over timestamps the page reported. The
model is never asked for a number, and a number the page did not report is
`None` — never zero. A zero would read as "instantaneous", which is the
opposite of the truth when the truth is "it never responded".
"""
from __future__ import annotations

import logging

from playwright.async_api import Page

from app.behaviour import js
from app.behaviour.models import InteractionTiming
from app.tools.statistics import calculate_percentile

log = logging.getLogger(__name__)

#: A frame budget at 60 Hz. Used only to estimate dropped frames; the FPS
#: figure itself is measured, not derived from this.
FRAME_BUDGET_MS = 1000.0 / 60.0


def _rel(value: float | None, t0: float) -> float | None:
    """A page timestamp as a latency, or None. Negative means 'before the
    action', which is not a response to it."""
    if value is None:
        return None
    delta = float(value) - float(t0)
    return round(delta, 1) if delta >= 0 else None


def analyse_frames(frames: list[float]) -> tuple[float | None, int | None, float | None]:
    """(fps, dropped, worst_frame_ms) from raw rAF timestamps.

    Fewer than three frames is not a sample: two timestamps give one interval,
    and one interval is not a frame rate. Returns Nones rather than a figure
    nobody should quote.
    """
    if len(frames) < 3:
        return None, None, None
    deltas = [b - a for a, b in zip(frames, frames[1:]) if b > a]
    if not deltas:
        return None, None, None
    span = frames[-1] - frames[0]
    if span <= 0:
        return None, None, None
    fps = round((len(frames) - 1) * 1000.0 / span, 1)
    # Each interval longer than one budget swallowed that many whole frames.
    dropped = sum(max(0, int(d / FRAME_BUDGET_MS) - 1) for d in deltas)
    worst = round(max(deltas), 1)
    return fps, dropped, worst


def frame_p95_ms(frames: list[float]) -> float | None:
    """The 95th percentile frame interval — what the stutter actually felt like.

    A mean frame time hides a single 400 ms hitch inside 200 good frames; the
    p95 does not. Uses the same percentile implementation the performance
    engine uses, so the two agree by construction.
    """
    if len(frames) < 3:
        return None
    deltas = [b - a for a, b in zip(frames, frames[1:]) if b > a]
    if not deltas:
        return None
    p = calculate_percentile(deltas, 95)
    return round(p, 1) if p is not None else None


def compute_timing(raw: dict | None, *, is_scroll: bool = False,
                   state_complete_ms: float | None = None) -> InteractionTiming:
    """Reduce one probe reading to the four clocks. Pure."""
    t = InteractionTiming()
    if not raw:
        return t

    t0 = raw.get("t0")
    if t0 is None:
        return t

    t.mutation_count = int(raw.get("mutations") or 0)

    ui = _rel(raw.get("firstPaint"), t0)
    first_mut = _rel(raw.get("firstMutation"), t0)
    focus_ms = _rel(raw.get("firstFocus"), t0)
    # The paint clock is the honest UI response. When the browser never
    # delivered the post-mutation frame (a background tab, a throttled
    # renderer), the mutation timestamp is the closest thing we observed.
    t.ui_response_ms = ui if ui is not None else first_mut

    requests = [r for r in (raw.get("requests") or [])
                if isinstance(r, dict) and r.get("start") is not None
                and float(r["start"]) >= float(t0) - 2]
    t.request_count = len(requests)

    if requests:
        first_bytes = [_rel(r.get("responseStart"), t0) for r in requests]
        first_bytes = [v for v in first_bytes if v is not None]
        if first_bytes:
            t.network_first_byte_ms = min(first_bytes)
        else:
            # Cross-origin without Timing-Allow-Origin: responseStart is
            # unreadable. The request start is the only honest lower bound.
            starts = [_rel(r.get("start"), t0) for r in requests]
            starts = [v for v in starts if v is not None]
            t.network_first_byte_ms = min(starts) if starts else None
        ends = [_rel(r.get("end"), t0) for r in requests]
        ends = [v for v in ends if v is not None]
        t.network_complete_ms = max(ends) if ends else None

    # The first sign of life, whichever channel produced it. Focus counts
    # here — the caret appearing IS the page reacting — but it deliberately
    # does not feed `ui_response_ms`, because focus moves on every click and
    # would otherwise give a dead button a response time.
    candidates = [v for v in (first_mut, focus_ms, t.network_first_byte_ms,
                              _rel(min((r["start"] for r in requests),
                                       default=None), t0) if requests else None)
                  if v is not None]
    t.input_latency_ms = min(candidates) if candidates else None

    # What a user would call "it responded": what they could see, and only
    # failing that, what came back over the wire.
    t.perceived_ms = (t.ui_response_ms if t.ui_response_ms is not None
                      else t.network_first_byte_ms)

    if state_complete_ms is not None:
        t.state_complete_ms = round(state_complete_ms, 1)
    else:
        last = _rel(raw.get("lastMutation"), t0)
        t.state_complete_ms = last

    shift = raw.get("shift")
    t.layout_shift = round(float(shift), 4) if shift else (0.0 if shift == 0 else None)
    long_task = raw.get("longTask")
    t.long_task_ms = round(float(long_task), 1) if long_task else None

    if is_scroll:
        frames = [float(f) for f in (raw.get("frames") or [])]
        fps, dropped, _worst = analyse_frames(frames)
        t.frame_count = len(frames) or None
        t.scroll_fps = fps
        t.dropped_frames = dropped
    return t


class MeasurementEngine:
    """Owns the probe lifecycle around one dispatched action."""

    def __init__(self, *, quiet_ms: int = 260, max_settle_ms: int = 4500,
                 poll_ms: int = 90, no_response_ms: int = 2500,
                 isolate_ms: int = 1600):
        #: How long the DOM must be still before we call the state complete.
        self.quiet_ms = quiet_ms
        #: Hard ceiling. A page that never quiesces (a carousel, a ticker)
        #: must not hold the agent forever; it is reported as such instead.
        self.max_settle_ms = max_settle_ms
        self.poll_ms = poll_ms
        #: How long to wait with NOTHING moving before concluding the control
        #: is dead. This is not the same as `quiet_ms` and must be much larger:
        #: a debounced search box that responds 620 ms after the last keystroke
        #: has not failed, it is debounced, and a short patience here reports
        #: every debounced control on the web as broken.
        self.no_response_ms = no_response_ms
        #: How long to wait for the page to go still BEFORE dispatching. See
        #: `isolate()`.
        self.isolate_ms = isolate_ms

    async def install(self, page: Page) -> bool:
        try:
            await page.evaluate(js.PROBE_INSTALL)
            return True
        except Exception as exc:                                # noqa: BLE001
            log.debug("probe install failed: %s", exc)
            return False

    async def mark(self, page: Page) -> None:
        """Stamp t0 as late as possible before dispatch, clearing what came
        before it. See js.PROBE_MARK."""
        try:
            await page.evaluate(js.PROBE_MARK)
        except Exception:                                       # noqa: BLE001
            pass

    async def isolate(self, page: Page) -> bool:
        """Wait for the page to stop moving before the next action is dispatched.

        This is the difference between measuring an interaction and measuring
        the previous one's tail. Deferred work — a 600 ms debounce, a late
        banner, an animation finishing — lands whenever it lands, and if the
        agent presses the next control while it is still in flight, the probe
        attributes that work to the new action. The visible symptom is
        specific and misleading in both directions: a dead button gets
        credited with a response it did not cause, and a genuinely slow
        control looks instant.

        A person waits for a page to settle before clicking the next thing.
        So does the agent, and for the same reason.

        Returns whether the page actually went still within the budget.
        """
        waited = 0
        last_count = -1
        stable_for = 0
        while waited < self.isolate_ms:
            reading = await self.read(page)
            if reading is None:
                return True                # no probe: nothing to wait for
            count = int(reading.get("mutations") or 0)
            if count == last_count:
                stable_for += self.poll_ms
                if stable_for >= self.quiet_ms:
                    return True
            else:
                stable_for = 0
                last_count = count
            await page.wait_for_timeout(self.poll_ms)
            waited += self.poll_ms
        return False

    async def start_frames(self, page: Page) -> None:
        try:
            await page.evaluate(js.PROBE_FRAMES_START)
        except Exception:                                       # noqa: BLE001
            pass

    async def stop_frames(self, page: Page) -> None:
        try:
            await page.evaluate(js.PROBE_FRAMES_STOP)
        except Exception:                                       # noqa: BLE001
            pass

    async def read(self, page: Page) -> dict | None:
        try:
            return await page.evaluate(js.PROBE_READ)
        except Exception as exc:                                # noqa: BLE001
            log.debug("probe read failed: %s", exc)
            return None

    async def settle(self, page: Page) -> tuple[dict | None, float | None, bool]:
        """Poll until the DOM is quiet, or the ceiling is reached.

        Returns (last reading, state completion in ms, quiesced?). The third
        value matters: a page still mutating at the ceiling has no observed
        completion time, and saying so is more useful than reporting the
        ceiling as if it were a measurement.
        """
        waited = 0
        last: dict | None = None
        while waited < self.max_settle_ms:
            await page.wait_for_timeout(self.poll_ms)
            waited += self.poll_ms
            last = await self.read(page)
            if last is None:
                return None, None, False
            t0 = last.get("t0")
            last_mut = last.get("lastMutation")
            now = last.get("now")
            if t0 is None or now is None:
                continue
            if last_mut is None:
                # Nothing has moved yet. Wait the full no-response patience
                # before concluding the control is dead — a debounced handler
                # has not failed just because it has not fired yet.
                if now - t0 >= self.no_response_ms:
                    return last, None, True
                continue
            if now - last_mut >= self.quiet_ms:
                return last, float(last_mut) - float(t0), True
        return last, None, False

    async def navigation_timing(self, page: Page) -> InteractionTiming:
        """Measure a document replacement, where the in-page probe cannot survive.

        A navigation destroys the JavaScript context, taking `window.__aq` with
        it. Polling the probe afterwards reads `null` and would report the
        navigation as "the probe could not be read" — which is how a working
        link ends up counted as an inconclusive interaction.

        So a navigation is measured from the NEW document's own navigation
        timing instead, and the four clocks are mapped onto what that actually
        means for a person:

            input latency  = TTFB          the server started answering
            UI response    = FCP           the user saw the new page
            network        = TTFB..load
            state complete = load          the page stopped loading

        All of it is still observed rather than derived, and anything the
        browser did not report stays None.
        """
        t = InteractionTiming()
        try:
            v = await page.evaluate(js.VITALS)
        except Exception as exc:                                # noqa: BLE001
            log.debug("navigation timing unavailable: %s", exc)
            return t
        if not v:
            return t
        ttfb = v.get("ttfb")
        fcp = v.get("fcp")
        lcp = v.get("lcp")
        load = v.get("load")
        t.input_latency_ms = round(ttfb, 1) if ttfb else None
        t.network_first_byte_ms = t.input_latency_ms
        t.network_complete_ms = round(load, 1) if load else None
        t.ui_response_ms = round(fcp, 1) if fcp else (
            round(lcp, 1) if lcp else None)
        t.state_complete_ms = t.network_complete_ms
        t.perceived_ms = t.ui_response_ms or t.input_latency_ms
        t.request_count = int(v.get("requests") or 0)
        shift = v.get("cls")
        t.layout_shift = round(float(shift), 4) if shift is not None else None
        return t

    async def stop(self, page: Page) -> None:
        try:
            await page.evaluate(js.PROBE_STOP)
        except Exception:                                       # noqa: BLE001
            pass
