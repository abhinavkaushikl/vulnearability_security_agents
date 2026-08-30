"use client";

import { useEffect, useRef } from "react";

/**
 * A dark room with a machine running in it. One fullscreen quad, one fragment
 * shader — three.js would be ~600 KB to draw two triangles. Movement is kept
 * near the threshold of perception on purpose; if you notice it, it is too much.
 */

const VERT = `
attribute vec2 p;
void main() { gl_Position = vec4(p, 0.0, 1.0); }
`;

const FRAG = `
precision mediump float;
uniform vec2  u_res;
uniform float u_time;
uniform vec2  u_mouse;
uniform float u_energy;   // 0 idle -> 1 agent deployed

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
}

float noise(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i + vec2(0.0, 0.0)), hash(i + vec2(1.0, 0.0)), u.x),
             mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x), u.y);
}

// Faint contour lines — a topology of the site being walked, not a grid.
float topology(vec2 uv, float t) {
  float n = noise(uv * 3.2 + vec2(t * 0.02, t * 0.013));
  n += 0.5 * noise(uv * 6.4 - vec2(t * 0.017, 0.0));
  float bands = abs(fract(n * 5.0) - 0.5);
  return smoothstep(0.46, 0.5, 1.0 - bands);
}

void main() {
  vec2 uv = gl_FragCoord.xy / u_res.xy;
  vec2 asp = vec2(u_res.x / u_res.y, 1.0);
  vec2 suv = uv * asp;

  vec3 col = vec3(0.02, 0.02, 0.024);

  // Contours, barely there.
  float topo = topology(suv, u_time);
  col += vec3(0.085, 0.085, 0.105) * topo * (0.62 + 0.38 * u_energy);

  // Amber pool that follows the pointer with a long lag (lag lives in JS).
  float d = distance(suv, u_mouse * asp);
  float glow = exp(-d * 3.4) * (0.05 + 0.16 * u_energy);
  col += vec3(1.0, 0.69, 0.0) * glow;

  // Slow horizontal sweep, like a machine refreshing its own display.
  float sweep = smoothstep(0.0, 0.04, abs(fract(uv.y - u_time * 0.035) - 0.5));
  col *= 0.94 + 0.06 * sweep;

  // Film grain keeps the flat black from banding on OLED.
  float g = hash(gl_FragCoord.xy + fract(u_time) * 100.0);
  col += (g - 0.5) * 0.016;

  gl_FragColor = vec4(col, 1.0);
}
`;

function compile(gl: WebGLRenderingContext, type: number, src: string) {
  const s = gl.createShader(type)!;
  gl.shaderSource(s, src);
  gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
    console.warn(gl.getShaderInfoLog(s));
    return null;
  }
  return s;
}

export default function AmbientField({ energy = 0 }: { energy?: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const energyRef = useRef(energy);
  energyRef.current = energy;

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const gl =
      canvas.getContext("webgl", { antialias: false, alpha: false, depth: false }) ??
      canvas.getContext("experimental-webgl");
    if (!gl || !(gl instanceof WebGLRenderingContext)) return;

    const vs = compile(gl, gl.VERTEX_SHADER, VERT);
    const fs = compile(gl, gl.FRAGMENT_SHADER, FRAG);
    if (!vs || !fs) return;

    const prog = gl.createProgram()!;
    gl.attachShader(prog, vs);
    gl.attachShader(prog, fs);
    gl.linkProgram(prog);
    gl.useProgram(prog);

    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 3, -1, -1, 3]),
      gl.STATIC_DRAW,
    );
    const loc = gl.getAttribLocation(prog, "p");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);

    const uRes = gl.getUniformLocation(prog, "u_res");
    const uTime = gl.getUniformLocation(prog, "u_time");
    const uMouse = gl.getUniformLocation(prog, "u_mouse");
    const uEnergy = gl.getUniformLocation(prog, "u_energy");

    // Half-resolution is invisible on a field this soft and halves the fill cost.
    const scale = Math.min(window.devicePixelRatio || 1, 1.5) * 0.5;
    const resize = () => {
      canvas.width = Math.floor(window.innerWidth * scale);
      canvas.height = Math.floor(window.innerHeight * scale);
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.uniform2f(uRes, canvas.width, canvas.height);
    };
    resize();
    window.addEventListener("resize", resize);

    const target = { x: 0.5, y: 0.5 };
    const eased = { x: 0.5, y: 0.5 };
    const onMove = (e: PointerEvent) => {
      target.x = e.clientX / window.innerWidth;
      target.y = 1 - e.clientY / window.innerHeight;
    };
    window.addEventListener("pointermove", onMove, { passive: true });

    let raf = 0;
    let e0 = 0;
    const start = performance.now();
    const frame = () => {
      const t = (performance.now() - start) / 1000;
      // The pool trails the cursor: inertia, not tracking.
      eased.x += (target.x - eased.x) * 0.045;
      eased.y += (target.y - eased.y) * 0.045;
      e0 += (energyRef.current - e0) * 0.03;

      gl.uniform1f(uTime, reduced ? 0 : t);
      gl.uniform2f(uMouse, eased.x, eased.y);
      gl.uniform1f(uEnergy, e0);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      raf = requestAnimationFrame(frame);
    };
    frame();

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      window.removeEventListener("pointermove", onMove);
    };
  }, []);

  return (
    <div className="fixed inset-0 -z-10" aria-hidden>
      <canvas ref={ref} className="h-full w-full" />
      <div className="vignette pointer-events-none absolute inset-0" />
    </div>
  );
}
