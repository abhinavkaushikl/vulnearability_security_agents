"use client";

import type {
  BehaviourProgress, MapEdge, MapNode, Thought,
} from "@/lib/behaviourTypes";
import JourneyMap from "./JourneyMap";
import AgentHUD from "./AgentHUD";
import ThoughtStream from "./ThoughtStream";

/**
 * The live view: the map, the telemetry and the log, composed.
 *
 * The map graph and the trail through it are passed in rather than derived
 * from `progress`, because they cannot be derived from it safely. The backend
 * emits the node set on exactly one frame — a journey map that reshuffles
 * mid-run is unreadable — and React batches SSE frames, so the single frame
 * carrying it can be collapsed away before it ever reaches a render. They are
 * accumulated in the stream callback in app/page.tsx, which runs once per
 * message. The same applies to the visited trail.
 */
export default function BehaviourStage({
  progress, thoughts, graph, visited, failed, target, live,
}: {
  progress: BehaviourProgress;
  thoughts: Thought[];
  graph: { nodes: MapNode[]; edges: MapEdge[] };
  visited: Set<string>;
  failed: Set<string>;
  target: string;
  live: boolean;
}) {
  const nodeCount = graph.nodes.length;

  return (
    <section className="mx-auto w-full max-w-6xl px-6">
      <span className="sr-only" aria-live="polite">
        {progress.state}. {progress.current_action}
      </span>

      {/* The map is the hero: this is the agent playing through the site. */}
      <div
        className="crt relative overflow-hidden"
        style={{ border: "1px solid var(--color-line)", background: "#050506" }}
      >
        <JourneyMap
          nodes={graph.nodes}
          edges={graph.edges}
          activeId={progress.node}
          visited={visited}
          failed={failed}
        />
        {nodeCount > 0 && (
          <p
            className="mono absolute right-3 top-3"
            style={{ color: "var(--color-dim)" }}
          >
            {visited.size - 1}/{nodeCount - 1} steps
          </p>
        )}
      </div>

      <div className="mt-12 grid gap-14 lg:grid-cols-[1.15fr_1fr] lg:gap-16">
        <AgentHUD progress={progress} target={target} live={live} />
        <ThoughtStream thoughts={thoughts} />
      </div>
    </section>
  );
}
