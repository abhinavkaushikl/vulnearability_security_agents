"use client";

import { useEffect, useRef } from "react";
import type { MapEdge, MapNode } from "@/lib/behaviourTypes";
import { prefersReduced } from "@/lib/motion";

/**
 * §14 — the agent as a small digital creature moving through the journey it
 * is walking. Nodes light as it reaches them.
 *
 * The graph is the backend's; the LAYOUT is ours. `agent.py :: map_nodes`
 * emits nodes and edges and no coordinates, deliberately — putting positions
 * in the backend would freeze a visual decision somewhere it cannot be
 * changed, and the interface has to lay this out differently at 380px than
 * at 1400px anyway.
 *
 * Rendered on a fixed logical buffer and upscaled with nearest-neighbour, the
 * same technique MissionStage uses: it keeps the pixels square at any
 * viewport and makes fill cost independent of screen size.
 */

const W = 520;
const H = 250;

const AMBER = "#ffb000";
const BONE = "#edeae3";
const ANOMALY = "#ff2d55";
const DIM = "#3a3a44";
const LINE = "#1b1b22";

/** Left gutter for the journey name, so a row reads as a named route. */
const GUTTER = 96;
const RIGHT = 18;
const TOP = 34;
const ROW_GAP = 42;

type Placed = MapNode & { px: number; py: number; row: number; above: boolean };
type Row = { journeyId: string; name: string; y: number };

/**
 * One row per journey.
 *
 * The first version laid all the nodes on a single serpentine, which read as
 * one long route the agent never actually walks — the journeys are separate
 * attempts from the same entry point, not a sequence — and at nineteen nodes
 * the labels collided into an unreadable band. A row per journey says the
 * true thing and has room to say it.
 *
 * Labels alternate above and below the line. At this node spacing a single
 * baseline cannot fit them, and alternating doubles the room without
 * shrinking the type past legibility.
 */
function layout(nodes: MapNode[]): { placed: Placed[]; rows: Row[] } {
  const byJourney = new Map<string, MapNode[]>();
  for (const n of nodes) {
    if (!n.journey_id) continue;
    const list = byJourney.get(n.journey_id) ?? [];
    list.push(n);
    byJourney.set(n.journey_id, list);
  }

  const rows: Row[] = [];
  const placed: Placed[] = [];
  let row = 0;

  for (const [journeyId, steps] of byJourney) {
    steps.sort((a, b) => a.index - b.index);
    const y = TOP + row * ROW_GAP;
    rows.push({ journeyId, name: steps[0].journey ?? journeyId, y });

    const usable = W - GUTTER - RIGHT;
    const step = steps.length > 1 ? usable / (steps.length - 1) : 0;
    steps.forEach((n, i) => {
      placed.push({
        ...n, row, py: y, above: i % 2 === 0,
        px: GUTTER + (steps.length > 1 ? i * step : usable / 2),
      });
    });
    row++;
  }

  // The entry point sits in the gutter, level with the middle row: every
  // journey starts from it, and the edges fan out to say so.
  const entry = nodes.find((n) => n.id === "start");
  if (entry) {
    placed.push({
      ...entry, row: -1, above: true,
      px: 26, py: TOP + ((rows.length - 1) * ROW_GAP) / 2,
    });
  }
  return { placed, rows };
}

