/**
 * Mirrors app/models/*.py. The vocabulary is the backend's, not the UI's —
 * the frontend never invents a verdict the engine would not emit.
 */

export type NativeResult =
  | "PASS" | "FAIL" | "N/A" | "WARN" | "NOT_TESTABLE" | "INFORMATIONAL";

export type ContractResult = "YES" | "NO" | "NOT_APPLICABLE" | "UNKNOWN";

export type Severity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO";

/** app/models/assessment.py :: AssessmentStatus */
export type AssessmentStatus =
  | "INITIALIZING" | "PLANNING" | "DISCOVERING" | "COLLECTING_EVIDENCE"
  | "EVALUATING" | "MEASURING_PERFORMANCE" | "AGGREGATING"
  | "COMPLETED" | "PARTIAL" | "BLOCKED" | "FAILED";

export const TERMINAL: AssessmentStatus[] =
  ["COMPLETED", "PARTIAL", "BLOCKED", "FAILED"];

/** One row of app/tools/rules.py output, after evaluation. */
export interface Finding {
  control_id: string;
  family: string;
  title: string;
  severity: Severity;
  native_result: NativeResult;
  result: ContractResult;
  observed_value: string | null;
  unknown_reason: string | null;
  evidence: string;
  source_file: string;
  source_line: number;
}

/** app/models/results.py :: ResultTally */
export interface Tally {
  total: number;
  yes: number;
  no: number;
  not_applicable: number;
  unknown: number;
  native_pass: number;
  native_fail: number;
  native_warn: number;
  native_na: number;
  native_informational: number;
  native_not_testable: number;
}

export interface FamilyCoverage {
  family: string;
  label: string;
  decided: number;
  total: number;
  failed: number;
}

/** app/models/assessment.py :: PlannedAction — the agent's actual route. */
export interface AgentStep {
  kind: string;
  target: string;
  reason: string;
  required_by: string[];
}

export interface ProfileStat {
  profile: string;
  ttfb_p50: number | null;
  lcp_p50: number | null;
  load_p95: number | null;
  n: number;
  status: "OK" | "PARTIAL" | "UNAVAILABLE";
}

export interface Progress {
  status: AssessmentStatus;
  pct: number;
  label: string;
  detail?: string;
  requests?: number;
}

export interface Report {
  assessment_id: string;
  target: string;
  status: AssessmentStatus;
  coverage_pct: number;
  tally: Tally;
  families: FamilyCoverage[];
  findings: Finding[];
  route: AgentStep[];
  performance: ProfileStat[];
  collectors_run: string[];
  duration_seconds: number;
  llm_model: string | null;
  blocked_reason: string | null;
}
