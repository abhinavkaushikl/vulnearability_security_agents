"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Lenis from "lenis";
import AmbientField from "@/components/AmbientField";
import Cursor from "@/components/Cursor";
import Hero from "@/components/Hero";
import Portal from "@/components/Portal";
import MissionStage from "@/components/MissionStage";
import Results from "@/components/Results";
import Sections from "@/components/Sections";
import { startRun, isLive, type Run } from "@/lib/api";
import type { Progress, Report } from "@/lib/types";
import { prefersReduced } from "@/lib/motion";

type Phase = "idle" | "deploying" | "running" | "done" | "error";

export default function Page() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [progress, setProgress] = useState<Progress>({
    status: "PLANNING", pct: 0, label: "READING THE PACK",
  });
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const run = useRef<Run | null>(null);

  /* Smooth scroll, disabled entirely under reduced motion. */
  useEffect(() => {
    if (prefersReduced()) return;
    const lenis = new Lenis({ duration: 1.15, smoothWheel: true });
    let raf = 0;
    const loop = (t: number) => {
      lenis.raf(t);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(raf);
      lenis.destroy();
    };
  }, []);

  const deploy = useCallback(async (url: string) => {
    setError(null);
    setReport(null);
    // A held beat before the stage arrives; a hard cut would lose the handoff.
    setPhase("deploying");
    await new Promise((r) => setTimeout(r, prefersReduced() ? 0 : 620));
    setPhase("running");

    const r = startRun(url, setProgress);
    run.current = r;
    try {
      const rep = await r.done;
      setReport(rep);
      setPhase("done");
      window.scrollTo({ top: 0, behavior: "auto" });
    } catch (e) {
      setError(e instanceof Error ? e.message : "The run could not be completed.");
      setPhase("error");
    }
  }, []);

  const reset = useCallback(() => {
    run.current?.cancel();
    run.current = null;
    setReport(null);
    setError(null);
    setProgress({ status: "PLANNING", pct: 0, label: "READING THE PACK" });
    setPhase("idle");
    window.scrollTo({ top: 0, behavior: "auto" });
  }, []);

  useEffect(() => () => run.current?.cancel(), []);

  const busy = phase === "deploying" || phase === "running";
  const energy = phase === "idle" ? 0 : phase === "done" ? 0.5 : 1;

  return (
    <main className="relative min-h-dvh">
      <AmbientField energy={energy} />
      <Cursor />

      {/* Idle: hero + portal + the case for the design. */}
      <div
        style={{
          opacity: phase === "idle" || phase === "deploying" ? 1 : 0,
          transform: phase === "deploying" ? "scale(0.985)" : "none",
          filter: phase === "deploying" ? "blur(6px)" : "none",
          transition: "opacity 600ms, transform 800ms var(--ease-spring), filter 600ms",
          pointerEvents: phase === "idle" ? "auto" : "none",
          display: phase === "done" || phase === "running" ? "none" : "block",
        }}
      >
        <Hero />
        <Portal onDeploy={deploy} busy={busy} />
        <Sections />
      </div>

      {/* Running: the stage takes the whole viewport. */}
      {phase === "running" && (
        <div
          className="grid min-h-dvh place-items-center py-20"
          style={{ animation: "none" }}
        >
          <div className="w-full">
            <MissionStage progress={progress} />
            <p className="mono mx-auto mt-10 max-w-5xl px-6" style={{ color: "var(--color-dim)" }}>
              {isLive()
                ? `requests // ${progress.requests ?? 0}`
                : "simulated run // set NEXT_PUBLIC_AGENTQA_API to drive the real analyzer"}
            </p>
          </div>
        </div>
      )}

      {/* Done. */}
      {phase === "done" && report && <Results report={report} onReset={reset} />}

      {/* Failure states get direction, not an apology. */}
      {phase === "error" && (
        <section className="mx-auto grid min-h-dvh max-w-3xl place-items-center px-6">
          <div>
            <p className="mono" style={{ color: "var(--color-anomaly)" }}>run halted</p>
            <h2 className="h-display mt-6 text-[clamp(1.8rem,5vw,3rem)]">{error}</h2>
            <p className="mt-6 leading-relaxed" style={{ color: "var(--color-ash)" }}>
              Nothing was retried and no request was repeated. Check the target is
              reachable and that the analyzer is running, then deploy again.
            </p>
            <button
              onClick={reset}
              data-cursor="RETRY"
              className="mono mt-10 px-5 py-3"
              style={{ border: "1px solid var(--color-line-lit)", color: "var(--color-bone)" }}
            >
              Back to start
            </button>
          </div>
        </section>
      )}
    </main>
  );
}
