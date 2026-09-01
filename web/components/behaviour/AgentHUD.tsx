"use client";

import type { AgentState, BehaviourProgress } from "@/lib/behaviourTypes";
import { AGENT_STATES, STATE_LINE } from "@/lib/behaviourTypes";
import { useFollowingSpring } from "@/lib/fluid";

/**
 * §15 — live telemetry, as a minimal black interface rather than a dashboard.
 *
 * Every number here is read from the run: `requests` comes straight off the
 * TrafficBudget, so the figure on screen is the number of requests the target
 * actually received. `pct` is the only interpolated value in the whole feed
 * and it never touches a measurement — the same rule `app/api/progress.py`
 * states for the security pipeline.
 */

function Readout({ label, value, unit, muted }: {
  label: string; value: number | null; unit?: string; muted?: boolean;
}) {
  const springs = useFollowingSpring(value ?? 0);
  return (
    <div>
      <p className="mono" style={{ color: "var(--color-dim)" }}>{label}</p>
      <p
        className="h-display tabular-nums text-[clamp(1.3rem,3vw,2rem)]"
        style={{ color: muted ? "var(--color-dim)" : "var(--color-bone)" }}
      >
        {value === null ? "—" : Math.round(springs).toLocaleString()}
        {value !== null && unit && (
          <span className="mono ml-1" style={{ color: "var(--color-dim)" }}>
            {unit}
          </span>
        )}
      </p>
    </div>
  );
}

export default function AgentHUD({ progress, target, live }: {
  progress: BehaviourProgress;
  target: string;
  live: boolean;
}) {
  const host = (() => {
    try { return new URL(target).host; } catch { return target; }
  })();

  const stateIndex = AGENT_STATES.indexOf(progress.state);

  return (
    <div className="grid gap-8">
      {/* ── identity ─────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-baseline justify-between gap-4">
        <div>
          <p className="mono" style={{ color: "var(--color-dim)" }}>target //</p>
          <p className="h-display text-[clamp(1.2rem,3vw,1.8rem)]">{host}</p>
        </div>
        <div className="flex items-center gap-2">
          <span
            className="block h-2 w-2 rounded-full"
            style={{
              background: progress.state === "BLOCKED"
                ? "var(--color-anomaly)" : "var(--color-phos)",
              animation: "aq-pulse 1.5s ease-in-out infinite",
            }}
          />
          <span className="mono" style={{ color: "var(--color-bone)" }}>
            {progress.state}
          </span>
        </div>
      </div>

      {/* ── the state machine, §26 ───────────────────────────────────── */}
      <div className="flex flex-wrap gap-x-3 gap-y-2" aria-hidden>
        {AGENT_STATES.map((s, i) => (
          <span
            key={s}
            className="mono"
            style={{
              color: s === progress.state ? "var(--color-phos)"
                   : i < stateIndex ? "var(--color-ash)"
                   : "var(--color-dim)",
              transition: "color 420ms",
            }}
          >
            {s}
            {i < AGENT_STATES.length - 1 && (
              <span style={{ color: "var(--color-line-lit)" }}> · </span>
            )}
          </span>
        ))}
      </div>

      {/* ── what it is doing right now ───────────────────────────────── */}
      <div className="grid gap-3">
        <div>
          <p className="mono" style={{ color: "var(--color-dim)" }}>
            current objective
          </p>
          <p className="text-[clamp(1rem,2.2vw,1.35rem)] leading-snug">
            {progress.objective || STATE_LINE[progress.state]}
          </p>
        </div>
        <div>
          <p className="mono" style={{ color: "var(--color-dim)" }}>
            current action
          </p>
          <p style={{ color: "var(--color-ash)" }}>
            {progress.current_action || STATE_LINE[progress.state]}
          </p>
        </div>
      </div>

      {/* ── the rail ─────────────────────────────────────────────────── */}
      <div>
        <span className="relative block h-px w-full"
              style={{ background: "var(--color-line)" }}>
          <span
            className="absolute inset-y-0 left-0 block"
            style={{
              width: `${Math.min(100, progress.pct)}%`,
              background: "var(--color-phos)",
              transition: "width 700ms var(--ease-spring)",
            }}
          />
        </span>
      </div>

      {/* ── telemetry ────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-6 sm:grid-cols-3 lg:grid-cols-5">
        <Readout label="actions" value={progress.actions_dispatched} />
        <Readout label="pages visited" value={progress.pages_visited} />
        <Readout label="interactions" value={progress.interactions} />
        <Readout label="avg response" value={progress.avg_response_ms} unit="ms" />
        <Readout label="requests sent" value={progress.requests} />
      </div>

      <p className="mono" style={{ color: "var(--color-dim)" }}>
        {live
          ? `journeys ${progress.journeys_done}/${progress.journeys_total || "—"} `
            + `// every request counted against one budget // nothing purchased, `
            + `submitted or deleted`
          : "simulated session // set NEXT_PUBLIC_AGENTQA_API to deploy the real agent"}
      </p>

      <style jsx>{`
        @keyframes aq-pulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50%      { opacity: 0.35; transform: scale(0.8); }
        }
      `}</style>
    </div>
  );
}
