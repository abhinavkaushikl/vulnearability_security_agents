import type { AssessmentStatus } from "./types";

/**
 * The level design is the pipeline. Each act corresponds to a real
 * AssessmentStatus the backend emits — nothing here is decorative fiction.
 */
export interface Act {
  id: number;
  status: AssessmentStatus;
  code: string;      // stage marquee
  line: string;      // what the agent is doing, in the agent's voice
  /** Props the canvas scatters through this act's terrain. */
  props: string[];
}

export const ACTS: Act[] = [
  {
    id: 1,
    status: "PLANNING",
    code: "READING THE PACK",
    line: "144 controls parsed. 42 have a passive evidence route.",
    props: ["NET", "WEB", "IAM", "PCI", "PRIV", "FLOW"],
  },
  {
    id: 2,
    status: "DISCOVERING",
    code: "AGENT DEPLOYED",
    line: "One instrumented navigation. Every request carries a reason.",
    props: ["GET /", "TLS", "DNS", "REDIRECT"],
  },
  {
    id: 3,
    status: "COLLECTING_EVIDENCE",
    code: "EVIDENCE COLLECTED",
    line: "Headers, cookies, storage, forms, scripts, console.",
    props: ["HDR", "CK", "WS", "DOM", "JS", "NET", "CON", "FRM", "LNK"],
  },
  {
    id: 4,
    status: "EVALUATING",
    code: "CONTROLS EVALUATED",
    line: "Zero traffic. The evidence is frozen; the agent reads it.",
    props: ["WEB-01", "WEB-02", "NET-03", "WEB-05", "APP-04", "PRIV-06"],
  },
  {
    id: 5,
    status: "MEASURING_PERFORMANCE",
    code: "NETWORK PROFILED",
    line: "fast, 4g, 3g, slow — in series, never in parallel.",
    props: ["FAST", "4G", "3G", "SLOW"],
  },
  {
    id: 6,
    status: "AGGREGATING",
    code: "COVERAGE COMPUTED",
    line: "Counts in Python. The model never counts.",
    props: ["YES", "NO", "UNKNOWN"],
  },
];

export function actForStatus(s: AssessmentStatus): Act {
  return ACTS.find((a) => a.status === s) ?? ACTS[0];
}

export const FAMILY_LABELS: Record<string, string> = {
  NET: "Network, DNS & TLS",
  WEB: "HTTP, browser & assets",
  IAM: "Identity & sessions",
  API: "Authorization & API",
  APP: "Input validation",
  PCI: "Payments",
  PRIV: "Privacy",
  ABUSE: "Abuse & anti-bot",
  PERF: "Availability & performance",
  LOG: "Logging & monitoring",
  IR: "Incident response",
  SDLC: "Secure SDLC & cloud",
  A11Y: "Accessibility",
  EU: "EU consumer",
  IN: "India DPDP",
  FLOW: "Critical journeys",
  GOV: "Scope & audit model",
};
