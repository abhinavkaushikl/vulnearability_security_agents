"use client";

import { useState } from "react";
import type { Finding } from "@/lib/types";

const RESULT_COLOR: Record<string, string> = {
  PASS: "var(--color-bone)",
  FAIL: "var(--color-anomaly)",
  WARN: "var(--color-phos)",
  INFORMATIONAL: "var(--color-phos)",
  NOT_TESTABLE: "var(--color-dim)",
  "N/A": "var(--color-dim)",
};

/**
 * Findings are the report's integrity, so the row leads with *why* a verdict
 * exists. A NOT_TESTABLE row is not a failure to be hidden — it is the system
 * declining to claim something, and it gets the same visual weight.
 */
function Row({ f, index }: { f: Finding; index: number }) {
  const [open, setOpen] = useState(false);
  const color = RESULT_COLOR[f.native_result] ?? "var(--color-ash)";
  const undecided = f.native_result === "NOT_TESTABLE" || f.native_result === "INFORMATIONAL";

  return (
    <li className="rule">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        data-cursor={open ? "CLOSE" : "INSPECT"}
        className="group grid w-full grid-cols-[2.5rem_1fr_auto] items-start gap-4 py-6 text-left transition-colors md:grid-cols-[3.5rem_1fr_10rem_6rem] md:gap-6"
      >
        <span className="mono pt-1 tabular-nums">
          {String(index + 1).padStart(2, "0")}
        </span>

        <span className="min-w-0">
          <span className="mono block" style={{ color: "var(--color-dim)" }}>
            {f.control_id} // {f.family}
          </span>
          <span
            className="mt-1.5 block text-[clamp(1.05rem,2vw,1.45rem)] leading-snug tracking-tight transition-transform duration-500 group-hover:translate-x-1"
            style={{ transitionTimingFunction: "var(--ease-spring)" }}
          >
            {f.title}
          </span>
        </span>

        <span className="mono hidden md:block" style={{ color }}>
          {f.native_result}
        </span>

        <span
          className="mono justify-self-end"
          style={{ color: undecided ? "var(--color-dim)" : color }}
        >
          {undecided ? "—" : f.severity}
        </span>
      </button>

      <div
        className="grid overflow-hidden transition-[grid-template-rows] duration-500"
        style={{
          gridTemplateRows: open ? "1fr" : "0fr",
          transitionTimingFunction: "var(--ease-spring)",
        }}
      >
        <div className="min-h-0">
          <div className="grid gap-6 pb-8 md:grid-cols-[3.5rem_1fr] md:gap-6">
            <div />
            <div className="grid gap-5 md:grid-cols-2">
              {f.observed_value && (
                <Field label="Observed">
                  <code
                    className="block break-words font-[family-name:var(--font-mono)] text-[0.8rem] leading-relaxed"
                    style={{ color: "var(--color-phos)" }}
                  >
                    {f.observed_value}
                  </code>
                </Field>
              )}

              {f.unknown_reason && (
                <Field label="Why no verdict">
                  <p className="text-[0.9rem] leading-relaxed" style={{ color: "var(--color-ash)" }}>
                    {f.unknown_reason}
                  </p>
                </Field>
              )}

              <Field label="Evidence">
                <p className="text-[0.9rem] leading-relaxed" style={{ color: "var(--color-ash)" }}>
                  {f.evidence}
                </p>
              </Field>

              <Field label="Source">
                <p className="mono" style={{ letterSpacing: "0.08em" }}>
                  {f.source_file}:{f.source_line}
                </p>
              </Field>
            </div>
          </div>
        </div>
      </div>
    </li>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div
      className="border-l pl-4"
      style={{ borderColor: "var(--color-line)" }}
    >
      <p className="mono mb-2">{label}</p>
      {children}
    </div>
  );
}

export default function Findings({ findings }: { findings: Finding[] }) {
  const [filter, setFilter] = useState<"all" | "decided" | "undecided">("all");

  const shown = findings.filter((f) => {
    const undecided =
      f.native_result === "NOT_TESTABLE" || f.native_result === "INFORMATIONAL";
    if (filter === "decided") return !undecided;
    if (filter === "undecided") return undecided;
    return true;
  });

  const tabs = [
    { id: "all" as const, label: `All ${findings.length}` },
    { id: "decided" as const, label: "Decided" },
    { id: "undecided" as const, label: "No verdict" },
  ];

  return (
    <section className="mx-auto w-full max-w-5xl px-6 pt-28">
      <div className="flex flex-wrap items-end justify-between gap-6">
        <h2 className="h-display text-[clamp(1.9rem,5vw,3rem)]">What the agent saw</h2>
        <div className="flex gap-1" role="tablist" aria-label="Filter findings">
          {tabs.map((tb) => (
            <button
              key={tb.id}
              role="tab"
              aria-selected={filter === tb.id}
              onClick={() => setFilter(tb.id)}
              data-cursor="FILTER"
              className="mono px-3 py-2 transition-colors"
              style={{
                color: filter === tb.id ? "var(--color-phos)" : "var(--color-dim)",
                borderBottom: `1px solid ${filter === tb.id ? "var(--color-phos)" : "transparent"}`,
              }}
            >
              {tb.label}
            </button>
          ))}
        </div>
      </div>

      <ul className="mt-10">
        {shown.map((f, i) => (
          <Row key={f.control_id} f={f} index={i} />
        ))}
      </ul>
      <div className="rule" />
    </section>
  );
}
