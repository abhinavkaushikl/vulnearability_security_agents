"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Lenis from "lenis";
import AmbientField from "@/components/AmbientField";
import Cursor from "@/components/Cursor";
import Hero from "@/components/Hero";
import Portal, { type Mode } from "@/components/Portal";
import MissionStage from "@/components/MissionStage";
import Results from "@/components/Results";
import Sections from "@/components/Sections";
import BehaviourStage from "@/components/behaviour/BehaviourStage";
import BehaviourResults from "@/components/behaviour/BehaviourResults";
import { startRun, isLive, type Run } from "@/lib/api";
import { startBehaviour, type BehaviourRun } from "@/lib/behaviourApi";
import type { Progress, Report } from "@/lib/types";
import type {
  BehaviourProgress, BehaviourReport, MapEdge, MapNode, Thought,
} from "@/lib/behaviourTypes";
import { prefersReduced } from "@/lib/motion";
import { LENIS_FAST, useScrollSignal } from "@/lib/fluid";

type Phase = "idle" | "deploying" | "running" | "done" | "error";

const INITIAL_BEHAVIOUR: BehaviourProgress = {
  state: "DISCOVERING", pct: 0, objective: "Reaching the site",
  current_action: "", page_url: "", pages_visited: 0, interactions: 0,
  actions_dispatched: 0, avg_response_ms: null, requests: 0,
  journeys_done: 0, journeys_total: 0, thought: null, node: null,
  map_nodes: null,
};

export default function Page() {
  const [mode, setMode] = useState<Mode>("behaviour");
  const [phase, setPhase] = useState<Phase>("idle");
  const [target, setTarget] = useState("");
  const [error, setError] = useState<string | null>(null);

  const [progress, setProgress] = useState<Progress>({
    status: "PLANNING", pct: 0, label: "READING THE PACK",
  });
  const [report, setReport] = useState<Report | null>(null);

  const [bProgress, setBProgress] = useState<BehaviourProgress>(INITIAL_BEHAVIOUR);
  const [thoughts, setThoughts] = useState<Thought[]>([]);
  const [bReport, setBReport] = useState<BehaviourReport | null>(null);

  /* The journey map and the trail through it.
   *
   * These are accumulated in the SSE callback rather than read off the latest
   * `bProgress`, and that is not a style choice. React batches state updates,
   * and the stream replays its whole history the moment the browser
   * subscribes — so a dozen frames can collapse into one render. Anything
   * carried by exactly ONE frame is then lost, and the map is carried by
   * exactly one frame (the PLANNING one). The callback, by contrast, runs
   * once per message, so accumulating here sees every frame. */
  const [graph, setGraph] = useState<{ nodes: MapNode[]; edges: MapEdge[] }>(
    { nodes: [], edges: [] });
  const [trail, setTrail] = useState<{ visited: Set<string>; failed: Set<string> }>(
    { visited: new Set(["start"]), failed: new Set() });

  const run = useRef<Run | BehaviourRun | null>(null);

  /* The velocity signal every animation on the page reads. See lib/fluid.ts. */
  useScrollSignal();

  /* Smooth scroll, disabled entirely under reduced motion.
     Tuned for "fast + smooth" rather than "slow + smooth" — §13. */
  useEffect(() => {
    if (prefersReduced()) return;
    const lenis = new Lenis({ ...LENIS_FAST });
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
    setBReport(null);
    setThoughts([]);
    setBProgress(INITIAL_BEHAVIOUR);
    setGraph({ nodes: [], edges: [] });
    setTrail({ visited: new Set(["start"]), failed: new Set() });
    setTarget(url);
    // A held beat before the stage arrives; a hard cut would lose the handoff.
    setPhase("deploying");
    await new Promise((r) => setTimeout(r, prefersReduced() ? 0 : 620));
    setPhase("running");

    try {
      if (mode === "behaviour") {
        const r = startBehaviour(url, (p) => {
          setBProgress(p);
          // Thoughts accumulate here rather than in the stage, so the log
          // survives the handoff from the live view to the report.
          if (p.thought) {
            setThoughts((prev) =>
              prev.some((t) => t.seq === p.thought!.seq)
                ? prev : [...prev, p.thought!]);
          }
          if (p.map_nodes && p.map_nodes.length) setGraph(p.map_nodes[0]);
          if (p.node) {
            const node = p.node;
            const failed = p.thought?.ok === false;
            setTrail((prev) => {
              if (prev.visited.has(node) && !failed) return prev;
              const visited = new Set(prev.visited).add(node);
              const failedSet = failed
                ? new Set(prev.failed).add(node) : prev.failed;
              return { visited, failed: failedSet };
            });
          }
        });
        run.current = r;
        setBReport(await r.done);
      } else {
        const r = startRun(url, setProgress);
        run.current = r;
        setReport(await r.done);
      }
      setPhase("done");
      window.scrollTo({ top: 0, behavior: "auto" });
    } catch (e) {
      setError(e instanceof Error ? e.message
                                  : "The run could not be completed.");
      setPhase("error");
    }
  }, [mode]);

  const reset = useCallback(() => {
    run.current?.cancel();
    run.current = null;
    setReport(null);
    setBReport(null);
    setThoughts([]);
    setBProgress(INITIAL_BEHAVIOUR);
    setGraph({ nodes: [], edges: [] });
    setTrail({ visited: new Set(["start"]), failed: new Set() });
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
        <Portal onDeploy={deploy} busy={busy} mode={mode} onMode={setMode} />
        <Sections />
      </div>

      {/* Running. */}
      {phase === "running" && mode === "behaviour" && (
        <div className="grid min-h-dvh place-items-center py-20">
          <BehaviourStage
            progress={bProgress}
            thoughts={thoughts}
            graph={graph}
            visited={trail.visited}
            failed={trail.failed}
            target={target}
            live={isLive()}
          />
        </div>
      )}

      {phase === "running" && mode === "security" && (
        <div className="grid min-h-dvh place-items-center py-20">
          <div className="w-full">
            <MissionStage progress={progress} />
            <p className="mono mx-auto mt-10 max-w-5xl px-6"
               style={{ color: "var(--color-dim)" }}>
              {isLive()
                ? `requests // ${progress.requests ?? 0}`
                : "simulated run // set NEXT_PUBLIC_AGENTQA_API to drive the real analyzer"}
            </p>
          </div>
        </div>
      )}

      {/* Done. */}
      {phase === "done" && bReport && (
        <BehaviourResults report={bReport} onReset={reset} />
      )}
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
