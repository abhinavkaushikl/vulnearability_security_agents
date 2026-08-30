import type { Progress, Report, Finding, FamilyCoverage } from "./types";
import { ACTS, FAMILY_LABELS } from "./stages";

const API = process.env.NEXT_PUBLIC_AGENTQA_API ?? "";

export const isLive = () => API.length > 0;

export interface Run {
  /** Resolves when the run reaches a terminal status. */
  done: Promise<Report>;
  cancel: () => void;
}

/**
 * POST /analyze -> { assessment_id }, then subscribe to
 * GET /analyze/{id}/stream (SSE) for progress, GET /analyze/{id} for the report.
 * With no API configured we drive the same state machine from a local
 * simulation so the interface is developable without touching a target.
 */
export function startRun(
  url: string,
  onProgress: (p: Progress) => void,
): Run {
  return API ? live(url, onProgress) : simulate(url, onProgress);
}

function live(url: string, onProgress: (p: Progress) => void): Run {
  let es: EventSource | null = null;
  let cancelled = false;

  const done = (async () => {
    const res = await fetch(`${API}/analyze`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ url }),
    });
    if (!res.ok) throw new Error(`analyze failed: ${res.status}`);
    const { assessment_id } = (await res.json()) as { assessment_id: string };

    await new Promise<void>((resolve, reject) => {
      es = new EventSource(`${API}/analyze/${assessment_id}/stream`);
      es.onmessage = (ev) => {
        const p = JSON.parse(ev.data) as Progress;
        onProgress(p);
        if (["COMPLETED", "PARTIAL", "BLOCKED", "FAILED"].includes(p.status)) {
          es?.close();
          resolve();
        }
      };
      es.onerror = () => {
        es?.close();
        cancelled ? resolve() : reject(new Error("progress stream lost"));
      };
    });

    const rep = await fetch(`${API}/analyze/${assessment_id}`);
    if (!rep.ok) throw new Error(`report failed: ${rep.status}`);
    return (await rep.json()) as Report;
  })();

  return { done, cancel: () => { cancelled = true; es?.close(); } };
}

/* ---------------------------------------------------------------- simulation */

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function simulate(url: string, onProgress: (p: Progress) => void): Run {
  let cancelled = false;
  const done = (async () => {
    let pct = 0;
    for (const act of ACTS) {
      const span = 100 / ACTS.length;
      const steps = 14;
      for (let i = 0; i < steps; i++) {
        if (cancelled) break;
        pct = Math.min(100, pct + span / steps);
        onProgress({
          status: act.status,
          pct,
          label: act.code,
          detail: act.line,
          requests: Math.round((pct / 100) * 17),
        });
        await sleep(90);
      }
    }
    onProgress({ status: "PARTIAL", pct: 100, label: "ASSESSMENT COMPLETE",
                 detail: "42 of 144 controls decided.", requests: 17 });
    return sampleReport(url);
  })();
  return { done, cancel: () => { cancelled = true; } };
}

/**
 * Shape-accurate sample data. Values match what the engine actually produces
 * against tests/fixtures/site — a deliberately broken fixture — so the UI is
 * never designed against numbers the backend could not emit.
 */
