"use client";

import { useSpringNumber, useInView } from "@/lib/motion";
import type { Tally } from "@/lib/types";

/**
 * A radial tick field, not a donut. 144 ticks — one per control — so the
 * reader can see at a glance how much of the pack a browser could reach.
 * Amber ticks were decided; dim ticks were not, and that gap is the point.
 */
export default function CoverageDial({
  coverage,
  tally,
}: {
  coverage: number;
  tally: Tally;
}) {
  const [ref, seen] = useInView<HTMLDivElement>();
  const v = useSpringNumber(coverage, seen, 0.055, 100);
  const lit = useSpringNumber(tally.total - tally.unknown, seen, 0.055, tally.total);

  const TICKS = tally.total || 144;
  const R = 132;
  const decidedTicks = Math.round((lit / TICKS) * TICKS);

  return (
    <div ref={ref} className="relative grid place-items-center">
      <svg viewBox="-160 -160 320 320" className="w-[min(84vw,340px)]" aria-hidden>
        {Array.from({ length: TICKS }).map((_, i) => {
          const a = (i / TICKS) * Math.PI * 2 - Math.PI / 2;
          const on = i < decidedTicks;
          const len = on ? 16 : 8;
          const x1 = Math.cos(a) * R;
          const y1 = Math.sin(a) * R;
          const x2 = Math.cos(a) * (R + len);
          const y2 = Math.sin(a) * (R + len);
          return (
            <line
              key={i}
              x1={x1} y1={y1} x2={x2} y2={y2}
              stroke={on ? "var(--color-phos)" : "var(--color-line-lit)"}
              strokeWidth={on ? 2 : 1}
              opacity={on ? 0.95 : 0.5}
            />
          );
        })}
        <circle r={R - 6} fill="none" stroke="var(--color-line)" strokeWidth="1" />
      </svg>

      <div className="absolute grid place-items-center text-center">
        <p className="mono mb-1">Coverage</p>
        <p
          className="h-display tabular-nums text-[clamp(3.5rem,11vw,5.5rem)]"
          style={{ color: "var(--color-phos)" }}
        >
          {v.toFixed(1)}
          <span className="text-[0.34em]" style={{ color: "var(--color-ash)" }}>
            %
          </span>
        </p>
        <p className="mono mt-1" style={{ letterSpacing: "0.1em" }}>
          {Math.round(lit)} of {tally.total} decided
        </p>
      </div>
    </div>
  );
}
