"use client";

import { useEffect, useRef, useState } from "react";

/**
 * A white dot that trails the pointer, and expands into a label over anything
 * that declares one via data-cursor. Written against rAF and transforms only —
 * a React state update per pointermove would drop frames on its own.
 */
export default function Cursor() {
  const dot = useRef<HTMLDivElement>(null);
  const [label, setLabel] = useState<string | null>(null);
  const [down, setDown] = useState(false);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const fine = window.matchMedia("(hover: hover) and (pointer: fine)").matches;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!fine) {
      document.body.classList.remove("aq-cursor");
      return;
    }

    const pos = { x: innerWidth / 2, y: innerHeight / 2 };
    const cur = { ...pos };
    let raf = 0;

    const move = (e: PointerEvent) => {
      pos.x = e.clientX;
      pos.y = e.clientY;
      setVisible(true);

      const el = (e.target as HTMLElement)?.closest?.("[data-cursor]");
      setLabel(el ? el.getAttribute("data-cursor") : null);
    };

    const frame = () => {
      // Lower stiffness than the element springs, so the dot reads as lighter.
      const k = reduced ? 1 : 0.22;
      cur.x += (pos.x - cur.x) * k;
      cur.y += (pos.y - cur.y) * k;
      if (dot.current) {
        dot.current.style.transform =
          `translate3d(${cur.x}px, ${cur.y}px, 0) translate(-50%, -50%)`;
      }
      raf = requestAnimationFrame(frame);
    };
    frame();

    const dn = () => setDown(true);
    const up = () => setDown(false);
    const leave = () => setVisible(false);

    window.addEventListener("pointermove", move, { passive: true });
    window.addEventListener("pointerdown", dn);
    window.addEventListener("pointerup", up);
    document.addEventListener("pointerleave", leave);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerdown", dn);
      window.removeEventListener("pointerup", up);
      document.removeEventListener("pointerleave", leave);
    };
  }, []);

  return (
    <div
      ref={dot}
      aria-hidden
      className="pointer-events-none fixed left-0 top-0 z-[100] will-change-transform"
      style={{ opacity: visible ? 1 : 0, transition: "opacity 200ms" }}
    >
      <div
        className="flex items-center justify-center whitespace-nowrap rounded-full border transition-[width,height,background-color,border-color] duration-300"
        style={{
          width: label ? "auto" : down ? 6 : 9,
          height: label ? 26 : down ? 6 : 9,
          paddingInline: label ? 12 : 0,
          background: label ? "transparent" : "var(--color-bone)",
          borderColor: label ? "var(--color-phos)" : "transparent",
          transitionTimingFunction: "var(--ease-spring)",
        }}
      >
        {label && (
          <span
            className="mono"
            style={{ color: "var(--color-phos)", fontSize: "0.625rem" }}
          >
            {label}
          </span>
        )}
      </div>
    </div>
  );
}