function sampleReport(target: string): Report {
  const findings: Finding[] = [
    {
      control_id: "WEB-01", family: "WEB", title: "Content-Security-Policy enforced",
      severity: "HIGH", native_result: "FAIL", result: "NO",
      observed_value: "no content-security-policy header on the main document",
      unknown_reason: null,
      evidence: "Response captured for GET / — header absent from 14 responses.",
      source_file: "Rules/03_http_browser_assets.md", source_line: 11,
    },
    {
      control_id: "NET-03", family: "NET", title: "HSTS with an approved max-age",
      severity: "HIGH", native_result: "FAIL", result: "NO",
      observed_value: "strict-transport-security: absent",
      unknown_reason: null,
      evidence: "Policy requires max-age >= 15768000. No header observed.",
      source_file: "Rules/02_network_dns_tls_edge.md", source_line: 13,
    },
    {
      control_id: "WEB-05", family: "WEB", title: "Session cookie flags",
      severity: "CRITICAL", native_result: "FAIL", result: "NO",
      observed_value: "sessionid — Secure=false, HttpOnly=false, SameSite=None",
      unknown_reason: null,
      evidence: "Cookie read from the discovery context after navigation.",
      source_file: "Rules/03_http_browser_assets.md", source_line: 15,
    },
    {
      control_id: "WEB-09", family: "WEB", title: "No secrets in client-side source",
      severity: "CRITICAL", native_result: "FAIL", result: "NO",
      observed_value: "aws_access_key_id in /static/app.js (value redacted at capture)",
      unknown_reason: null,
      evidence: "Two literals matched. Neither is retained in the bundle.",
      source_file: "Rules/03_http_browser_assets.md", source_line: 19,
    },
    {
      control_id: "WEB-02", family: "WEB", title: "X-Content-Type-Options: nosniff",
      severity: "MEDIUM", native_result: "PASS", result: "YES",
      observed_value: "x-content-type-options: nosniff",
      unknown_reason: null,
      evidence: "Present on the main document and 11 subresources.",
      source_file: "Rules/03_http_browser_assets.md", source_line: 12,
    },
    {
      control_id: "NET-02", family: "NET", title: "TLS at or above the baseline",
      severity: "CRITICAL", native_result: "PASS", result: "YES",
      observed_value: "TLSv1.3 · expires in 61 days · SAN matches host",
      unknown_reason: null,
      evidence: "Out-of-band ssl handshake; the browser was not involved.",
      source_file: "Rules/02_network_dns_tls_edge.md", source_line: 12,
    },
    {
      control_id: "PERF-01", family: "PERF", title: "Core Web Vitals at field p75",
      severity: "MEDIUM", native_result: "INFORMATIONAL", result: "UNKNOWN",
      observed_value: "lab LCP 2410 ms (n=3, fast profile)",
      unknown_reason:
        "PERF-01 asks for the 75th percentile of field data. Twelve lab loads " +
        "from one machine are not a p75 of real users.",
      evidence: "Measurement attached; no verdict claimed.",
      source_file: "Rules/10_availability_performance_resilience.md", source_line: 11,
    },
    {
      control_id: "IAM-03", family: "IAM", title: "Horizontal access-control separation",
      severity: "CRITICAL", native_result: "NOT_TESTABLE", result: "UNKNOWN",
      observed_value: null,
      unknown_reason:
        "Marked P in the pack, but proving it needs two accounts compared " +
        "against each other, which 19_test_modes_safety.md forbids publicly. " +
        "The safety model wins.",
      evidence: "No request was made.",
      source_file: "Rules/04_identity_auth_sessions.md", source_line: 14,
    },
    {
      control_id: "PCI-10", family: "PCI", title: "Cardholder data environment scope",
      severity: "CRITICAL", native_result: "NOT_TESTABLE", result: "UNKNOWN",
      observed_value: null,
      unknown_reason:
        "The pack's own words: never treat a web header or SSL scan as proof " +
        "of PCI compliance. Needs an audited attestation.",
      evidence: "No request was made.",
      source_file: "Rules/07_payments_pci_dss.md", source_line: 20,
    },
  ];

  const families: FamilyCoverage[] = [
    { family: "NET",  decided: 6,  total: 9,   failed: 1 },
    { family: "WEB",  decided: 10, total: 12,  failed: 4 },
    { family: "PERF", decided: 4,  total: 8,   failed: 0 },
    { family: "PRIV", decided: 5,  total: 11,  failed: 1 },
    { family: "A11Y", decided: 3,  total: 7,   failed: 0 },
    { family: "IAM",  decided: 1,  total: 10,  failed: 0 },
    { family: "PCI",  decided: 0,  total: 12,  failed: 0 },
    { family: "FLOW", decided: 0,  total: 14,  failed: 0 },
  ].map((f) => ({ ...f, label: FAMILY_LABELS[f.family] ?? f.family }));

  return {
    assessment_id: "8f3a21c4d90b47e2",
    target,
    status: "PARTIAL",
    coverage_pct: 29.2,
    tally: {
      total: 144, yes: 18, no: 12, not_applicable: 12, unknown: 102,
      native_pass: 18, native_fail: 12, native_warn: 6, native_na: 12,
      native_informational: 4, native_not_testable: 92,
    },
    families,
    findings,
    route: [
      { kind: "navigate", target, reason: "single instrumented page load feeding all in-page collectors", required_by: ["WEB-01", "WEB-02", "WEB-05", "NET-03"] },
      { kind: "scroll_to_fold", target, reason: "settle lazy-loaded resources for LCP and mixed-content checks", required_by: ["PERF-02", "WEB-08"] },
      { kind: "probe_http_scheme", target, reason: "HTTP to HTTPS redirect chain", required_by: ["NET-01"] },
      { kind: "fetch_well_known", target, reason: "security.txt and robots.txt", required_by: ["IR-05"] },
      { kind: "probe_benign_404", target, reason: "server error-page disclosure", required_by: ["WEB-10", "APP-07"] },
    ],
    performance: [
      { profile: "fast", ttfb_p50: 118, lcp_p50: 2410, load_p95: 3180, n: 3, status: "OK" },
      { profile: "4g",   ttfb_p50: 244, lcp_p50: 3960, load_p95: 5120, n: 3, status: "OK" },
      { profile: "3g",   ttfb_p50: 612, lcp_p50: 7840, load_p95: 11240, n: 3, status: "OK" },
      { profile: "slow", ttfb_p50: 1490, lcp_p50: null, load_p95: null, n: 1, status: "PARTIAL" },
    ],
    collectors_run: ["SELF", "HDR", "CK", "WS", "DOM", "JS", "NET", "CON", "TIM",
                     "CWV", "FRM", "LNK", "3P", "CACHE", "RDR", "TLS", "DNS", "WK", "ERR"],
    duration_seconds: 96.4,
    llm_model: "qwen3-coder",
    blocked_reason: null,
  };
}
