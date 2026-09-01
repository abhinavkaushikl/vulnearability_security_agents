"""The measurement engine — the four clocks, and what happens when one is
missing.

The whole point of this module is that an unobserved metric is None and never
zero, so most of these tests are about the absence of a measurement rather
than the presence of one.
"""
from __future__ import annotations

from app.behaviour.measure import (FRAME_BUDGET_MS, analyse_frames,
                                   compute_timing, frame_p95_ms)


def probe(**over) -> dict:
    base = {
        "t0": 1000.0, "now": 2000.0,
        "firstMutation": None, "lastMutation": None, "firstPaint": None,
        "firstFocus": None, "focusRef": "",
        "mutations": 0, "requests": [], "shift": 0, "longTask": 0,
        "frames": [], "errors": [],
        "startUrl": "https://x.test/", "url": "https://x.test/",
        "startScroll": 0, "scrollY": 0,
    }
    base.update(over)
    return base


# ── nothing observed stays nothing ───────────────────────────────────────

def test_a_dead_control_reports_no_latency_not_a_zero():
    """The finding is 'it never responded'. A 0 would read as 'instantly'."""
    t = compute_timing(probe())
    assert t.ui_response_ms is None
    assert t.perceived_ms is None
    assert t.input_latency_ms is None
    assert t.network_first_byte_ms is None
    assert t.mutation_count == 0


def test_an_unreadable_probe_yields_an_empty_timing():
    t = compute_timing(None)
    assert t.perceived_ms is None
    assert t.mutation_count == 0


def test_events_before_the_action_are_not_responses_to_it():
    """A mutation timestamped before t0 cannot have been caused by t0."""
    t = compute_timing(probe(firstMutation=900.0, mutations=3))
    assert t.ui_response_ms is None
    assert t.perceived_ms is None
    # The count is still reported: something moved, just not because of us.
    assert t.mutation_count == 3


# ── the clocks ───────────────────────────────────────────────────────────

def test_the_paint_is_the_ui_response_and_the_mutation_is_the_fallback():
    t = compute_timing(probe(firstMutation=1120.0, firstPaint=1140.0,
                             mutations=2))
    assert t.ui_response_ms == 140.0
    assert t.perceived_ms == 140.0
    assert t.input_latency_ms == 120.0     # first sign of life, not the paint

    # No post-mutation frame delivered: the mutation timestamp is the best
    # observation we have, and it is used rather than discarded.
    t2 = compute_timing(probe(firstMutation=1120.0, mutations=2))
    assert t2.ui_response_ms == 120.0


def test_network_clocks_come_from_the_requests_the_action_caused():
    t = compute_timing(probe(requests=[
        {"start": 1010.0, "responseStart": 1090.0, "end": 1300.0},
        {"start": 1020.0, "responseStart": 1250.0, "end": 1400.0},
    ]))
    assert t.request_count == 2
    assert t.network_first_byte_ms == 90.0      # earliest first byte
    assert t.network_complete_ms == 400.0       # last response end


def test_a_cross_origin_response_start_of_zero_is_not_an_instant_first_byte():
    """responseStart is 0 without Timing-Allow-Origin. The request START is
    the only honest lower bound, and 0 must never be reported as 0 ms."""
    t = compute_timing(probe(requests=[
        {"start": 1060.0, "responseStart": None, "end": 1500.0},
    ]))
    assert t.network_first_byte_ms == 60.0
    assert t.network_first_byte_ms != 0


def test_perceived_falls_back_to_the_network_when_nothing_painted():
    """This is the 'silent action' signature: the data came back, the
    interface never said so."""
    t = compute_timing(probe(requests=[
        {"start": 1010.0, "responseStart": 1200.0, "end": 1400.0}]))
    assert t.ui_response_ms is None
    assert t.perceived_ms == 200.0


def test_focus_is_a_sign_of_life_but_not_a_ui_response():
    """Focus moves on every click. Counting it as a UI response would give a
    dead button a response time."""
    t = compute_timing(probe(firstFocus=1030.0, focusRef="e4"))
    assert t.input_latency_ms == 30.0
    assert t.ui_response_ms is None


def test_state_completion_is_the_last_mutation_when_the_page_went_quiet():
    t = compute_timing(probe(firstMutation=1100.0, lastMutation=1800.0,
                             mutations=9), state_complete_ms=800.0)
    assert t.state_complete_ms == 800.0


# ── frames ───────────────────────────────────────────────────────────────

def test_a_steady_sixty_fps_scroll_reads_as_sixty():
    frames = [i * FRAME_BUDGET_MS for i in range(60)]
    fps, dropped, worst = analyse_frames(frames)
    assert fps is not None and 59 <= fps <= 61
    assert dropped == 0
    assert worst is not None


def test_one_long_hitch_is_counted_as_dropped_frames():
    frames = [0.0, 16.7, 33.4, 133.4, 150.1, 166.8]
    fps, dropped, worst = analyse_frames(frames)
    assert dropped and dropped >= 5        # a 100 ms gap swallowed ~5 frames
    assert worst == 100.0


def test_too_few_frames_is_not_a_frame_rate():
    """Two timestamps give one interval, and one interval is not an fps."""
    assert analyse_frames([]) == (None, None, None)
    assert analyse_frames([0.0, 16.7]) == (None, None, None)
    assert frame_p95_ms([0.0, 16.7]) is None


def test_the_frame_p95_exposes_jank_a_mean_would_hide():
    """Nine good frames then a stall, repeated. The mean frame time stays
    respectable; the p95 reports what the scroll actually felt like.

    A SINGLE stall in sixty frames is deliberately NOT a p95 — it is a p98 —
    and `analyse_frames` reports that one through `worst` instead. Both are
    kept because they answer different questions: "is this consistently
    janky" and "did it ever stall".
    """
    frames = [0.0]
    for i in range(60):
        frames.append(frames[-1] + (120.0 if i % 10 == 9 else 16.7))
    p95 = frame_p95_ms(frames)
    assert p95 is not None and p95 > 100

    smooth = [i * 16.7 for i in range(60)]
    smooth.append(smooth[-1] + 400.0)
    # One stall does not move the p95 — and must not be made to.
    assert (frame_p95_ms(smooth) or 0) < 30
    # It shows up as the worst frame, which is the honest place for it.
    assert analyse_frames(smooth)[2] == 400.0


def test_scroll_metrics_only_appear_for_scrolls():
    frames = [i * 16.7 for i in range(30)]
    plain = compute_timing(probe(frames=frames))
    assert plain.scroll_fps is None and plain.frame_count is None

    scrolled = compute_timing(probe(frames=frames), is_scroll=True)
    assert scrolled.scroll_fps is not None
    assert scrolled.frame_count == 30
