"use client";

/**
 * The fluid scroll engine — §13.
 *
 * The brief's requirement is specific and easy to get backwards: the page
 * must feel **fast and smooth**, not **slow and smooth**. Those are different
 * settings of the same machine, and most "smooth scroll" implementations pick
 * the wrong one — they lerp the scroll position toward the target with a low
 * coefficient, which literally delays the content behind the user's input.
 * The scroll becomes buttery and the site becomes sluggish.
 *
 * So the position itself stays honest. What we interpolate is the *reaction*:
 *
 *   real scroll position  ──► never delayed, never lerped
 *   scroll VELOCITY       ──► smoothed, and drives every animation
 *
 * Velocity is the signal §13 actually asks for. Scroll hard and elements
 * displace, blur and skew more; ease off and they settle. The content is
 * always exactly where the user put it, and the motion on top of it has
 * momentum. That is what "fast + smooth" means.
 *
 * Everything is written to CSS custom properties on `<html>` from one rAF
 * loop, so React never re-renders on scroll and any number of components can
 * read the same signal without each installing their own listener:
 *
 *   --v      signed velocity, roughly -1..1, smoothed
 *   --va     |velocity|, 0..1 — the one most animations want
 *   --sy     absolute scroll position in px
 *   --sp     scroll progress through the document, 0..1
 *   --dir    +1 down, -1 up
 */

import { useEffect, useRef, useState } from "react";
import { prefersReduced } from "./motion";

/** Critically-damped-ish smoothing. Fast to rise, unhurried to settle. */
const RISE = 0.34;
const FALL = 0.09;
/** Velocity in px/frame that counts as "as fast as anyone scrolls". */
const V_MAX = 78;

let installed = 0;
let raf = 0;

function loop() {
  const root = document.documentElement;
  let sy = window.scrollY;
  let last = sy;
  let v = 0;
  let smooth = 0;

  const frame = () => {
    sy = window.scrollY;
    v = sy - last;
    last = sy;

    const target = Math.max(-1, Math.min(1, v / V_MAX));
    // Asymmetric: react immediately, decay slowly. A symmetric filter either
    // lags the flick or snaps the settle, and both read as cheap.
    const k = Math.abs(target) > Math.abs(smooth) ? RISE : FALL;
    smooth += (target - smooth) * k;
    if (Math.abs(smooth) < 0.0008) smooth = 0;

    const doc = Math.max(1, root.scrollHeight - window.innerHeight);
    root.style.setProperty("--v", smooth.toFixed(4));
    root.style.setProperty("--va", Math.abs(smooth).toFixed(4));
    root.style.setProperty("--sy", `${sy.toFixed(1)}`);
    root.style.setProperty("--sp", (sy / doc).toFixed(4));
    root.style.setProperty("--dir", smooth >= 0 ? "1" : "-1");

    raf = requestAnimationFrame(frame);
  };
  frame();
}

/**
 * Publishes the scroll signal for the whole page. Mount once, near the root.
 * Under reduced motion it publishes zeroes and never starts a loop, so every
 * velocity-driven effect flattens to its resting state on its own.
 */
export function useScrollSignal() {
  useEffect(() => {
    const root = document.documentElement;
    if (prefersReduced()) {
      for (const [k, val] of [["--v", "0"], ["--va", "0"], ["--sy", "0"],
                              ["--sp", "0"], ["--dir", "1"]] as const) {
        root.style.setProperty(k, val);
      }
      return;
    }
    if (installed++ === 0) loop();
    return () => {
      if (--installed === 0) cancelAnimationFrame(raf);
    };
  }, []);
}

/**
 * Section interpolation: how far this element is through the viewport,
 * -1 (just below the fold) → 0 (centred) → 1 (just above it).
 *
 * Written straight to a CSS variable on the element, so a section can drive
 * its own parallax in CSS without React participating in the scroll at all.
 */
export function useSectionProgress<T extends HTMLElement>(varName = "--p") {
  const ref = useRef<T>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || prefersReduced()) return;
    let frame = 0;
    let visible = false;

    const io = new IntersectionObserver(
      ([e]) => { visible = e.isIntersecting; },
      { rootMargin: "40% 0px 40% 0px" },
    );
    io.observe(el);

    const tick = () => {
      if (visible) {
        const r = el.getBoundingClientRect();
        const centre = r.top + r.height / 2;
        const p = 1 - (centre / (window.innerHeight / 2));
        el.style.setProperty(varName, Math.max(-1.4, Math.min(1.4, p)).toFixed(4));
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(frame);
      io.disconnect();
    };
  }, [varName]);

  return ref;
}

/**
 * A spring that follows a moving target. Unlike `useSpringNumber`, which
 * animates once to a fixed value, this tracks a value that keeps changing —
 * a live latency readout, a counter climbing during a run — without ever
 * snapping.
 */
export function useFollowingSpring(target: number, stiffness = 0.14,
                                   damping = 0.75) {
  const [value, setValue] = useState(target);
  const state = useRef({ x: target, v: 0 });

  useEffect(() => {
    if (prefersReduced()) {
      setValue(target);
      return;
    }
    let frame = 0;
    const step = () => {
      const s = state.current;
      s.v = (s.v + (target - s.x) * stiffness) * damping;
      s.x += s.v;
      if (Math.abs(target - s.x) < 0.01 && Math.abs(s.v) < 0.01) {
        s.x = target;
        s.v = 0;
        setValue(target);
        return;
      }
      setValue(s.x);
      frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [target, stiffness, damping]);

  return value;
}

/**
 * Lenis settings that keep the wheel FAST while still gliding.
 *
 * `lerp` over `duration` on purpose: a duration-based smooth scroll takes the
 * same time for a nudge as for a flick, which is exactly the "slow + smooth"
 * failure §13 warns about. A high lerp reaches the target in a few frames —
 * enough to kill the step-jitter of a raw wheel event, not enough to be felt
 * as latency. `wheelMultiplier` above 1 puts the speed back that any
 * smoothing costs.
 */
export const LENIS_FAST = {
  lerp: 0.135,
  wheelMultiplier: 1.18,
  touchMultiplier: 1.9,
  smoothWheel: true,
  syncTouch: false,
} as const;
