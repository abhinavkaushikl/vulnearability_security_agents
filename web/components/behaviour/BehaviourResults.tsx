"use client";

import type {
  BehaviourReport, JourneyOutcome, TimelineRow, UXFinding, UXSeverity,
} from "@/lib/behaviourTypes";
import UXScoreDial from "./UXScoreDial";
import { useInView, useSpringNumber } from "@/lib/motion";
import { useSectionProgress } from "@/lib/fluid";

/**
 * §18-§20 and §24 — the behavioural report.
 *
 * The organising principle is §28: this must not read as "your website loads
 * in 1.8 seconds". It reads as *we gave your website to an AI user, here is
 * what happened to it* — so the journey the agent walked comes before any
 * table, every finding states what was expected next to what was observed,
 * and the closing card is a mission debrief rather than a score card.
 *
 * A `null` latency renders as "not measured". Never as 0.
 */

const SEV_COLOR: Record<UXSeverity, string> = {
  CRITICAL: "var(--color-anomaly)",
  HIGH: "var(--color-anomaly)",
  MEDIUM: "var(--color-phos)",
  LOW: "var(--color-ash)",
  INFO: "var(--color-dim)",
};

const ms = (v: number | null) => (v === null ? "not measured" : `${Math.round(v)}ms`);

function Section({ id, eyebrow, title, children }: {
  id: string; eyebrow: string; title: string; children: React.ReactNode;
}) {
  // Velocity-driven: the heading displaces as the section crosses the fold,
  // and the displacement scales with how hard the reader is scrolling.
  const ref = useSectionProgress<HTMLElement>();
  return (
    <section
      id={id}
      ref={ref}
      className="mx-auto w-full max-w-6xl px-6 py-20 md:py-28"
      style={{ ["--p" as string]: 0 }}
    >
      <header
        className="mb-12"
        style={{
          transform:
            "translate3d(0, calc(var(--p, 0) * -14px * (0.4 + var(--va, 0))), 0)",
          willChange: "transform",
        }}
      >
        <p className="mono" style={{ color: "var(--color-dim)" }}>{eyebrow}</p>
        <h2 className="h-display mt-3 text-[clamp(1.6rem,4.5vw,2.8rem)]">{title}</h2>
      </header>
      {children}
    </section>
  );
}

function Stat({ n, label, colour }: { n: number | null; label: string; colour?: string }) {
  const [ref, seen] = useInView<HTMLDivElement>();
  const v = useSpringNumber(n ?? 0, seen && n !== null, 0.09);
  return (
    <div ref={ref}>
      <p className="h-display tabular-nums text-[clamp(1.8rem,4.5vw,2.8rem)]"
         style={{ color: colour ?? "var(--color-bone)" }}>
        {n === null ? "—" : Math.round(v).toLocaleString()}
      </p>
      <p className="mono mt-1">{label}</p>
    </div>
  );
}

