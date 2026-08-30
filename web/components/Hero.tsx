"use client";

import { useEffect, useRef } from "react";
import { prefersReduced } from "@/lib/motion";

/**
 * Per-word displacement on pointer proximity. Words, not letters: per-letter
 * spans on a headline this size cost ~60 nodes and read as a gimmick at speed.
 */
function DisplaceLine({ text, className }: { text: string; className?: string }) {
  const host = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const el = host.current;
    if (!el || prefersReduced()) return;
    const words = Array.from(el.querySelectorAll<HTMLElement>("[data-w]"));
    const state = words.map(() => ({ x: 0, y: 0, tx: 0, ty: 0 }));
    let raf = 0;

    const move = (e: PointerEvent) => {
      words.forEach((w, i) => {
        const r = w.getBoundingClientRect();
        const dx = e.clientX - (r.left + r.width / 2);
        const dy = e.clientY - (r.top + r.height / 2);
        const d = Math.hypot(dx, dy);
        const reach = 220;
        if (d < reach) {
          const f = (1 - d / reach) ** 2 * 14;
          state[i].tx = (-dx / (d || 1)) * f;
          state[i].ty = (-dy / (d || 1)) * f;
        } else {
          state[i].tx = 0;
          state[i].ty = 0;
        }
      });
    };

    const frame = () => {
      words.forEach((w, i) => {
        const s = state[i];
        s.x += (s.tx - s.x) * 0.09;
        s.y += (s.ty - s.y) * 0.09;
        w.style.transform = `translate3d(${s.x.toFixed(2)}px, ${s.y.toFixed(2)}px, 0)`;
      });
      raf = requestAnimationFrame(frame);
    };
    frame();

    window.addEventListener("pointermove", move, { passive: true });
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("pointermove", move);
    };
  }, []);

  return (
    <span ref={host} className={className}>
      {text.split(" ").map((w, i) => (
        <span key={i} data-w className="inline-block will-change-transform">
          {w}
          {i < text.split(" ").length - 1 ? " " : ""}
        </span>
      ))}
    </span>
  );
}

export default function Hero() {
  return (
    <header className="relative flex flex-col items-center px-6 pt-24 text-center md:pt-32">
      <div className="mono flex items-center gap-3">
        <span
          className="inline-block h-1.5 w-1.5 rounded-full"
          style={{ background: "var(--color-phos)" }}
        />
        AgentQA
        <span style={{ color: "var(--color-dim)" }}>//</span>
        AI website security &amp; behavioral analysis
      </div>

      <h1 className="h-display mt-10 max-w-[16ch] text-[clamp(2.75rem,8vw,6.5rem)]">
        <DisplaceLine text="Send an AI agent" className="block" />
        <DisplaceLine
          text="into your website."
          className="block"
        />
      </h1>

      <p
        className="mt-8 max-w-[42ch] text-balance text-[clamp(1rem,1.7vw,1.25rem)] leading-relaxed"
        style={{ color: "var(--color-ash)" }}
      >
        It walks the site like a real user, collects only the evidence the rule
        pack asks for, and tells you plainly which of{" "}
        <span style={{ color: "var(--color-bone)" }}>144 controls</span> it could
        actually decide.
      </p>
    </header>
  );
}
