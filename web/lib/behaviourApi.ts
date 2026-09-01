import type {
  BehaviourProgress, BehaviourReport, Thought, UXFinding,
} from "./behaviourTypes";

const API = process.env.NEXT_PUBLIC_AGENTQA_API ?? "";

export const isLive = () => API.length > 0;

export interface BehaviourRun {
  /** Resolves when the session reaches a terminal state. */
  done: Promise<BehaviourReport>;
  cancel: () => void;
}

export interface BehaviourOptions {
  maxActions?: number;
  pacing?: number;
  noLlm?: boolean;
}

/**
 * POST /behaviour -> { session_id }, then GET /behaviour/{id}/stream for the
 * live feed and GET /behaviour/{id} for the report.
 *
 * With no API configured this falls back to a local simulation, exactly as
 * lib/api.ts does — useful for design work on the stage, and never to be
 * mistaken for a measurement. `isLive()` is the switch, and every surface
 * that renders a number says which mode produced it.
 */
export function startBehaviour(
  url: string,
  onProgress: (p: BehaviourProgress) => void,
  options: BehaviourOptions = {},
): BehaviourRun {
  return API ? live(url, onProgress, options) : simulate(url, onProgress);
}

function live(url: string, onProgress: (p: BehaviourProgress) => void,
              options: BehaviourOptions): BehaviourRun {
  let es: EventSource | null = null;
  let cancelled = false;
  let id: string | null = null;

  const done = (async () => {
    const res = await fetch(`${API}/behaviour`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        url,
        max_actions: options.maxActions,
        pacing: options.pacing,
        no_llm: options.noLlm ?? false,
      }),
    });
    if (!res.ok) {
      throw new Error(
        res.status === 422
          ? "That is not a URL the agent can reach."
          : `The agent could not be deployed (${res.status}).`);
    }
    const body = (await res.json()) as { session_id: string };
    id = body.session_id;

    await new Promise<void>((resolve, reject) => {
      es = new EventSource(`${API}/behaviour/${id}/stream`);
      es.onmessage = (ev) => {
        const p = JSON.parse(ev.data) as BehaviourProgress;
        onProgress(p);
        if (["COMPLETED", "BLOCKED", "FAILED"].includes(p.state)) {
          es?.close();
          resolve();
        }
      };
      es.onerror = () => {
        es?.close();
        cancelled ? resolve() : reject(new Error("the live feed was lost"));
      };
    });

    const rep = await fetch(`${API}/behaviour/${id}`);
    if (!rep.ok) throw new Error(`the report could not be read (${rep.status})`);
    return (await rep.json()) as BehaviourReport;
  })();

  return {
    done,
    cancel: () => {
      cancelled = true;
      es?.close();
      // Tell the backend too: an abandoned browser tab must not leave an
      // autonomous agent driving a browser against someone's site.
      if (id) void fetch(`${API}/behaviour/${id}`, { method: "DELETE" });
    },
  };
}

/* ---------------------------------------------------------------- simulation */

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

const SIM_THOUGHTS: Omit<Thought, "seq">[] = [
  { state: "DISCOVERING", observation: "62 interactive elements, 2 forms, scrollable.",
    action: "Measured the landing page: 1840 ms to the largest paint.",
    result: "48 focusable controls, 3 of them unnamed.", latency_ms: 1840, ok: true },
  { state: "UNDERSTANDING", observation: "Title, headings and 62 controls read.",
    action: "Classified as ecommerce.",
    result: "A visitor comes here to find a product and add it to the cart.",
    latency_ms: null, ok: true },
  { state: "PLANNING", observation: "5 affordances available.",
    action: "Planned 3 journeys: First impression, Shop for a product, Search.",
    result: "13 steps in total.", latency_ms: null, ok: true },
  { state: "INTERACTING", observation: "Scroll on the homepage — expecting content to keep up.",
    action: "Read what is above the fold.",
    result: "scrolled 768px at 58 fps", latency_ms: null, ok: true },
  { state: "INTERACTING", observation: "Click on 'Copper Kettle' — expecting the product page.",
    action: "Open a product.", result: "arrived at /product/copper-kettle in 211 ms",
    latency_ms: 211, ok: true },
  { state: "MEASURING", observation: "Click on 'Add to bag' — expecting the cart to acknowledge it.",
    action: "Add it to the cart.",
    result: "1 request was sent but the interface did not visibly change",
    latency_ms: 421, ok: false },
  { state: "ADAPTING", observation: "1 request was sent but the interface did not visibly change.",
    action: "Diagnosis: the response arrived before any feedback did.",
    result: "Recovery: alternate route.", latency_ms: null, ok: false },
  { state: "INTERACTING", observation: "Click on 'Search' — expecting focus.",
    action: "Click the search box.",
    result: "the field took focus in 34 ms — a caret is the whole of the expected response",
    latency_ms: 34, ok: true },
  { state: "MEASURING", observation: "Type on 'Search' — expecting suggestions while typing.",
    action: "Type a query.", result: "3 DOM updates, first visible in 480 ms",
    latency_ms: 480, ok: true },
];

