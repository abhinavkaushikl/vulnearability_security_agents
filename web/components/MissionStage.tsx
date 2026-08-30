"use client";

import { useEffect, useRef } from "react";
import type { Progress } from "@/lib/types";
import { actForStatus } from "@/lib/stages";
import { prefersReduced } from "@/lib/motion";

/**
 * The signature element: a side-scrolling CRT stage whose level *is* the
 * pipeline. Rendered on a 360x160 logical buffer and upscaled with
 * nearest-neighbour, which is what keeps the pixels square at any viewport
 * and keeps fill cost independent of screen size.
 *
 * Canvas 2D rather than WebGL on purpose — this is a few hundred axis-aligned
 * rects per frame, and 2D gives crisp integer pixels for free.
 */

const W = 360;
const H = 132;
const GROUND = 96;

const AMBER = "#ffb000";
const BONE = "#edeae3";
const ANOMALY = "#ff2d55";
const DIM = "#3a3a44";

type Prop = {
  x: number;
  y: number;
  label: string;
  hit: boolean;
  anomaly: boolean;
  life: number;
};

type Mote = { x: number; y: number; vx: number; vy: number; life: number; c: string };

/** Deterministic noise so the terrain is stable across frames, not jittering. */
function rnd(seed: number) {
  const s = Math.sin(seed * 127.1) * 43758.5453;
  return s - Math.floor(s);
}

