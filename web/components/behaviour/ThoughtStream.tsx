"use client";

import { useEffect, useRef } from "react";
import type { Thought } from "@/lib/behaviourTypes";

/**
 * §16 — what the agent is doing, without exposing how it decided.
 *
 * Three statements per entry: what was on screen, what was dispatched, what
 * came back. They are assembled in Python from an `ActionRecord`
 * (`agent.py :: _think`), not narrated by the model, so nothing here can
 * describe an action the agent did not take or a latency it did not measure.
 *
 * Newest first. A live feed that appends downward asks the reader to chase
 * it, and during a fast run they will lose.
 */
export default function ThoughtStream({ thoughts }: { thoughts: Thought[] }) {
  const list = useRef<HTMLOListElement>(null);
  const count = useRef(thoughts.length);

  useEffect(() => {
    if (thoughts.length !== count.current) count.current = thoughts.length;
  }, [thoughts.length]);

  const recent = thoughts.slice(-7).reverse();

  return (
    <div>
      <p className="mono mb-4" style={{ color: "var(--color-dim)" }}>
        agent log //
      </p>
      <ol ref={list} className="grid gap-5" aria-live="polite" aria-atomic="false">
        {recent.length === 0 && (
          <li className="mono" style={{ color: "var(--color-dim)" }}>
            waiting for the first observation…
          </li>
        )}
        {recent.map((t, i) => {
          const colour =
            t.ok === false ? "var(--color-anomaly)"
            : t.ok === true ? "var(--color-phos)"
            : "var(--color-dim)";
          return (
            <li
              key={t.seq}
              style={{
                // The newest entry arrives at full strength; older ones recede
                // rather than disappear, so the run reads as a trail.
                opacity: 1 - i * 0.13,
                animation: i === 0 ? "aq-thought 520ms var(--ease-spring) both"
                                   : undefined,
              }}
            >
              <div className="grid gap-1.5 border-l pl-4"
                   style={{ borderColor: colour }}>
                <p className="mono" style={{ color: "var(--color-dim)" }}>
                  observation
                </p>
                <p className="text-[0.92rem] leading-snug"
                   style={{ color: "var(--color-ash)" }}>
                  {t.observation}
                </p>

                <p className="mono mt-2" style={{ color: "var(--color-dim)" }}>
                  action
                </p>
                <p className="text-[0.98rem] leading-snug"
                   style={{ color: "var(--color-bone)" }}>
                  {t.action}
                </p>

                {t.result && (
                  <>
                    <p className="mono mt-2" style={{ color: "var(--color-dim)" }}>
                      result
                    </p>
                    <p className="text-[0.92rem] leading-snug" style={{ color: colour }}>
                      {t.result}
                      {t.latency_ms !== null && (
                        <span className="mono ml-2 tabular-nums">
                          {t.latency_ms.toFixed(0)}ms
                        </span>
                      )}
                    </p>
                  </>
                )}
              </div>
            </li>
          );
        })}
      </ol>

      <style jsx>{`
        @keyframes aq-thought {
          from { opacity: 0; transform: translateY(-10px); }
          to   { opacity: 1; transform: none; }
        }
        @media (prefers-reduced-motion: reduce) {
          li { animation: none !important; }
        }
      `}</style>
    </div>
  );
}
