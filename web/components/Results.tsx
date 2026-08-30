"use client";

import type { Report } from "@/lib/types";
import CoverageDial from "./CoverageDial";
import Findings from "./Findings";
import { useInView, useSpringNumber } from "@/lib/motion";

function Stat({ n, label, color, active }: { n: number; label: string; color: string; active: boolean }) {
  const v = useSpringNumber(n, active, 0.09);
  return (
    <div>
      <p className="h-display tabular-nums text-[clamp(1.8rem,4vw,2.6rem)]" style={{ color }}>
        {Math.round(v)}
      </p>
      <p className="mono mt-1">{label}</p>
    </div>
  );
}

/** Family coverage as energy bars: filled = decided, notch = failed. */
function FamilyBars({ report }: { report: Report }) {
  const [ref, seen] = useInView<HTMLDivElement>();
  return (
    <div ref={ref} className="grid gap-5">
      {report.families.map((f, i) => {
        const pct = f.total ? (f.decided / f.total) * 100 : 0;
        return (
          <div key={f.family} className="grid grid-cols-[4.5rem_1fr_4rem] items-center gap-4">
            <span className="mono" style={{ color: "var(--color-bone)" }}>{f.family}</span>
            <span className="relative block h-[3px]" style={{ background: "var(--color-line)" }}>
              <span
                className="absolute inset-y-0 left-0 block"
                style={{
                  width: seen ? `${pct}%` : "0%",
                  background: f.failed ? "var(--color-anomaly)" : "var(--color-phos)",
                  transition: `width 1100ms ${i * 70}ms var(--ease-spring)`,
                }}
              />
            </span>
            <span className="mono tabular-nums justify-self-end">
              {f.decided}/{f.total}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/** The agent's real route — every step carries the reason it was taken. */
function Route({ report }: { report: Report }) {
  const [ref, seen] = useInView<HTMLOListElement>();
  return (
    <ol ref={ref} className="relative">
      <span
        className="absolute left-[3px] top-2 w-px"
        style={{
          background: "var(--color-line-lit)",
          height: seen ? "calc(100% - 1rem)" : 0,
          transition: "height 1400ms var(--ease-spring)",
        }}
      />
      {report.route.map((s, i) => (
        <li
          key={i}
          className="relative pb-7 pl-8"
          style={{
            opacity: seen ? 1 : 0,
            transform: seen ? "none" : "translateY(8px)",
            transition: `opacity 600ms ${300 + i * 130}ms, transform 700ms ${300 + i * 130}ms var(--ease-spring)`,
          }}
        >
          <span
            className="absolute left-0 top-[7px] block h-[7px] w-[7px] rounded-full"
            style={{ background: "var(--color-phos)" }}
          />
          <p className="mono" style={{ color: "var(--color-bone)" }}>{s.kind}</p>
          <p className="mt-1.5 text-[0.95rem] leading-relaxed" style={{ color: "var(--color-ash)" }}>
            {s.reason}
          </p>
          {s.required_by.length > 0 && (
            <p className="mono mt-2" style={{ color: "var(--color-dim)" }}>
              required by // {s.required_by.join("  ")}
            </p>
          )}
        </li>
      ))}
    </ol>
  );
}

export default function Results({ report, onReset }: { report: Report; onReset: () => void }) {
  const [ref, seen] = useInView<HTMLDivElement>("0px");
  const t = report.tally;

  return (
    <div ref={ref}>
      {/* ---- headline -------------------------------------------------- */}
      <section className="mx-auto w-full max-w-5xl px-6 pt-16">
        <div className="mono flex flex-wrap items-center gap-x-6 gap-y-2">
          <span>target // {report.target}</span>
          <span>session // {report.assessment_id.slice(0, 8).toUpperCase()}</span>
          <span>status // <span style={{ color: "var(--color-phos)" }}>{report.status}</span></span>
          <span>{report.duration_seconds.toFixed(1)}s</span>
        </div>

        <div className="mt-14 grid items-center gap-14 md:grid-cols-[minmax(0,340px)_1fr] md:gap-20">
          <CoverageDial coverage={report.coverage_pct} tally={t} />

          <div>
            <h2 className="h-display max-w-[18ch] text-[clamp(1.9rem,4.4vw,3rem)]">
              {t.unknown} controls could not be decided from a browser.
            </h2>
            <p className="mt-6 max-w-[52ch] leading-relaxed" style={{ color: "var(--color-ash)" }}>
              That is the honest result, not a gap in the scan. Payments, identity
              and business-logic controls need staging, authorized active testing
              or interviews — so the agent reports what it observed and declines
              the rest.
            </p>

            <div className="mt-10 grid grid-cols-2 gap-8 sm:grid-cols-4">
              <Stat n={t.yes} label="Yes" color="var(--color-bone)" active={seen} />
              <Stat n={t.no} label="No" color="var(--color-anomaly)" active={seen} />
              <Stat n={t.not_applicable} label="N/A" color="var(--color-ash)" active={seen} />
              <Stat n={t.unknown} label="Unknown" color="var(--color-dim)" active={seen} />
            </div>
          </div>
        </div>
      </section>

      {/* ---- families + route ----------------------------------------- */}
      <section className="mx-auto grid w-full max-w-5xl gap-16 px-6 pt-28 md:grid-cols-2 md:gap-20">
        <div>
          <h3 className="h-display text-[clamp(1.4rem,3vw,2rem)]">Reach by family</h3>
          <p className="mono mt-3 mb-8">how much of each family a browser could prove</p>
          <FamilyBars report={report} />
        </div>
        <div>
          <h3 className="h-display text-[clamp(1.4rem,3vw,2rem)]">Route taken</h3>
          <p className="mono mt-3 mb-8">{report.route.length} actions // no unattributed traffic</p>
          <Route report={report} />
        </div>
      </section>

      <Findings findings={report.findings} />

      {/* ---- performance ----------------------------------------------- */}
      <section className="mx-auto w-full max-w-5xl px-6 pt-28">
        <h3 className="h-display text-[clamp(1.4rem,3vw,2rem)]">Under throttling</h3>
        <p className="mono mt-3 mb-8">profiles run in series // a shared uplink measures contention, not the profile</p>
        <div className="grid gap-px sm:grid-cols-2 lg:grid-cols-4" style={{ background: "var(--color-line)" }}>
          {report.performance.map((p) => (
            <div key={p.profile} className="p-6" style={{ background: "var(--color-void)" }}>
              <p className="mono" style={{ color: p.status === "OK" ? "var(--color-phos)" : "var(--color-dim)" }}>
                {p.profile} // {p.status}
              </p>
              <p className="h-display mt-4 tabular-nums text-[clamp(1.6rem,3.4vw,2.2rem)]">
                {p.lcp_p50 === null ? "—" : `${(p.lcp_p50 / 1000).toFixed(2)}s`}
              </p>
              <p className="mono mt-1">lcp p50 // n={p.n}</p>
              <p className="mono mt-3" style={{ color: "var(--color-dim)" }}>
                ttfb {p.ttfb_p50 === null ? "—" : `${p.ttfb_p50}ms`}
              </p>
            </div>
          ))}
        </div>
        <p className="mono mt-5 max-w-[64ch] leading-relaxed" style={{ textTransform: "none", letterSpacing: "0.04em" }}>
          Lab measurements. PERF-01 asks for a field p75, so no verdict is claimed from these.
        </p>
      </section>

      {/* ---- footer ---------------------------------------------------- */}
      <section className="mx-auto w-full max-w-5xl px-6 py-28">
        <div className="rule pt-10">
          <div className="flex flex-wrap items-center justify-between gap-8">
            <div>
              <p className="mono">collectors run // {report.collectors_run.length}</p>
              <p className="mono mt-2">{report.collectors_run.join("  ")}</p>
              {report.llm_model && <p className="mono mt-2">model // {report.llm_model}</p>}
            </div>
            <button
              onClick={onReset}
              data-cursor="NEW TARGET"
              className="h-display text-[clamp(1.2rem,2.6vw,1.7rem)] transition-colors hover:text-[var(--color-phos)]"
            >
              Analyze another site →
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