export default function JourneyMap({
  nodes, edges, activeId, visited, failed,
}: {
  nodes: MapNode[];
  edges: MapEdge[];
  activeId: string | null;
  visited: Set<string>;
  failed: Set<string>;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const live = useRef({ nodes, edges, activeId, visited, failed });
  live.current = { nodes, edges, activeId, visited, failed };

  useEffect(() => {
    const c = canvas.current;
    if (!c) return;
    const ctx = c.getContext("2d", { alpha: false });
    if (!ctx) return;

    const reduced = prefersReduced();
    c.width = W;
    c.height = H;
    ctx.imageSmoothingEnabled = false;

    let raf = 0;
    let t = 0;
    // The agent's own position, sprung toward the active node. It TRAVELS —
    // §14 asks for a creature moving between nodes, and teleporting it would
    // lose the one thing the map is for: showing where the agent is going.
    const pos = { x: W / 2, y: H / 2, vx: 0, vy: 0 };
    let started = false;
    const sparks: { x: number; y: number; vx: number; vy: number;
                    life: number; c: string }[] = [];

    const glow = (() => {
      const g = document.createElement("canvas");
      g.width = g.height = 64;
      const gc = g.getContext("2d")!;
      const grad = gc.createRadialGradient(32, 32, 0, 32, 32, 32);
      grad.addColorStop(0, "rgba(255,176,0,0.34)");
      grad.addColorStop(0.45, "rgba(255,176,0,0.11)");
      grad.addColorStop(1, "rgba(255,176,0,0)");
      gc.fillStyle = grad;
      gc.fillRect(0, 0, 64, 64);
      return g;
    })();

    const px = (x: number, y: number, w: number, h: number, fill: string) => {
      ctx.fillStyle = fill;
      ctx.fillRect(Math.round(x), Math.round(y), w, h);
    };

    /** The same 7x9 creature the mission stage uses, so it reads as one agent. */
    const drawAgent = (x: number, y: number, frame: number, moving: boolean) => {
      const body = BONE;
      ctx.drawImage(glow, x - 23, y - 20, 52, 52);
      px(x + 2, y, 3, 3, body);
      px(x + 1, y + 3, 5, 4, body);
      px(x, y + 4, 1, 2, body);
      px(x + 6, y + 4, 1, 2, AMBER);
      if (moving && frame === 0) {
        px(x + 1, y + 7, 2, 2, body);
        px(x + 4, y + 7, 2, 2, body);
      } else if (moving) {
        px(x + 2, y + 7, 2, 2, body);
        px(x + 3, y + 7, 3, 2, body);
      } else {
        px(x + 1, y + 7, 2, 2, body);
        px(x + 4, y + 7, 2, 2, body);
      }
    };

    const frame = () => {
      const { nodes: ns, edges: es, activeId: aid, visited: vis,
              failed: fail } = live.current;
      t += reduced ? 0 : 1;

      ctx.fillStyle = "#050506";
      ctx.fillRect(0, 0, W, H);

      if (!ns.length) {
        ctx.font = "7px ui-monospace, monospace";
        ctx.fillStyle = DIM;
        ctx.textAlign = "center";
        ctx.fillText("MAPPING THE SITE", W / 2, H / 2);
        ctx.textAlign = "left";
        raf = requestAnimationFrame(frame);
        return;
      }

      const { placed, rows } = layout(ns);
      const at = new Map(placed.map((p) => [p.id, p]));

      /* ---- journey names ---------------------------------------------- */
      ctx.font = "6px ui-monospace, monospace";
      for (const r of rows) {
        const steps = placed.filter((p) => p.journey_id === r.journeyId);
        const done = steps.every((p) => vis.has(p.id));
        ctx.fillStyle = done ? "#8b8b93" : "#4a4a55";
        const name = r.name.length > 15 ? r.name.slice(0, 14) + "…" : r.name;
        ctx.fillText(name.toUpperCase(), 8, r.y + 2);
      }

      /* ---- edges ------------------------------------------------------ */
      for (const e of es) {
        const a = at.get(e.from);
        const b = at.get(e.to);
        if (!a || !b) continue;
        const done = vis.has(e.from) && vis.has(e.to);
        ctx.strokeStyle = done ? "rgba(255,176,0,0.30)" : LINE;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(a.px, a.py);
        if (a.row === b.row) {
          ctx.lineTo(b.px, b.py);
        } else {
          // The fan out of the entry point: a shoulder, so the routes read as
          // separate attempts from one place rather than as one long path.
          const midX = (a.px + b.px) / 2;
          ctx.lineTo(midX - 14, a.py);
          ctx.lineTo(midX, b.py);
          ctx.lineTo(b.px, b.py);
        }
        ctx.stroke();

        if (done && !reduced && a.row === b.row) {
          const p = (t * 0.012) % 1;
          px(a.px + (b.px - a.px) * p, a.py + (b.py - a.py) * p, 2, 2,
             "rgba(255,176,0,0.65)");
        }
      }

      /* ---- nodes ------------------------------------------------------ */
      for (const n of placed) {
        const isActive = n.id === aid;
        const isVisited = vis.has(n.id);
        const isFailed = fail.has(n.id);
        const col = isFailed ? ANOMALY : isVisited ? AMBER : DIM;

        if (isActive) {
          const r = 8 + Math.sin(t * 0.09) * 1.6;
          ctx.strokeStyle = "rgba(255,176,0,0.5)";
          ctx.beginPath();
          ctx.arc(n.px, n.py, r, 0, Math.PI * 2);
          ctx.stroke();
        }
        px(n.px - 2, n.py - 2, 4, 4, col);

        // Only the label that can be read is drawn: the active step always,
        // and otherwise every other node, alternating above and below the
        // line. Nineteen labels on one baseline is a smear, not a map.
        const show = isActive || isVisited || n.id === "start";
        if (show) {
          ctx.font = "6px ui-monospace, monospace";
          ctx.fillStyle = isActive ? BONE : isFailed ? ANOMALY : "#7a7a85";
          ctx.textAlign = "center";
          const raw = n.label;
          const label = raw.length > 13 ? raw.slice(0, 12) + "…" : raw;
          ctx.fillText(label, n.px, n.py + (n.above ? -8 : 13));
          ctx.textAlign = "left";
        }
      }

      /* ---- the agent -------------------------------------------------- */
      const target = aid ? at.get(aid) : placed[0];
      if (target) {
        if (!started) {
          pos.x = target.px;
          pos.y = target.py;
          started = true;
        }
        const tx = target.px - 3;
        const ty = target.py - 12;
        if (reduced) {
          pos.x = tx;
          pos.y = ty;
        } else {
          pos.vx = (pos.vx + (tx - pos.x) * 0.055) * 0.82;
          pos.vy = (pos.vy + (ty - pos.y) * 0.055) * 0.82;
          pos.x += pos.vx;
          pos.y += pos.vy;
        }
        const speed = Math.hypot(pos.vx, pos.vy);
        const moving = speed > 0.25;
        if (moving && !reduced && t % 4 === 0) {
          sparks.push({ x: pos.x + 3, y: pos.y + 8, vx: -pos.vx * 0.3,
                        vy: -pos.vy * 0.3 - 0.1, life: 1, c: AMBER });
        }
        drawAgent(pos.x, pos.y, Math.floor(t / 6) % 2, moving);
      }

      for (let i = sparks.length - 1; i >= 0; i--) {
        const s = sparks[i];
        s.x += s.vx;
        s.y += s.vy;
        s.life -= 0.035;
        if (s.life <= 0) {
          sparks.splice(i, 1);
          continue;
        }
        ctx.globalAlpha = s.life;
        px(s.x, s.y, 1, 1, s.c);
        ctx.globalAlpha = 1;
      }

      raf = requestAnimationFrame(frame);
    };

    frame();
    return () => cancelAnimationFrame(raf);
  }, []);

  return (
    <canvas
      ref={canvas}
      aria-hidden
      className="pixelated block w-full"
      style={{ aspectRatio: `${W} / ${H}`, height: "auto" }}
    />
  );
}