function simulate(url: string, onProgress: (p: BehaviourProgress) => void
                  ): BehaviourRun {
  let cancelled = false;
  const done = (async () => {
    const map = simMap();
    let seq = 0;
    for (let i = 0; i < SIM_THOUGHTS.length; i++) {
      if (cancelled) break;
      const t = SIM_THOUGHTS[i];
      const pct = 6 + (i / SIM_THOUGHTS.length) * 88;
      onProgress({
        state: t.state, pct, objective: "Get to a product in the cart",
        current_action: t.action, page_url: url,
        pages_visited: Math.min(4, 1 + Math.floor(i / 2)),
        interactions: i, actions_dispatched: i,
        avg_response_ms: 214, requests: 2 + i,
        journeys_done: Math.floor(i / 4), journeys_total: 3,
        thought: { ...t, seq: ++seq },
        node: map[0].nodes[Math.min(i + 1, map[0].nodes.length - 1)].id,
        map_nodes: i === 2 ? map : null,
      });
      await sleep(1250);
    }
    onProgress({
      state: "COMPLETED", pct: 100, objective: "Mission complete",
      current_action: "", page_url: url, pages_visited: 4, interactions: 9,
      actions_dispatched: 9, avg_response_ms: 214, requests: 11,
      journeys_done: 3, journeys_total: 3, thought: null, node: null,
      map_nodes: null,
    });
    return sampleReport(url);
  })();
  return { done, cancel: () => { cancelled = true; } };
}

function simMap() {
  const labels = ["ENTRY", "READ THE PAGE", "OPEN A PRODUCT", "INSPECT IT",
                  "ADD TO CART", "OPEN THE CART", "SEARCH"];
  return [{
    nodes: labels.map((label, i) => ({
      id: i === 0 ? "start" : `j-1:${i - 1}`,
      label, journey_id: i === 0 ? null : "j-1", journey: "Shop for a product",
      index: i - 1,
    })),
    edges: labels.slice(1).map((_, i) => ({
      from: i === 0 ? "start" : `j-1:${i - 1}`, to: `j-1:${i}`,
    })),
  }];
}

/**
 * Shape-accurate sample data. The numbers are the ones the engine actually
 * produces against tests/fixtures/ux_site — a deliberately imperfect fixture
 * — so the interface is never designed against a result the backend could
 * not emit.
 */
