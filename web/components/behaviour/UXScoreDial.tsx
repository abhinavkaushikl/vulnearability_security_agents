"use client";

import type { UXScore } from "@/lib/behaviourTypes";
import { BAND_COLOR } from "@/lib/behaviourTypes";
import { useInView, useSpringNumber } from "@/lib/motion";

/**
 * §17 — the UX score, and every component that went into it.
 *
 * The design constraint here is the backend's, not a stylistic one: a
 * component with no observations has `score === null`, and it must render as
 * an absence rather than as a zero. A dial that draws 0% for "not measured"
 * is the single most misleading thing this interface could do, so the bar for
 * an unrated component is drawn as an inert rule and labelled.
 */
export default function UXScoreDial({ score }: { score: UXScore }) {
  const [ref, seen] = useInView<HTMLDivElement>();
  const value = useSpringNumber(score.overall ?? 0, seen && score.overall !== null,
                                0.07, 100);
  const colour = BAND_COLOR[score.band];
  const R = 78;
  const C = 2 * Math.PI * R;

  return (
    <div ref={ref} className="grid gap-12 lg:grid-cols-[auto_1fr] lg:gap-16">
      {/* ── the number ────────────────────────────────────────────────── */}
      <div className="relative grid place-items-center justify-self-center">
        <svg viewBox="0 0 200 200" className="h-[210px] w-[210px] -rotate-90">
          <circle cx="100" cy="100" r={R} fill="none"
                  stroke="var(--color-line)" strokeWidth="1" />
          {score.overall !== null && (
            <circle
              cx="100" cy="100" r={R} fill="none" stroke={colour}
              strokeWidth="2" strokeLinecap="butt"
              strokeDasharray={C}
              strokeDashoffset={C - (C * Math.min(100, value)) / 100}
              style={{ transition: "stroke 600ms" }}
            />
          )}
        </svg>
        <div className="absolute grid place-items-center text-center">
          {score.overall === null ? (
            <>
              <p className="h-display text-[2.4rem]" style={{ color: "var(--color-dim)" }}>
                —
              </p>
              <p className="mono mt-2">unrated</p>
            </>
          ) : (
            <>
              <p className="h-display tabular-nums text-[clamp(3rem,8vw,4.2rem)]"
                 style={{ color: colour }}>
                {Math.round(value)}
              </p>
              <p className="mono" style={{ color: "var(--color-dim)" }}>/100</p>
              <p className="mono mt-3" style={{ color: colour }}>{score.band}</p>
            </>
          )}
        </div>
      </div>

      {/* ── the components ───────────────────────────────────────────── */}
      <div className="grid content-center gap-5">
        {score.components.map((c, i) => {
          const unrated = c.score === null;
          return (
            <div key={c.name} className="grid gap-1.5">
              <div className="grid grid-cols-[1fr_auto] items-baseline gap-4">
                <span style={{ color: unrated ? "var(--color-dim)"
                                              : "var(--color-bone)" }}>
                  {c.name}
                </span>
                <span className="mono tabular-nums"
                      style={{ color: unrated ? "var(--color-dim)"
                                              : "var(--color-bone)" }}>
                  {unrated ? "not measured" : c.score}
                  <span style={{ color: "var(--color-dim)" }}> · n={c.n}</span>
                </span>
              </div>
              <span className="relative block h-[2px]"
                    style={{ background: "var(--color-line)" }}>
                {!unrated && (
                  <span
                    className="absolute inset-y-0 left-0 block"
                    style={{
                      width: seen ? `${c.score}%` : "0%",
                      background: (c.score ?? 0) < 50 ? "var(--color-anomaly)"
                                                      : "var(--color-phos)",
                      transition: `width 1200ms ${180 + i * 90}ms var(--ease-spring)`,
                    }}
                  />
                )}
              </span>
              <p className="mono leading-relaxed" style={{ color: "var(--color-dim)",
                 letterSpacing: "0.06em", textTransform: "none" }}>
                {c.basis}
              </p>
            </div>
          );
        })}
        <p className="mono mt-2 leading-relaxed"
           style={{ color: "var(--color-dim)", textTransform: "none",
                    letterSpacing: "0.05em" }}>
          {score.method}.
        </p>
      </div>
    </div>
  );
}
