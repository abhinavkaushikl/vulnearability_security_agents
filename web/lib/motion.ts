"use client";

import { useEffect, useRef, useState } from "react";

export function prefersReduced() {
  if (typeof window === "undefined") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * Pulls an element toward the pointer while it is nearby, then lets it spring
 * back. Transform is written directly — this never re-renders React.
 */
export function useMagnetic<T extends HTMLElement>(strength = 0.35, radius = 120) {
  const ref = useRef<T>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || prefersReduced()) return;

    const target = { x: 0, y: 0 };
    const cur = { x: 0, y: 0 };
    let raf = 0;

    const move = (e: PointerEvent) => {
      const r = el.getBoundingClientRect();
      const cx = r.left + r.width / 2;
      const cy = r.top + r.height / 2;
      const dx = e.clientX - cx;
      const dy = e.clientY - cy;
      const dist = Math.hypot(dx, dy);
      if (dist < radius + Math.max(r.width, r.height) / 2) {
        target.x = dx * strength;
        target.y = dy * strength;
      } else {
        target.x = 0;
        target.y = 0;
      }
    };

    const frame = () => {
      cur.x += (target.x - cur.x) * 0.14;
      cur.y += (target.y - cur.y) * 0.14;
      el.style.transform = `translate3d(${cur.x.toFixed(2)}px, ${cur.y.toFixed(2)}px, 0)`;
      raf = requestAnimationFrame(frame);
    };
    frame();

    window.addEventListener("pointermove", move, { passive: true });
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("pointermove", move);
    };
  }, [strength, radius]);

  return ref;
}

/**
 * Counts to `to` under a real spring rather than a duration, so the number
 * overshoots slightly and settles. Reduced motion jumps straight to the value.
 */
export function useSpringNumber(
  to: number,
  active: boolean,
  stiffness = 0.08,
  /** Springs overshoot by design; a percentage must not read as 104%. */
  max?: number,
) {
  const [v, setV] = useState(0);

  useEffect(() => {
    if (!active) return;
    if (prefersReduced()) {
      setV(to);
      return;
    }
    let x = 0;
    let velocity = 0;
    let raf = 0;
    const step = () => {
      const force = (to - x) * stiffness;
      velocity = (velocity + force) * 0.82;
      x += velocity;
      if (Math.abs(to - x) < 0.02 && Math.abs(velocity) < 0.02) {
        setV(to);
        return;
      }
      setV(max === undefined ? x : Math.min(x, max));
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [to, active, stiffness, max]);

  return v;
}

/** Fires once when the element first crosses into view. */
export function useInView<T extends HTMLElement>(margin = "-12%") {
  const ref = useRef<T>(null);
  const [seen, setSeen] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el || seen) return;
    const io = new IntersectionObserver(
      ([e]) => e.isIntersecting && setSeen(true),
      { rootMargin: margin },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [seen, margin]);

  return [ref, seen] as const;
}