function sampleReport(target: string): BehaviourReport {
  const findings: UXFinding[] = [
    {
      id: "UX-SILENT", title: "Actions fetch data without showing anything",
      category: "responsiveness", severity: "HIGH",
      observed: "2 interactions sent a request but the interface did not change while it was in flight",
      expected: "a spinner, a disabled state or a skeleton within 100 ms",
      impact: "The user has no way to tell their action registered, so they press again — often submitting twice.",
      recommendation: "Render a pending state synchronously on press, before the request is issued.",
      evidence_seq: [6, 11], page_url: `${target}/product`,
    },
    {
      id: "UX-SLOW-SEARCH", title: "Slow search response", category: "search",
      severity: "MEDIUM",
      observed: "median perceived response 480 ms across 3 measurements (worst 644 ms)",
      expected: "under 200 ms for search suggestions and results",
      impact: "Above 500 ms users stop associating the response with their own action; search starts to feel unresponsive rather than slow.",
      recommendation: "Show a state change within 100 ms of the press and move the work behind it off the critical path.",
      evidence_seq: [12, 13], page_url: target,
    },
    {
      id: "UX-DEAD", title: "Controls that do nothing when pressed",
      category: "reliability", severity: "HIGH",
      observed: "1 interaction produced no DOM change, no request and no navigation: 'Join the mailing list'",
      expected: "every visible control produces some response to a click",
      impact: "A user who presses a control and sees nothing assumes the site is broken. Most will press it again, then leave.",
      recommendation: "Confirm each control has a handler bound, and give every one an immediate visual state change on press.",
      evidence_seq: [7], page_url: target,
    },
    {
      id: "UX-A11Y-FOCUS", title: "Keyboard focus is not always visible",
      category: "accessibility", severity: "MEDIUM",
      observed: "a focus indicator was detectable on 33% of keyboard stops sampled",
      expected: "every focusable control shows where focus is",
      impact: "Keyboard and switch users lose their place entirely. This is the most common reason a site is unusable without a mouse.",
      recommendation: "Never remove the default outline without replacing it; :focus-visible gives you the mouse-free behaviour people strip outlines to get.",
      evidence_seq: [], page_url: target,
    },
  ];

  return {
    session_id: "b7c11f2a4e8d0396", target, state: "COMPLETED",
    started_at: new Date().toISOString(), duration_seconds: 42.6,
    understanding: {
      kind: "ecommerce", confidence: 0.62,
      primary_goal: "find a product and add it to the cart",
      secondary_goals: ["compare products", "find the delivery terms"],
      audience: "first-time shoppers",
      key_affordances: ["search", "cart", "navigation", "pagination", "forms"],
      rationale: "derived from the page's own words and the controls that exist on it",
      derived_by: "heuristic",
    },
    score: {
      overall: 79, band: "GOOD",
      method: "weighted mean of 6 of 7 components that had observations; components with no data are excluded rather than scored zero",
      observations: 41,
      components: [
        { name: "Interaction Speed", score: 76, n: 6, basis: "median perceived response 244 ms across 6 interactions (good ≤200 ms)" },
        { name: "Navigation", score: 91, n: 5, basis: "median LCP 1840 ms over 4 pages; median route transition 211 ms over 1" },
        { name: "Responsiveness", score: 48, n: 4, basis: "visual acknowledgement in 128 ms (median); 2 of 4 actions fetched data with no visible feedback" },
        { name: "Visual Experience", score: 88, n: 14, basis: "worst page CLS 0.140 (good ≤0.1); 1 of 12 interactions shifted the layout" },
        { name: "Accessibility", score: 71, n: 4, basis: "3 unnamed controls, 1 image without alt, heading order intact on 4/4 pages, focus visible on 33% of keyboard stops — structural checks, not a WCAG conformance claim" },
        { name: "Interaction Reliability", score: 82, n: 17, basis: "14 of 17 actions produced the expected result; 1 produced no response at all" },
        { name: "Scroll Experience", score: 94, n: 6, basis: "median 58 fps over 6 scrolls, 3 dropped frames of 412" },
      ],
    },
    journeys: [], journey_outcomes: [
      { journey_id: "j-1", name: "First impression", goal: "find out what this site offers", completed: true, steps_planned: 4, steps_attempted: 4, steps_succeeded: 4, abandoned_at: null, abandon_reason: null, total_ms: 8400 },
      { journey_id: "j-2", name: "Shop for a product", goal: "get from the homepage to a product in the cart", completed: false, steps_planned: 5, steps_attempted: 4, steps_succeeded: 3, abandoned_at: "Add it to the cart", abandon_reason: "1 request was sent but the interface did not visibly change", total_ms: 11200 },
      { journey_id: "j-3", name: "Search for something", goal: "use search and get to a result", completed: true, steps_planned: 4, steps_attempted: 4, steps_succeeded: 3, abandoned_at: null, abandon_reason: null, total_ms: 6900 },
    ],
    timeline: [
      { seq: 2, journey_id: "j-1", label: "Read what is above the fold", action: "read", category: "dwell", ms: null, outcome: "SUCCESS", ok: true, slow: false, url: target },
      { seq: 5, journey_id: "j-2", label: "Open a product", action: "click", category: "button", ms: 211, outcome: "SUCCESS", ok: true, slow: false, url: `${target}/product` },
      { seq: 6, journey_id: "j-2", label: "Add it to the cart", action: "click", category: "button", ms: 421, outcome: "UNEXPECTED", ok: false, slow: true, url: `${target}/product` },
      { seq: 9, journey_id: "j-3", label: "Click the search box", action: "click", category: "search", ms: 34, outcome: "SUCCESS", ok: true, slow: false, url: target },
      { seq: 12, journey_id: "j-3", label: "Type a query", action: "type", category: "search", ms: 480, outcome: "SUCCESS", ok: true, slow: true, url: target },
      { seq: 13, journey_id: "j-3", label: "Submit the search", action: "submit_search", category: "search", ms: 644, outcome: "SUCCESS", ok: true, slow: true, url: target },
    ],
    interactions: [
      { seq: 5, interaction: "Copper Kettle", category: "button", expectation: "the product page loads", observed: "arrived at /product in 211 ms", ms: 211, assessment: "Within expectation", severity: "INFO" },
      { seq: 6, interaction: "Add to bag", category: "button", expectation: "the cart acknowledges the item", observed: "1 request was sent but the interface did not visibly change", ms: 421, assessment: "Needs improvement", severity: "MEDIUM" },
      { seq: 12, interaction: "Search", category: "search", expectation: "suggestions appear while typing", observed: "3 DOM updates, first visible in 480 ms", ms: 480, assessment: "Well outside expectation", severity: "HIGH" },
    ],
    categories: [
      { category: "button", n: 6, median_ms: 244, p95_ms: 421, worst_ms: 421, best_ms: 40 },
      { category: "navigation", n: 4, median_ms: 211, p95_ms: null, worst_ms: 268, best_ms: 180 },
      { category: "search", n: 3, median_ms: 480, p95_ms: null, worst_ms: 644, best_ms: 34 },
      { category: "scroll", n: 6, median_ms: 0, p95_ms: null, worst_ms: 0, best_ms: 0 },
    ],
    actions: [], thoughts: SIM_THOUGHTS.map((t, i) => ({ ...t, seq: i + 1 })),
    pages: [
      { url: target, title: "Fixture Store", visits: 3, interactions: 9, errors: 0,
        vitals: { ttfb_ms: 118, fcp_ms: 940, lcp_ms: 1840, cls: 0.14, load_ms: 2210, dom_content_loaded_ms: 1100, transferred_bytes: 412_000, request_count: 22, inp_ms: null } },
      { url: `${target}/product`, title: "Copper Kettle", visits: 1, interactions: 4, errors: 0,
        vitals: { ttfb_ms: 96, fcp_ms: 780, lcp_ms: 1520, cls: 0.02, load_ms: 1810, dom_content_loaded_ms: 900, transferred_bytes: 388_000, request_count: 19, inp_ms: null } },
    ],
    findings,
    insights: {
      "How does it feel?": "Quick, but uneven — the fast paths are fast and the rest are noticeably not.",
      "Where does a user struggle?": "actions fetch data without showing anything; controls that do nothing when pressed.",
      "Which interactions are slow?": "search (480 ms median), button (244 ms median), navigation (211 ms median).",
      "Which components feel unresponsive?": "1 control did nothing at all; 2 fetched data with no visible feedback.",
      "Where does a journey break down?": "Shop for a product — stopped at Add it to the cart.",
      "Are the primary actions discoverable?": "The agent found its first actionable control after 1 scroll.",
      "Does navigation feel intuitive?": "4 pages were reached; route transitions ran at a 211 ms median.",
      "Does scrolling feel natural?": "median 58 fps over 6 scrolls, 3 dropped frames of 412.",
      "Does the site give immediate feedback?": "2 of 6 interactions responded within 100 ms — the threshold at which a response still feels like part of the click.",
    },
    summary:
      "The agent read this as an ecommerce site whose visitor wants to find a product and add it to the cart, and ran 3 journeys across 4 pages with 17 interactions. Browsing is quick — pages arrive in around 200 ms and scrolling holds close to 60 fps — but the cart does not acknowledge an item for 421 ms and shows nothing at all while it works, which is where the shopping journey stopped. Search behaves the same way: the request is not slow, the silence is.",
    mission: {
      pages_explored: 4, interactions: 17, journeys: 3, issues_detected: 4,
      critical_issues: 0, avg_response_ms: 214, requests_made: 11,
      score: 79, band: "GOOD",
    },
    refusals: [
      { seq: 0, element: "Buy now", reason: "click on 'Buy now' refused — completes a purchase" },
      { seq: 0, element: "Place order", reason: "click on 'Place order' refused — completes a purchase" },
    ],
    requests_made: 11, blocked_reason: null, errors: [],
    llm_model: null, browser_version: "chromium 131.0.6778.33",
  };
}