/** §18's journey diagram: each hop carries the latency the user actually saw. */
function Timeline({ rows }: { rows: TimelineRow[] }) {
  const [ref, seen] = useInView<HTMLOListElement>();
  if (!rows.length) {
    return <p style={{ color: "var(--color-dim)" }}>
      The agent dispatched no measurable steps.
    </p>;
  }
  return (
    <ol ref={ref} className="relative">
      <span
        className="absolute left-[5px] top-3 w-px"
        style={{
          background: "var(--color-line-lit)",
          height: seen ? "calc(100% - 2rem)" : 0,
          transition: "height 1500ms var(--ease-spring)",
        }}
      />
      {rows.map((r, i) => {
        const colour = !r.ok ? "var(--color-anomaly)"
                     : r.slow ? "var(--color-phos)"
                     : "var(--color-line-lit)";
        return (
          <li
            key={r.seq}
            className="relative grid grid-cols-[1fr_auto] items-baseline gap-4 pb-8 pl-9"
            style={{
              opacity: seen ? 1 : 0,
              transform: seen ? "none" : "translateY(10px)",
              transition: `opacity 550ms ${200 + i * 90}ms, `
                        + `transform 650ms ${200 + i * 90}ms var(--ease-spring)`,
            }}
          >
            <span
              className="absolute left-0 top-[7px] block h-[11px] w-[11px]"
              style={{
                background: r.ok ? colour : "var(--color-anomaly)",
                clipPath: "polygon(50% 0,100% 50%,50% 100%,0 50%)",
              }}
            />
            <div>
              <p className="text-[1.02rem] leading-snug">{r.label}</p>
              <p className="mono mt-1" style={{ color: "var(--color-dim)" }}>
                {r.action} · {r.category}
                {!r.ok && ` · ${r.outcome.replace("_", " ").toLowerCase()}`}
              </p>
            </div>
            <span className="mono tabular-nums whitespace-nowrap"
                  style={{ color: r.slow ? "var(--color-phos)"
                                         : r.ok ? "var(--color-ash)"
                                                : "var(--color-anomaly)" }}>
              {r.ms === null
                ? (r.outcome === "NO_RESPONSE" ? "no response" : "—")
                : `${Math.round(r.ms)}ms`}
              {r.slow && " ⚠"}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function Journeys({ outcomes }: { outcomes: JourneyOutcome[] }) {
  const [ref, seen] = useInView<HTMLDivElement>();
  return (
    <div ref={ref} className="grid gap-8 md:grid-cols-2">
      {outcomes.map((j, i) => {
        const pct = j.steps_planned
          ? (j.steps_succeeded / j.steps_planned) * 100 : 0;
        return (
          <article
            key={j.journey_id}
            className="grid gap-3 p-6"
            style={{
              border: "1px solid var(--color-line)",
              background: "rgba(12,12,15,0.55)",
              opacity: seen ? 1 : 0,
              transform: seen ? "none" : "translateY(14px)",
              transition: `opacity 600ms ${i * 110}ms, `
                        + `transform 700ms ${i * 110}ms var(--ease-spring)`,
            }}
          >
            <div className="flex items-baseline justify-between gap-4">
              <h3 className="text-[1.1rem]">{j.name}</h3>
              <span className="mono"
                    style={{ color: j.completed ? "var(--color-phos)"
                                                : "var(--color-anomaly)" }}>
                {j.completed ? "completed" : "abandoned"}
              </span>
            </div>
            <p style={{ color: "var(--color-ash)" }}>{j.goal}</p>
            <span className="relative mt-2 block h-[2px]"
                  style={{ background: "var(--color-line)" }}>
              <span className="absolute inset-y-0 left-0 block"
                    style={{
                      width: seen ? `${pct}%` : "0%",
                      background: j.completed ? "var(--color-phos)"
                                              : "var(--color-anomaly)",
                      transition: `width 1100ms ${300 + i * 110}ms var(--ease-spring)`,
                    }} />
            </span>
            <p className="mono" style={{ color: "var(--color-dim)" }}>
              {j.steps_succeeded}/{j.steps_planned} steps succeeded
              {j.total_ms !== null && ` · ${(j.total_ms / 1000).toFixed(1)}s`}
            </p>
            {!j.completed && j.abandoned_at && (
              <p className="mt-1 leading-relaxed"
                 style={{ color: "var(--color-anomaly)" }}>
                Stopped at “{j.abandoned_at}”
                {j.abandon_reason && (
                  <span style={{ color: "var(--color-ash)" }}> — {j.abandon_reason}</span>
                )}
              </p>
            )}
          </article>
        );
      })}
    </div>
  );
}

function Findings({ findings }: { findings: UXFinding[] }) {
  const [ref, seen] = useInView<HTMLDivElement>();
  if (!findings.length) {
    return <p style={{ color: "var(--color-ash)" }}>
      Nothing crossed a reporting threshold in this session. That is not the
      same as “no problems” — it is the set of problems this agent, on these
      journeys, could measure.
    </p>;
  }
  return (
    <div ref={ref} className="grid gap-px" style={{ background: "var(--color-line)" }}>
      {findings.map((f, i) => (
        <article
          key={f.id}
          className="grid gap-4 p-7 md:grid-cols-[13rem_1fr] md:gap-10"
          style={{
            background: "var(--color-void)",
            opacity: seen ? 1 : 0,
            transform: seen ? "none" : "translateY(12px)",
            transition: `opacity 600ms ${i * 90}ms, `
                      + `transform 700ms ${i * 90}ms var(--ease-spring)`,
          }}
        >
          <div>
            <p className="mono" style={{ color: SEV_COLOR[f.severity] }}>
              {f.severity}
            </p>
            <p className="mono mt-1" style={{ color: "var(--color-dim)" }}>
              {f.category}
            </p>
            {f.evidence_seq.length > 0 && (
              <p className="mono mt-3" style={{ color: "var(--color-dim)" }}>
                from actions {f.evidence_seq.slice(0, 6).join(", ")}
              </p>
            )}
          </div>

          <div className="grid gap-4">
            <h3 className="text-[clamp(1.05rem,2.4vw,1.35rem)] leading-snug">
              {f.title}
            </h3>
            <div className="grid gap-3 md:grid-cols-2">
              <div>
                <p className="mono" style={{ color: "var(--color-dim)" }}>observed</p>
                <p className="mt-1 leading-relaxed"
                   style={{ color: "var(--color-bone)" }}>{f.observed}</p>
              </div>
              <div>
                <p className="mono" style={{ color: "var(--color-dim)" }}>expected</p>
                <p className="mt-1 leading-relaxed"
                   style={{ color: "var(--color-ash)" }}>{f.expected}</p>
              </div>
            </div>
            <div>
              <p className="mono" style={{ color: "var(--color-dim)" }}>impact</p>
              <p className="mt-1 leading-relaxed"
                 style={{ color: "var(--color-ash)" }}>{f.impact}</p>
            </div>
            <div>
              <p className="mono" style={{ color: "var(--color-dim)" }}>recommendation</p>
              <p className="mt-1 leading-relaxed"
                 style={{ color: "var(--color-bone)" }}>{f.recommendation}</p>
            </div>
          </div>
        </article>
      ))}
    </div>
  );
}

export default function BehaviourResults({ report, onReset }: {
  report: BehaviourReport;
  onReset: () => void;
}) {
  const m = report.mission;
  const host = (() => {
    try { return new URL(report.target).host; } catch { return report.target; }
  })();

  return (
    <div>
      {/* ── §24: mission debrief ──────────────────────────────────────── */}
      <section className="mx-auto w-full max-w-6xl px-6 pb-8 pt-24 md:pt-32">
        <p className="mono" style={{ color: "var(--color-phos)" }}>
          agent mission complete
        </p>
        <h1 className="h-display mt-5 text-[clamp(2.2rem,7vw,4.4rem)]">
          We gave {host} to an AI user.
        </h1>
        <p className="mt-6 max-w-[54ch] text-[clamp(1rem,2.2vw,1.25rem)] leading-relaxed"
           style={{ color: "var(--color-ash)" }}>
          {report.understanding.primary_goal
            ? `It came here to ${report.understanding.primary_goal}. `
            : ""}
          Here is what happened to it.
        </p>

        {report.blocked_reason && (
          <p className="mt-8 max-w-[62ch] border-l-2 pl-5 leading-relaxed"
             style={{ borderColor: "var(--color-anomaly)",
                      color: "var(--color-bone)" }}>
            {report.blocked_reason}
          </p>
        )}

        <div className="mt-16 grid grid-cols-2 gap-8 sm:grid-cols-3 lg:grid-cols-6">
          <Stat n={m.pages_explored} label="pages explored" />
          <Stat n={m.interactions} label="interactions" />
          <Stat n={m.journeys} label="journeys" />
          <Stat n={m.issues_detected} label="issues detected" />
          <Stat n={m.critical_issues} label="critical"
                colour={m.critical_issues ? "var(--color-anomaly)" : undefined} />
          <Stat n={m.avg_response_ms} label="median response ms" />
        </div>
      </section>

      {/* ── §17: the score ────────────────────────────────────────────── */}
      <Section id="score" eyebrow="§ user experience score"
               title="What the experience is worth">
        <UXScoreDial score={report.score} />
      </Section>

      {/* ── §18: executive summary ────────────────────────────────────── */}
      <Section id="summary" eyebrow="§ executive summary"
               title="In a paragraph">
        <p className="max-w-[62ch] text-[clamp(1.05rem,2.4vw,1.45rem)] leading-relaxed">
          {report.summary}
        </p>
        <div className="mt-12 grid gap-6 md:grid-cols-3">
          <div>
            <p className="mono" style={{ color: "var(--color-dim)" }}>read as</p>
            <p className="mt-1">{report.understanding.kind}
              <span className="mono ml-2" style={{ color: "var(--color-dim)" }}>
                {(report.understanding.confidence * 100).toFixed(0)}% confidence
                · {report.understanding.derived_by}
              </span>
            </p>
          </div>
          <div>
            <p className="mono" style={{ color: "var(--color-dim)" }}>visitor goal</p>
            <p className="mt-1">{report.understanding.primary_goal || "—"}</p>
          </div>
          <div>
            <p className="mono" style={{ color: "var(--color-dim)" }}>affordances found</p>
            <p className="mt-1">
              {report.understanding.key_affordances.join(", ") || "none"}
            </p>
          </div>
        </div>
      </Section>

      {/* ── §18: the journey ──────────────────────────────────────────── */}
      <Section id="journey" eyebrow="§ user journey"
               title="What the agent actually did">
        <div className="grid gap-16 lg:grid-cols-[1.1fr_1fr]">
          <Timeline rows={report.timeline} />
          <div className="grid content-start gap-8">
            <Journeys outcomes={report.journey_outcomes} />
          </div>
        </div>
      </Section>

      {/* ── §11: latency by interaction category ──────────────────────── */}
      {report.categories.length > 0 && (
        <Section id="latency" eyebrow="§ interaction performance"
                 title="How long each kind of thing took">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[34rem] border-collapse text-left">
              <thead>
                <tr className="mono" style={{ color: "var(--color-dim)" }}>
                  <th className="py-3 pr-6 font-normal">category</th>
                  <th className="py-3 pr-6 font-normal">n</th>
                  <th className="py-3 pr-6 font-normal">median</th>
                  <th className="py-3 pr-6 font-normal">p95</th>
                  <th className="py-3 font-normal">worst</th>
                </tr>
              </thead>
              <tbody>
                {report.categories.map((c) => (
                  <tr key={c.category}
                      style={{ borderTop: "1px solid var(--color-line)" }}>
                    <td className="py-4 pr-6">{c.category}</td>
                    <td className="mono py-4 pr-6 tabular-nums">{c.n}</td>
                    <td className="mono py-4 pr-6 tabular-nums">
                      {Math.round(c.median_ms)}ms
                    </td>
                    <td className="mono py-4 pr-6 tabular-nums"
                        style={{ color: c.p95_ms === null ? "var(--color-dim)"
                                                          : undefined }}>
                      {c.p95_ms === null ? "n<3" : `${Math.round(c.p95_ms)}ms`}
                    </td>
                    <td className="mono py-4 tabular-nums">
                      {Math.round(c.worst_ms)}ms
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mono mt-6" style={{ color: "var(--color-dim)",
             textTransform: "none", letterSpacing: "0.05em" }}>
            Perceived response — the moment the interface visibly reacted, not
            the moment the request came back. A p95 needs at least three
            samples; below that it is not reported.
          </p>
        </Section>
      )}

      {/* ── §18: interaction analysis ─────────────────────────────────── */}
      {report.interactions.length > 0 && (
        <Section id="interactions" eyebrow="§ interaction analysis"
                 title="Expectation against observation">
          <div className="grid gap-px" style={{ background: "var(--color-line)" }}>
            {report.interactions.slice(0, 18).map((r) => (
              <div key={r.seq}
                   className="grid gap-3 p-6 md:grid-cols-[1fr_1fr_10rem]"
                   style={{ background: "var(--color-void)" }}>
                <div>
                  <p className="mono" style={{ color: "var(--color-dim)" }}>
                    {r.category}
                  </p>
                  <p className="mt-1">{r.interaction}</p>
                </div>
                <div>
                  <p className="mono" style={{ color: "var(--color-dim)" }}>
                    expected · observed
                  </p>
                  <p className="mt-1" style={{ color: "var(--color-ash)" }}>
                    {r.expectation}
                  </p>
                  <p className="mt-1">{r.observed}</p>
                </div>
                <div className="md:text-right">
                  <p className="mono tabular-nums"
                     style={{ color: r.severity === "INFO" ? "var(--color-ash)"
                                                           : "var(--color-phos)" }}>
                    {ms(r.ms)}
                  </p>
                  <p className="mono mt-1"
                     style={{ color: r.severity === "CRITICAL" || r.severity === "HIGH"
                       ? "var(--color-anomaly)" : "var(--color-dim)",
                       textTransform: "none", letterSpacing: "0.04em" }}>
                    {r.assessment}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* ── §19: findings ─────────────────────────────────────────────── */}
      <Section id="findings" eyebrow="§ ux findings"
               title="Where the experience breaks down">
        <Findings findings={report.findings} />
      </Section>

      {/* ── §20: behavioural insights ─────────────────────────────────── */}
      <Section id="insights" eyebrow="§ behavioural insights"
               title="How it feels to use">
        <dl className="grid gap-8 md:grid-cols-2 md:gap-x-14">
          {Object.entries(report.insights).map(([q, a]) => (
            <div key={q}>
              <dt className="mono" style={{ color: "var(--color-dim)" }}>{q}</dt>
              <dd className="mt-2 leading-relaxed">{a}</dd>
            </div>
          ))}
        </dl>
      </Section>

      {/* ── pages measured ────────────────────────────────────────────── */}
      {report.pages.length > 0 && (
        <Section id="pages" eyebrow="§ pages measured"
                 title="Every page the agent reached">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[46rem] border-collapse text-left">
              <thead>
                <tr className="mono" style={{ color: "var(--color-dim)" }}>
                  <th className="py-3 pr-6 font-normal">page</th>
                  <th className="py-3 pr-6 font-normal">ttfb</th>
                  <th className="py-3 pr-6 font-normal">fcp</th>
                  <th className="py-3 pr-6 font-normal">lcp</th>
                  <th className="py-3 pr-6 font-normal">cls</th>
                  <th className="py-3 pr-6 font-normal">inp</th>
                  <th className="py-3 font-normal">visits</th>
                </tr>
              </thead>
              <tbody>
                {report.pages.map((p) => (
                  <tr key={p.url} style={{ borderTop: "1px solid var(--color-line)" }}>
                    <td className="max-w-[22rem] truncate py-4 pr-6">
                      {p.title || p.url}
                    </td>
                    <td className="mono py-4 pr-6 tabular-nums">{ms(p.vitals.ttfb_ms)}</td>
                    <td className="mono py-4 pr-6 tabular-nums">{ms(p.vitals.fcp_ms)}</td>
                    <td className="mono py-4 pr-6 tabular-nums">{ms(p.vitals.lcp_ms)}</td>
                    <td className="mono py-4 pr-6 tabular-nums">
                      {p.vitals.cls === null ? "—" : p.vitals.cls.toFixed(3)}
                    </td>
                    <td className="mono py-4 pr-6" style={{ color: "var(--color-dim)" }}>
                      n/a
                    </td>
                    <td className="mono py-4 tabular-nums">{p.visits}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mono mt-6 max-w-[64ch] leading-relaxed"
             style={{ color: "var(--color-dim)", textTransform: "none",
                      letterSpacing: "0.05em" }}>
            INP is <b>n/a</b> and always will be from this tool: it is measured
            from real users’ own interactions over a session. One agent on one
            machine cannot produce one, so none is claimed.
          </p>
        </Section>
      )}

      {/* ── what the agent refused to do ──────────────────────────────── */}
      {report.refusals.length > 0 && (
        <Section id="declined" eyebrow="§ declined"
                 title="What the agent would not do">
          <ul className="grid gap-4">
            {report.refusals.map((r, i) => (
              <li key={i} className="border-l-2 pl-5 leading-relaxed"
                  style={{ borderColor: "var(--color-line-lit)",
                           color: "var(--color-ash)" }}>
                {r.reason}
              </li>
            ))}
          </ul>
          <p className="mt-8 max-w-[58ch] leading-relaxed"
             style={{ color: "var(--color-ash)" }}>
            The agent walks up to these and stops. It never completes a
            purchase, submits credentials, sends a message or deletes anything
            — on any site, under any plan.
          </p>
        </Section>
      )}

      {/* ── provenance ────────────────────────────────────────────────── */}
      <section className="mx-auto w-full max-w-6xl px-6 pb-28">
        <div className="rule pt-10">
          <p className="mono leading-relaxed" style={{ color: "var(--color-dim)",
             textTransform: "none", letterSpacing: "0.05em" }}>
            session {report.session_id} · {report.duration_seconds.toFixed(1)}s ·
            {" "}{report.requests_made} requests sent to the target ·
            {" "}{report.browser_version || "browser"} ·
            {" "}{report.llm_model
              ? `plan and decisions assisted by ${report.llm_model}`
              : "deterministic mode — journeys and decisions from heuristics, "
                + "no model involved"}
            {report.errors.length > 0 && ` · ${report.errors.length} non-fatal errors`}
          </p>
          <button
            onClick={onReset}
            data-cursor="NEW SESSION"
            className="mono mt-10 px-5 py-3"
            style={{ border: "1px solid var(--color-line-lit)",
                     color: "var(--color-bone)" }}
          >
            Deploy again
          </button>
        </div>
      </section>
    </div>
  );
}
