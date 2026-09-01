/**
 * Mirrors app/behaviour/serializers.py exactly.
 *
 * Every latency is `number | null`, and null means "not observed" — never
 * zero. The backend refuses to fabricate a measurement, so the interface has
 * to be able to render the absence of one. Anywhere you are tempted to write
 * `ms ?? 0`, write "not measured" instead.
 */

/** app/behaviour/models.py :: AgentState — §26 of the brief. */
export type AgentState =
  | "DISCOVERING" | "UNDERSTANDING" | "PLANNING" | "NAVIGATING"
  | "INTERACTING" | "OBSERVING" | "MEASURING" | "ADAPTING"
  | "REPORTING" | "COMPLETED" | "BLOCKED" | "FAILED";

export const AGENT_TERMINAL: AgentState[] = ["COMPLETED", "BLOCKED", "FAILED"];

export type Outcome =
  | "SUCCESS" | "NO_RESPONSE" | "UNEXPECTED" | "ERROR" | "REFUSED"
  | "INCONCLUSIVE";

export type UXSeverity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO";

export type ScoreBand = "EXCELLENT" | "GOOD" | "FAIR" | "POOR" | "UNRATED";

export interface SiteUnderstanding {
  kind: string;
  confidence: number;
  primary_goal: string;
  secondary_goals: string[];
  audience: string;
  key_affordances: string[];
  rationale: string;
  /** "llm" or "heuristic" — the report says which produced the plan. */
  derived_by: string;
}

export interface ScoreComponent {
  name: string;
  /** null when nothing was observed for this dimension. Not zero. */
  score: number | null;
  n: number;
  basis: string;
}

export interface UXScore {
  overall: number | null;
  band: ScoreBand;
  method: string;
  observations: number;
  components: ScoreComponent[];
}

export interface JourneyStep {
  label: string;
  action: string;
  expectation: string;
  optional: boolean;
}

export interface Journey {
  id: string;
  name: string;
  goal: string;
  derived_by: string;
  steps: JourneyStep[];
}

export interface JourneyOutcome {
  journey_id: string;
  name: string;
  goal: string;
  completed: boolean;
  steps_planned: number;
  steps_attempted: number;
  steps_succeeded: number;
  abandoned_at: string | null;
  abandon_reason: string | null;
  total_ms: number | null;
}

export interface InteractionTiming {
  input_latency_ms: number | null;
  ui_response_ms: number | null;
  network_first_byte_ms: number | null;
  network_complete_ms: number | null;
  state_complete_ms: number | null;
  perceived_ms: number | null;
  mutation_count: number;
  request_count: number;
  layout_shift: number | null;
  long_task_ms: number | null;
  scroll_fps: number | null;
  dropped_frames: number | null;
}

export interface AgentAction {
  seq: number;
  kind: string;
  category: string;
  element: string;
  element_kind: string | null;
  reason: string;
  expectation: string;
  observed: string;
  outcome: Outcome;
  url: string;
  new_url: string | null;
  note: string;
  console_errors: string[];
  timing: InteractionTiming;
}

/** §16 — three statements of fact. Never chain-of-thought. */
export interface Thought {
  seq: number;
  state: AgentState;
  observation: string;
  action: string;
  result: string;
  latency_ms: number | null;
  ok: boolean | null;
}

export interface PageVitals {
  ttfb_ms: number | null;
  fcp_ms: number | null;
  lcp_ms: number | null;
  cls: number | null;
  load_ms: number | null;
  dom_content_loaded_ms: number | null;
  transferred_bytes: number | null;
  request_count: number;
  /** Always null. INP needs real users; a lab agent cannot produce one. */
  inp_ms: null;
}

export interface PageVisit {
  url: string;
  title: string;
  visits: number;
  interactions: number;
  errors: number;
  vitals: PageVitals;
}

export interface UXFinding {
  id: string;
  title: string;
  category: string;
  severity: UXSeverity;
  observed: string;
  expected: string;
  impact: string;
  recommendation: string;
  evidence_seq: number[];
  page_url: string;
}

export interface TimelineRow {
  seq: number;
  journey_id: string | null;
  label: string;
  action: string;
  category: string;
  ms: number | null;
  outcome: Outcome;
  ok: boolean;
  slow: boolean;
  url: string;
}

export interface InteractionRow {
  seq: number;
  interaction: string;
  category: string;
  expectation: string;
  observed: string;
  ms: number | null;
  assessment: string;
  severity: string;
}

export interface CategoryRow {
  category: string;
  n: number;
  median_ms: number;
  p95_ms: number | null;
  worst_ms: number;
  best_ms: number;
}

export interface MissionStats {
  pages_explored: number;
  interactions: number;
  journeys: number;
  issues_detected: number;
  critical_issues: number;
  avg_response_ms: number | null;
  requests_made: number;
  score: number | null;
  band: ScoreBand;
}

export interface MapNode {
  id: string;
  label: string;
  journey_id: string | null;
  journey?: string;
  index: number;
  action?: string;
}

export interface MapEdge { from: string; to: string }

export interface BehaviourReport {
  session_id: string;
  target: string;
  state: AgentState;
  started_at: string;
  duration_seconds: number;
  understanding: SiteUnderstanding;
  score: UXScore;
  journeys: Journey[];
  journey_outcomes: JourneyOutcome[];
  timeline: TimelineRow[];
  interactions: InteractionRow[];
  categories: CategoryRow[];
  actions: AgentAction[];
  thoughts: Thought[];
  pages: PageVisit[];
  findings: UXFinding[];
  insights: Record<string, string>;
  summary: string;
  mission: MissionStats;
  refusals: { seq: number; element: string; reason: string }[];
  requests_made: number;
  blocked_reason: string | null;
  errors: string[];
  llm_model: string | null;
  browser_version: string;
}

/** One SSE frame from GET /behaviour/{id}/stream. */
export interface BehaviourProgress {
  state: AgentState;
  pct: number;
  objective: string;
  current_action: string;
  page_url: string;
  pages_visited: number;
  interactions: number;
  actions_dispatched: number;
  avg_response_ms: number | null;
  requests: number;
  journeys_done: number;
  journeys_total: number;
  thought: Thought | null;
  node: string | null;
  map_nodes: { nodes: MapNode[]; edges: MapEdge[] }[] | null;
}

/** The state machine, in the order the agent walks it. */
export const AGENT_STATES: AgentState[] = [
  "DISCOVERING", "UNDERSTANDING", "PLANNING", "NAVIGATING",
  "INTERACTING", "OBSERVING", "MEASURING", "ADAPTING", "REPORTING",
];

export const STATE_LINE: Record<AgentState, string> = {
  DISCOVERING: "Opening the site and measuring the first load.",
  UNDERSTANDING: "Working out what this site is and who comes here.",
  PLANNING: "Writing the journeys a real visitor would take.",
  NAVIGATING: "Moving to where the next step happens.",
  INTERACTING: "Doing what a visitor would do next.",
  OBSERVING: "Reading what is on screen now.",
  MEASURING: "Timing how the site responded.",
  ADAPTING: "That did not work. Deciding what a person would do about it.",
  REPORTING: "Scoring what was measured.",
  COMPLETED: "Mission complete.",
  BLOCKED: "The target blocked the session. Nothing was retried.",
  FAILED: "The session could not be completed.",
};

export const BAND_COLOR: Record<ScoreBand, string> = {
  EXCELLENT: "var(--color-phos)",
  GOOD: "var(--color-phos)",
  FAIR: "var(--color-bone)",
  POOR: "var(--color-anomaly)",
  UNRATED: "var(--color-dim)",
};
