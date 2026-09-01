"use client";

import { useEffect, useRef, useState } from "react";
import { useMagnetic, prefersReduced } from "@/lib/motion";

export type Mode = "security" | "behaviour";

/** The two things the agent can be sent in to do. They are different runs
 *  against different questions, so the choice is made before deployment
 *  rather than presented as a toggle on a result. */
const MODES: { id: Mode; label: string; line: string; cursor: string }[] = [
  {
    id: "behaviour",
    label: "Behaviour",
    line: "An AI user browses the site and we measure what it experiences.",
    cursor: "DEPLOY USER AGENT",
  },
  {
    id: "security",
    label: "Security",
    line: "144 controls read from the rule pack, evaluated against one page load.",
    cursor: "DEPLOY AGENT",
  },
];

/**
 * The gateway. On focus, particles drift inward and the frame lights; the
 * submit control is a hexagonal aperture rather than a rectangle, and it
 * follows the pointer within its own radius.
 */
export default function Portal({
  onDeploy,
  busy,
  mode = "behaviour",
  onMode,
}: {
  onDeploy: (url: string) => void;
  busy: boolean;
  mode?: Mode;
  onMode?: (m: Mode) => void;
}) {
  const [value, setValue] = useState("");
  const [focused, setFocused] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const btn = useMagnetic<HTMLButtonElement>(0.4, 90);
  const particles = useRef<HTMLCanvasElement>(null);

  /* Inward-drifting motes, alive only while the field has focus. */
  useEffect(() => {
    const c = particles.current;
    if (!c || prefersReduced()) return;
    const ctx = c.getContext("2d");
    if (!ctx) return;

    const dpr = Math.min(devicePixelRatio || 1, 2);
    const size = () => {
      const r = c.getBoundingClientRect();
      c.width = r.width * dpr;
      c.height = r.height * dpr;
    };
    size();
    window.addEventListener("resize", size);

    type P = { x: number; y: number; a: number; s: number };
    let pool: P[] = [];
    let raf = 0;

    const frame = () => {
      ctx.clearRect(0, 0, c.width, c.height);
      if (focused && pool.length < 46 && Math.random() > 0.55) {
        const edge = Math.random();
        pool.push({
          x: edge < 0.5 ? Math.random() * c.width : Math.random() < 0.5 ? 0 : c.width,
          y: edge < 0.5 ? (Math.random() < 0.5 ? 0 : c.height) : Math.random() * c.height,
          a: 0,
          s: 0.006 + Math.random() * 0.012,
        });
      }
      const cx = c.width / 2;
      const cy = c.height / 2;
      pool = pool.filter((p) => {
        p.a = Math.min(1, p.a + 0.04);
        p.x += (cx - p.x) * p.s;
        p.y += (cy - p.y) * p.s;
        const d = Math.hypot(cx - p.x, cy - p.y);
        ctx.fillStyle = `rgba(255,176,0,${(p.a * Math.min(1, d / 60) * 0.55).toFixed(3)})`;
        ctx.fillRect(p.x, p.y, dpr, dpr);
        return d > 8;
      });
      if (!focused) pool = pool.filter((p) => (p.a -= 0.05) > 0);
      raf = requestAnimationFrame(frame);
    };
    frame();

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", size);
    };
  }, [focused]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const raw = value.trim();
    if (!raw) {
      setError("Enter a URL to analyze.");
      return;
    }
    const withScheme = /^https?:\/\//i.test(raw) ? raw : `https://${raw}`;
    let parsed: URL;
    try {
      parsed = new URL(withScheme);
    } catch {
      setError(`${raw} is not a URL the agent can reach.`);
      return;
    }
    if (!parsed.hostname.includes(".")) {
      setError(`${parsed.hostname} has no public domain. Use a full hostname.`);
      return;
    }
    setError(null);
    onDeploy(parsed.toString());
  };

  const active = MODES.find((m) => m.id === mode) ?? MODES[0];

  return (
    <section className="relative mx-auto mt-16 w-full max-w-3xl px-6 md:mt-20">
      {/* Mission select. Two runs, two questions — never one with a switch. */}
      <div role="radiogroup" aria-label="What to send the agent in to do"
           className="mb-6 flex flex-wrap items-center gap-x-8 gap-y-3">
        {MODES.map((m) => (
          <button
            key={m.id}
            type="button"
            role="radio"
            aria-checked={m.id === mode}
            disabled={busy}
            onClick={() => onMode?.(m.id)}
            data-cursor={m.label.toUpperCase()}
            className="mono relative pb-2 transition-colors disabled:opacity-40"
            style={{ color: m.id === mode ? "var(--color-bone)"
                                          : "var(--color-dim)" }}
          >
            {m.label}
            <span
              className="absolute inset-x-0 bottom-0 block h-px"
              style={{
                background: "var(--color-phos)",
                transform: m.id === mode ? "scaleX(1)" : "scaleX(0)",
                transformOrigin: "left",
                transition: "transform 460ms var(--ease-spring)",
              }}
            />
          </button>
        ))}
      </div>

      <form onSubmit={submit} noValidate>
        <div
          className="relative flex items-center gap-3 px-5 py-4 transition-[border-color,box-shadow,transform] duration-500 md:gap-5 md:px-7 md:py-6"
          style={{
            background: "rgba(12,12,15,0.72)",
            backdropFilter: "blur(14px)",
            border: `1px solid ${focused ? "var(--color-phos)" : "var(--color-line)"}`,
            boxShadow: focused
              ? "0 0 0 1px rgba(255,176,0,0.16), 0 0 62px -18px rgba(255,176,0,0.55)"
              : "none",
            transform: focused ? "scale(1.012)" : "scale(1)",
            transitionTimingFunction: "var(--ease-spring)",
          }}
        >
          <canvas
            ref={particles}
            aria-hidden
            className="pointer-events-none absolute inset-0 h-full w-full"
          />

          <span className="mono hidden shrink-0 md:block" style={{ color: "var(--color-dim)" }}>
            TARGET //
          </span>

          <label htmlFor="target" className="sr-only">
            Website URL to analyze
          </label>
          <input
            id="target"
            name="target"
            type="text"
            inputMode="url"
            autoComplete="url"
            spellCheck={false}
            disabled={busy}
            value={value}
            onChange={(e) => {
              setValue(e.target.value);
              if (error) setError(null);
            }}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            placeholder="Enter a website URL"
            aria-invalid={!!error}
            aria-describedby={error ? "target-error" : undefined}
            className="relative z-10 w-full bg-transparent text-[clamp(1.05rem,2.4vw,1.6rem)] tracking-tight outline-none placeholder:text-[var(--color-dim)] disabled:opacity-40"
          />

          {/* Aperture, not a button. */}
          <button
            ref={btn}
            type="submit"
            disabled={busy}
            data-cursor={active.cursor}
            aria-label={`Deploy the ${active.label.toLowerCase()} agent to this website`}
            className="relative z-10 grid h-14 w-14 shrink-0 place-items-center transition-opacity disabled:opacity-40 md:h-16 md:w-16"
          >
            <svg viewBox="0 0 64 64" className="absolute inset-0 h-full w-full">
              <polygon
                points="32,3 56,17 56,47 32,61 8,47 8,17"
                fill={focused ? "rgba(255,176,0,0.07)" : "transparent"}
                stroke={focused ? "var(--color-phos)" : "var(--color-line-lit)"}
                strokeWidth="1"
                style={{ transition: "all 400ms var(--ease-spring)" }}
              />
              <polygon
                points="32,3 56,17 56,47 32,61 8,47 8,17"
                fill="none"
                stroke="var(--color-phos)"
                strokeWidth="1"
                strokeDasharray="188"
                strokeDashoffset={busy ? 0 : 188}
                style={{ transition: "stroke-dashoffset 900ms ease-out" }}
              />
            </svg>
            <span
              className="relative text-lg leading-none"
              style={{ color: focused ? "var(--color-phos)" : "var(--color-bone)" }}
            >
              →
            </span>
          </button>
        </div>
      </form>

      <p className="mt-6 text-center leading-relaxed"
         style={{ color: "var(--color-ash)" }}>
        {active.line}
      </p>

      <p
        id="target-error"
        role={error ? "alert" : undefined}
        className="mono mt-5 min-h-4 text-center"
        style={{ color: error ? "var(--color-anomaly)" : "var(--color-dim)" }}
      >
        {error ?? (mode === "behaviour"
          ? "Autonomous session // nothing purchased, submitted or deleted // one host only"
          : "Passive mode // 1 navigation + 4 auxiliary requests // nothing submitted")}
      </p>
    </section>
  );
}