export default function MissionStage({ progress }: { progress: Progress }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const prog = useRef(progress);
  prog.current = progress;

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
    let scroll = 0;
    let props: Prop[] = [];
    let motes: Mote[] = [];
    let spawnAt = 0;

    /* The threat: appears once during EVALUATING, is analyzed, dissolves. */
    const threat = { x: W + 60, active: false, done: false, scan: 0, hp: 1 };
    let agentIdle = 0;

    /** Pre-rendered falloff sprite. A flat rect reads as a box, not a glow. */
    const makeGlow = (rgb: string) => {
      const g = document.createElement("canvas");
      g.width = g.height = 64;
      const gc = g.getContext("2d")!;
      const grad = gc.createRadialGradient(32, 32, 0, 32, 32, 32);
      grad.addColorStop(0, `rgba(${rgb},0.30)`);
      grad.addColorStop(0.45, `rgba(${rgb},0.10)`);
      grad.addColorStop(1, `rgba(${rgb},0)`);
      gc.fillStyle = grad;
      gc.fillRect(0, 0, 64, 64);
      return g;
    };
    const glowAmber = makeGlow("255,176,0");
    const glowRed = makeGlow("255,45,85");

    const stamp = (g: HTMLCanvasElement, cx: number, cy: number, r: number) => {
      ctx.drawImage(g, cx - r, cy - r, r * 2, r * 2);
    };

    const px = (x: number, y: number, w: number, h: number, fill: string) => {
      ctx.fillStyle = fill;
      ctx.fillRect(Math.round(x), Math.round(y), w, h);
    };

    /** 7x9 pixel agent. Two-frame run cycle; a third frame reads as noise. */
    const drawAgent = (x: number, y: number, frame: number, scanning: boolean) => {
      const body = scanning ? AMBER : BONE;
      px(x + 2, y, 3, 3, body);              // head
      px(x + 1, y + 3, 5, 4, body);          // torso
      px(x, y + 4, 1, 2, body);              // trailing arm
      px(x + 6, y + 4, 1, 2, scanning ? AMBER : body);
      if (frame === 0) {
        px(x + 1, y + 7, 2, 2, body);
        px(x + 4, y + 7, 2, 2, body);
      } else {
        px(x + 2, y + 7, 2, 2, body);
        px(x + 3, y + 7, 3, 2, body);
      }
      // The agent carries its own light source.
      stamp(glowAmber, x + 3, y + 4, scanning ? 30 : 20);
    };

    /** The threat is drawn as an unresolved shape — never a monster with a face. */
    const drawThreat = (x: number, y: number, wob: number, dissolve: number) => {
      const a = 1 - dissolve;
      const col = `rgba(255,45,85,${a.toFixed(2)})`;
      for (let i = 0; i < 5; i++) {
        const o = Math.sin(t * 0.06 + i) * wob;
        px(x + i * 2, y + i - o, 3, 8 - i, col);
        px(x - i * 2, y + i + o, 3, 8 - i, col);
      }
      px(x - 1, y - 4, 4, 4, col);
      ctx.globalAlpha = a;
      stamp(glowRed, x, y + 2, 26);
      ctx.globalAlpha = 1;
    };

    const burst = (x: number, y: number, n: number, col: string) => {
      for (let i = 0; i < n; i++) {
        motes.push({
          x, y,
          vx: (Math.random() - 0.5) * 1.6,
          vy: (Math.random() - 0.5) * 1.6 - 0.3,
          life: 1,
          c: col,
        });
      }
    };

    const frame = () => {
      const p = prog.current;
      const act = actForStatus(p.status);
      const evaluating = p.status === "EVALUATING";
      const aggregating = p.status === "AGGREGATING" || p.pct >= 99;

      t += reduced ? 0 : 1;
      const speed = reduced ? 0 : agentIdle > 0 ? 0.35 : 1.35;
      scroll += speed;

      /* ---- ground and parallax -------------------------------------- */
      ctx.fillStyle = "#050506";
      ctx.fillRect(0, 0, W, H);

      // Far layer: the site's structure, implied not depicted.
      for (let i = 0; i < 26; i++) {
        const bx = ((i * 34 - scroll * 0.14) % (W + 40)) - 20;
        const h = 8 + rnd(i + act.id * 7) * 26;
        px(bx, GROUND - h - 26, 1, h, "#141419");
        px(bx + 12, GROUND - h * 0.6 - 26, 1, h * 0.6, "#101015");
      }

      // Mid layer: connective lines — the link graph the agent is walking.
      ctx.strokeStyle = "#16161c";
      ctx.lineWidth = 1;
      ctx.beginPath();
      for (let i = 0; i < 7; i++) {
        const bx = ((i * 96 - scroll * 0.28) % (W + 130)) - 65;
        const arc = 16 + rnd(i * 3.7 + act.id) * 22;
        ctx.moveTo(bx, GROUND - 6);
        ctx.quadraticCurveTo(bx + 34, GROUND - 6 - arc, bx + 68, GROUND - 6);
      }
      ctx.stroke();

      // Ground: a dashed rule, so motion is legible even when empty.
      for (let x = -(scroll % 8); x < W; x += 8) px(x, GROUND, 4, 1, "#26262e");
      px(0, GROUND + 1, W, 1, "#0e0e12");

      /* ---- props ------------------------------------------------------ */
      if (!reduced && t > spawnAt) {
        spawnAt = t + 46 + Math.random() * 30;
        const label = act.props[Math.floor(Math.random() * act.props.length)];
        // Anomalies only exist where the engine can actually fail a control.
        const anomaly = evaluating && Math.random() < 0.26;
        props.push({
          x: W + 20,
          y: GROUND - 34 - Math.random() * 26,
          label,
          hit: false,
          anomaly,
          life: 1,
        });
      }

      const agentX = 74;
      props = props.filter((pr) => {
        pr.x -= speed;
        if (!pr.hit && pr.x <= agentX + 6) {
          pr.hit = true;
          burst(pr.x, pr.y + 4, pr.anomaly ? 10 : 6, pr.anomaly ? ANOMALY : AMBER);
        }
        if (pr.hit) pr.life -= 0.012;

        const col = pr.anomaly ? ANOMALY : pr.hit ? AMBER : DIM;
        const alpha = Math.max(0, pr.life);
        ctx.globalAlpha = alpha;

        // node
        px(pr.x, pr.y, 3, 3, col);
        if (pr.hit) {
          stamp(pr.anomaly ? glowRed : glowAmber, pr.x + 1, pr.y + 1, 13);
        }
        // tether to ground
        ctx.fillStyle = "#1b1b22";
        ctx.fillRect(pr.x + 1, pr.y + 3, 1, GROUND - pr.y - 3);

        ctx.font = "6px ui-monospace, monospace";
        ctx.fillStyle = col;
        ctx.fillText(pr.anomaly && pr.hit ? "ANOMALY" : pr.label, pr.x + 7, pr.y + 4);
        ctx.globalAlpha = 1;

        return pr.x > -40 && pr.life > 0;
      });

      /* ---- the threat encounter --------------------------------------- */
      if (evaluating && !threat.done && !threat.active && p.pct > 0) {
        threat.active = true;
        threat.x = W + 40;
      }
      if (threat.active) {
        if (threat.x > 150) {
          threat.x -= speed * 0.9;
        } else {
          // The agent does not fight it. It stops and reads it.
          agentIdle = 1;
          threat.scan = Math.min(1, threat.scan + 0.006);
          if (threat.scan > 0.55) threat.hp = Math.max(0, threat.hp - 0.012);

          // scan beam
          ctx.strokeStyle = `rgba(255,176,0,${(0.5 + Math.sin(t * 0.2) * 0.2).toFixed(2)})`;
          ctx.beginPath();
          ctx.moveTo(agentX + 8, GROUND - 5);
          ctx.lineTo(threat.x - 6, GROUND - 8);
          ctx.stroke();

          if (threat.hp <= 0) {
            burst(threat.x, GROUND - 12, 26, ANOMALY);
            threat.active = false;
            threat.done = true;
            agentIdle = 0;
          }
        }
        if (threat.active) {
          drawThreat(threat.x, GROUND - 12, 1.4, 1 - threat.hp);
          if (threat.scan > 0.2) {
            ctx.font = "6px ui-monospace, monospace";
            ctx.fillStyle = AMBER;
            const meta = ["SEVERITY", "IMPACT", "CONFIDENCE", "EVIDENCE"];
            meta.forEach((m, i) => {
              if (threat.scan > 0.2 + i * 0.12) {
                ctx.fillText(m, threat.x + 16, GROUND - 30 + i * 8);
              }
            });
          }
        }
      }

      /* ---- motes ------------------------------------------------------- */
      motes = motes.filter((m) => {
        m.x += m.vx;
        m.y += m.vy;
        m.vy += 0.012;
        m.life -= 0.02;
        ctx.globalAlpha = Math.max(0, m.life);
        px(m.x, m.y, 1, 1, m.c);
        ctx.globalAlpha = 1;
        return m.life > 0;
      });

      /* ---- the agent ---------------------------------------------------- */
      const bob = agentIdle > 0 ? 0 : Math.floor(t / 7) % 2;
      drawAgent(agentX, GROUND - 9 - (bob ? 1 : 0), Math.floor(t / 6) % 2, agentIdle > 0);

      /* ---- the number the run is walking toward ------------------------- */
      if (aggregating) {
        ctx.font = "700 46px ui-sans-serif, system-ui, sans-serif";
        ctx.textAlign = "center";
        ctx.fillStyle = "rgba(255,176,0,0.16)";
        ctx.fillText(String(Math.round(p.pct)), W / 2, GROUND - 34);
        ctx.textAlign = "left";
      }

      /* ---- HUD ---------------------------------------------------------- */
      ctx.font = "6px ui-monospace, monospace";
      ctx.fillStyle = "#55555e";
      ctx.fillText(`STAGE 0${act.id} / 06`, 6, 12);
      ctx.textAlign = "right";
      ctx.fillStyle = AMBER;
      ctx.fillText(`${p.pct.toFixed(0)}%`, W - 6, 12);
      ctx.textAlign = "left";

      // progress rail
      px(6, 16, W - 12, 1, "#1b1b22");
      px(6, 16, Math.max(1, ((W - 12) * p.pct) / 100), 1, AMBER);

      raf = requestAnimationFrame(frame);
    };

    frame();
    return () => cancelAnimationFrame(raf);
  }, []);

  const act = actForStatus(progress.status);

  return (
    <section
      className="relative mx-auto w-full max-w-5xl px-6"
      aria-live="polite"
      aria-atomic="true"
    >
      <span className="sr-only">
        {progress.label}. {progress.pct.toFixed(0)} percent complete.
      </span>

      <div
        className="crt relative overflow-hidden"
        style={{ border: "1px solid var(--color-line)", background: "#050506" }}
      >
        <canvas
          ref={canvas}
          aria-hidden
          className="pixelated block w-full"
          style={{ aspectRatio: `${W} / ${H}`, height: "auto" }}
        />
      </div>

      <div className="mt-6 flex flex-col gap-2 md:flex-row md:items-baseline md:justify-between">
        <p className="h-display text-[clamp(1.5rem,3.5vw,2.5rem)]">{act.code}</p>
        <p className="mono max-w-[46ch] md:text-right" style={{ letterSpacing: "0.06em" }}>
          {progress.detail ?? act.line}
        </p>
      </div>
    </section>
  );
}
