"use client";

import { useInView } from "@/lib/motion";

function Reveal({ children, delay = 0 }: { children: React.ReactNode; delay?: number }) {
  const [ref, seen] = useInView<HTMLDivElement>();
  return (
    <div
      ref={ref}
      style={{
        opacity: seen ? 1 : 0,
        transform: seen ? "none" : "translateY(14px)",
        transition: `opacity 700ms ${delay}ms, transform 900ms ${delay}ms var(--ease-spring)`,
      }}
    >
      {children}
    </div>
  );
}

const COLLECTORS: [string, string][] = [
  ["HDR", "response headers"],
  ["CK", "cookie flags"],
  ["WS", "web storage"],
  ["DOM", "rendered document"],
  ["JS", "script inventory"],
  ["NET", "request log"],
  ["CON", "console + page errors"],
  ["TIM", "navigation timing"],
  ["CWV", "lab vitals"],
  ["A11", "accessibility tree"],
  ["FRM", "form structure"],
  ["LNK", "link graph"],
  ["3P", "third-party origins"],
  ["CACHE", "cache directives"],
  ["RDR", "redirect chain"],
  ["TLS", "certificate + protocol"],
  ["DNS", "records, DNSSEC, CAA"],
  ["WK", "security.txt"],
  ["ERR", "one benign 404"],
];

const NEVER = [
  "exploitation",
  "brute force",
  "credential attacks",
  "authentication bypass",
  "denial of service",
  "destructive requests",
  "CAPTCHA solving",
  "anti-bot evasion",
  "IP rotation",
  "crawling",
];

export default function Sections() {
  return (
    <>
      {/* ---- the number that shapes everything ------------------------- */}
      <section className="mx-auto w-full max-w-5xl px-6 pt-40">
        <Reveal>
          <p className="mono">the finding that shapes the design</p>
          <h2 className="h-display mt-8 max-w-[20ch] text-[clamp(2rem,6vw,4rem)]">
            Only 25 of 144 controls are fully automatable.
          </h2>
          <p className="mt-8 max-w-[56ch] text-[1.05rem] leading-relaxed" style={{ color: "var(--color-ash)" }}>
            A system that emitted 144 pass/fail verdicts from one page load would
            be fabricating 102 of them. So AgentQA loads the whole pack, decides
            what the evidence supports, and returns{" "}
            <span style={{ color: "var(--color-phos)" }}>UNKNOWN with a stated reason</span>{" "}
            for the rest.
          </p>
        </Reveal>

        <Reveal delay={120}>
          <div className="mt-16 grid gap-px sm:grid-cols-2 lg:grid-cols-5" style={{ background: "var(--color-line)" }}>
            {[
              ["P", 25, "passive automation possible"],
              ["P/M", 14, "a browser sees part of it"],
              ["M/P", 3, "same, written the other way"],
              ["M", 96, "needs staging or interviews"],
              ["No", 6, "not provable from a website"],
            ].map(([tier, n, why]) => (
              <div key={tier as string} className="p-6" style={{ background: "var(--color-void)" }}>
                <p className="mono" style={{ color: "var(--color-phos)" }}>tier {tier}</p>
                <p className="h-display mt-3 tabular-nums text-[clamp(2rem,4vw,2.8rem)]">{n}</p>
                <p className="mono mt-2 leading-relaxed" style={{ textTransform: "none", letterSpacing: "0.04em" }}>
                  {why}
                </p>
              </div>
            ))}
          </div>
        </Reveal>
      </section>

      {/* ---- what it looks at ------------------------------------------ */}
      <section className="mx-auto w-full max-w-5xl px-6 pt-40">
        <Reveal>
          <h2 className="h-display max-w-[16ch] text-[clamp(1.9rem,5vw,3.2rem)]">
            Nineteen collectors. One page load.
          </h2>
          <p className="mt-6 max-w-[52ch] leading-relaxed" style={{ color: "var(--color-ash)" }}>
            Fifteen of them come from the same navigation. A full run is roughly
            one navigation, four auxiliary requests and twelve throttled loads —
            quieter than a single person browsing the site.
          </p>
        </Reveal>

        <Reveal delay={100}>
          <ul className="mt-14 grid gap-x-10 gap-y-4 sm:grid-cols-2 lg:grid-cols-3">
            {COLLECTORS.map(([code, what]) => (
              <li key={code} className="rule flex items-baseline gap-4 pt-3">
                <span className="mono w-14 shrink-0" style={{ color: "var(--color-phos)" }}>{code}</span>
                <span className="text-[0.95rem]" style={{ color: "var(--color-ash)" }}>{what}</span>
              </li>
            ))}
          </ul>
        </Reveal>
      </section>

      {/* ---- boundary --------------------------------------------------- */}
      <section className="mx-auto w-full max-w-5xl px-6 pb-40 pt-40">
        <Reveal>
          <p className="mono">safety boundary // enforced structurally</p>
          <h2 className="h-display mt-8 max-w-[18ch] text-[clamp(1.9rem,5vw,3.2rem)]">
            What the agent will never do.
          </h2>
          <ul className="mt-12 flex flex-wrap gap-x-3 gap-y-3">
            {NEVER.map((n) => (
              <li
                key={n}
                className="mono px-4 py-2"
                style={{
                  border: "1px solid var(--color-line)",
                  color: "var(--color-dim)",
                  textDecoration: "line-through",
                  textDecorationColor: "var(--color-anomaly)",
                }}
              >
                {n}
              </li>
            ))}
          </ul>
          <p className="mt-10 max-w-[56ch] leading-relaxed" style={{ color: "var(--color-ash)" }}>
            If the target challenges the agent, it halts, records the response as
            evidence, and marks every dependent control UNKNOWN. No retry, no
            backoff, no rotation. Assess only targets you are authorized to test.
          </p>
        </Reveal>
      </section>
    </>
  );
}
