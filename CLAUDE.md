# CLAUDE.md — Website Security & Performance Assessment System

End-to-end developer documentation: what this project is for, how it is built,
what every module does, and — importantly — what it deliberately refuses to do.

---

## 1. Intention

Point the system at a website URL. It drives a real browser, collects only the
evidence the rule pack demands, evaluates each control against that evidence,
measures performance under several network profiles, and writes a structured
report.

The `Rules/` directory is the **source of truth**. It is not a set of examples;
it is the specification. No security rule is hardcoded anywhere in `app/`.

### The finding that shapes the entire design

`Rules/` holds **144 controls across 17 families** — an enterprise e-commerce
audit baseline covering legal, organizational and operational controls, not a
list of website checks. Counting the pack's own `Auto?` column:

| Tier   | Count | Meaning                                                |
|--------|-------|--------------------------------------------------------|
| `P`    |  25   | passive automation is possible                          |
| `P/M`  |  14   | hybrid — a browser sees part of the picture             |
| `M/P`  |   3   | same, written the other way round                       |
| `M`    |  96   | needs staging, authorized active testing, or interviews |
| `No`   |   6   | not provable from a public website at all               |

Only **25 of 144** are fully automatable. **102 are unreachable** from any
browser. Meanwhile 50 controls are Critical and 73 High, and most of that
severity sits in `PCI`, `IAM`, `API` and `FLOW` — exactly the families a scan
cannot touch.

A system that emitted 144 pass/fail verdicts from one page load would be
fabricating 102 of them. The pack says so itself, twice:

> `PCI-10`: *"Never treat a web header/SSL scan as proof of PCI compliance."*
>
> `19_test_modes_safety.md`: *"A security tool should say **what was
> observed**, not infer legal compliance from a single signal."*

So the system loads all 144, evaluates what the evidence supports, and returns
`UNKNOWN` **with a stated reason** for the rest. Coverage is reported as a
headline number. There is no single site-wide "score".

### Non-goals

Not a vulnerability scanner. Not an exploitation tool. It does not brute force,
bypass authentication, evade bot detection, rotate IPs, solve CAPTCHAs, submit
forms, or crawl. See §11.

---

## 2. Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium

# See the plan and the exact request budget WITHOUT touching the target:
python -m app.main --url https://example.com --dry-run

# Full assessment:
python -m app.main --url https://example.com

# Narrower:
python -m app.main --url https://example.com \
    --families NET,WEB --network-profiles fast,3g --iterations 2
```

### The other agent

The same repository also ships a **User Behaviour Agent** — an autonomous AI
user that browses the site and measures what it experiences. It answers a
different question from the rule pack and is documented in full in §15.

```bash
python -m app.behaviour --url https://example.com --dry-run
python -m app.behaviour --url https://example.com
```

### The web interface

The same pipeline, driven from a browser instead of a terminal. Two processes:

```bash
python -m app.api.server        # API on 127.0.0.1:8000  <- the entry point
cd web && npm run dev           # interface on :3000
```

`web/.env.local` holds `NEXT_PUBLIC_AGENTQA_API=http://127.0.0.1:8000`. With
that variable **unset** the interface falls back to a local simulation with
hardcoded findings — useful for design work, and never to be mistaken for a
result. `web/lib/api.ts :: isLive()` is the switch, and
`web/lib/behaviourApi.ts` has the same one for the behaviour surface.

The interface offers both agents from one portal: **Behaviour** deploys the
autonomous user (§15), **Security** runs the rule-pack assessment.

Optional local model (improves coverage; the system runs without it):

```bash
ollama pull qwen3-coder        # or any qwen2.5-coder / qwen2.5 build
```

### CLI flags

| Flag | Effect |
|---|---|
| `--url` | target (required) |
| `--config`, `--policy` | YAML paths (default `config.yaml`, `policy.yaml`) |
| `--network-profiles` | e.g. `fast,4g,3g,slow` |
| `--iterations` | performance iterations per profile |
| `--families` | evaluate a subset, e.g. `NET,WEB` |
| `--skip-performance` | security only |
| `--no-llm` | deterministic only; unreachable controls become `UNKNOWN` |
| `--headed` | show the browser |
| `--dry-run` | print the plan, open no browser |
| `--output` | report directory override |

Exit codes: `0` completed/partial · `1` failed · `2` bad URL · `3` LLM required
but absent · `4` blocked by the target · `130` interrupted.

---

## 3. Architecture

One rule governs the layout: **reasoning and execution never touch the browser
at the same level.** The LLM plans and interprets. Deterministic Python drives
Playwright, computes statistics and writes files. *The model never receives a
page handle.*

```
                      TARGET URL
                          │
                   ┌──────▼──────┐
                   │ LOAD_RULES  │  pure Python, parses Rules/*.md
                   └──────┬──────┘
                   ┌──────▼──────┐
                   │    PLAN     │  LLM interprets rules (cached forever)
                   └──────┬──────┘  then unions collector sets
                   ┌──────▼──────────┐
                   │ COLLECT_EVIDENCE│  ONE instrumented navigation
                   └──────┬──────────┘  + 4 auxiliary requests
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
       ┌─────────────┐        ┌───────────────┐
       │  EVALUATE   │        │  PERFORMANCE  │
       │  PARALLEL   │        │  SEQUENTIAL   │
       │ 144 rules   │        │ fast→4g→3g→   │
       │ zero traffic│        │ slow, 3 iters │
       └──────┬──────┘        └───────┬───────┘
              │                ┌──────▼──────┐
              │                │ STATISTICS  │ pure Python
              │                └──────┬──────┘
              └───────────┬───────────┘
                   ┌──────▼──────┐
                   │  AGGREGATE  │  counts in Python, prose from LLM
                   └──────┬──────┘
                   ┌──────▼──────┐
                   │   PERSIST   │  repository seam → Excel or Postgres
                   └──────┬──────┘
                         END
```

### Why the fork is safe, and why one branch is not parallel

* **EVALUATE** reads a frozen in-memory bundle and issues **no network traffic
  at all**. Safe to run beside anything. 144 evaluations fan out under a
  semaphore.
* **PERFORMANCE** owns the network. Inside it, profiles run **strictly in
  series**. This is the one place where the obvious parallelism is actively
  wrong: all four profiles share one physical uplink, so running them
  concurrently measures *contention* rather than the profile — and quadruples
  simultaneous load on the target.

### Where the LLM is and is not

| Used for | Not used for |
|---|---|
| interpreting a Markdown control into a collector set (cached) | arithmetic, percentiles, any statistic |
| judging evidence against a control's pass criteria | browser navigation or DOM extraction |
| writing the executive summary prose | counting results |
| — | deciding what to click |

**LLM calls per run (warm cache):** ~42 evaluations + 1 summary. The ~102
controls the pack marks `M`/`No` are resolved to `NOT_TESTABLE` with **zero**
model calls, driven by the `Auto?` column rather than control identity.

---

## 4. Repository layout

```
Rules/                      UNTOUCHED — the source of truth
app/
  models/     rules.py assessment.py evidence.py performance.py results.py
  config/     settings.py
  tools/      rules.py browser.py inspection.py network.py a11y.py
              performance.py statistics.py screenshots.py
              evidence_projection.py evaluation.py report.py
  llm/        base.py qwen.py cache.py prompts.py
  agents/     planner.py browser_agent.py performance_agent.py aggregator.py
  graph/      state.py nodes.py workflow.py
  behaviour/  the User Behaviour Agent — see §15. Shares the browser, the
              LLM provider, the traffic budget and app/safety/ with the
              assessment above, and nothing else. Never reads Rules/.
  api/        server.py runner.py serializers.py progress.py behaviour.py
  repositories/ base.py excel.py postgres.py
  safety/     redaction.py antibot.py limits.py
  main.py     CLI
web/                        Next.js interface (see §2)
tests/
  unit/         no network, no browser
  integration/  real Chromium against a LOCAL fixture site only
  fixtures/     server.py + site/       (deliberately broken headers)
                ux_server.py + ux_site/ (deliberately broken UX — §15)
artifacts/<assessment_id>/  screenshots/ traces/ logs/ *.xlsx
config.yaml  policy.yaml  requirements.txt  .env.example
```

---

## 5. Module reference

### 5.1 `app/models/` — the domain

**`rules.py`**

* `Automation` — the `Auto?` column: `P`, `M`, `P/M`, `M/P`, `No`.
  `has_passive_component` is the predicate that decides whether a control gets
  an LLM call at all.
* `Severity` — with `.rank` for ordering.
* `TestLayer` — `L1`–`L5` from `00_README.md`. `from_automation()` derives it,
  because the family tables never populate `test_layer` even though
  `18_rule_object_schema.md` defines it. We derive rather than invent.
* `CollectorCode` — the 22 evidence collectors. Bounded by what
  `19_test_modes_safety.md` authorises for passive mode.
* `RuleInterpretation` — the *only* thing the LLM decides about a rule.
* `SecurityRule` — fields split into parsed-from-source, derived, and
  interpreted. `content_hash` keys the interpretation cache: it tracks the
  rule's **text**, so editing wording invalidates the cache but moving the file
  does not. Fields the pack defines but never populates (`framework_mapping`,
  `remediation`, `owner`) stay empty rather than being guessed.
* `RuleFamily` — one `Rules/NN_*.md` file.

**`results.py`** — the two-vocabulary design (see §7).
`NativeResult` (6 values) · `ContractResult` (4 values) · `project()` (total
pure function) · `SecurityResult` (carries both) ·
`SecurityResult.not_testable()` (the honest default) · `ResultTally` with
`.decided` and `.coverage_pct`.

**`evidence.py`** — `EvidenceBundle` plus its record types. Written **once** by
`COLLECT_EVIDENCE`, read-only thereafter. `html_source` is `exclude=True`, so
it never reaches Excel, a log or a prompt.

**`performance.py`** — `NetworkProfile` (Mbps→bps conversion at the config
boundary, so no unit maths hides in business logic) · `PerformanceMeasurement`
(`METRICS` is a `ClassVar`, not a field) · `PerformanceStatistics` ·
`ProfileOutcome`.

**`assessment.py`** — `AssessmentStatus` (11 states) · `PlannedAction` (every
action carries a mandatory `reason`) · `AssessmentPlan` · `AntiBotSignal` ·
`ComponentError` (scoped, non-fatal) · `Assessment` · `AssessmentReport`.

### 5.2 `app/config/settings.py`

Nested Pydantic models mirroring `config.yaml`, plus `Policy` from
`policy.yaml`. Precedence: **CLI > env > YAML > defaults**. `load_settings()`
deep-merges and converts `network_profiles` dicts into `NetworkProfile`
objects. `BrowserConfig.supports_throttling` is the Chromium-only gate.
No module outside this one reads a raw YAML key.

### 5.3 `app/tools/rules.py` — RuleLoaderTool

Contains **no knowledge of any individual control**. It parses GFM tables.

* `resolve_rules_dir()` — scans for the real on-disk name *first*, so
  `Rules/` vs `rules/` behaves identically on macOS and Linux. (macOS resolves
  the literal path either way, which would otherwise make `source_file` differ
  between platforms for the same repo.)
* `parse_markdown_rule()` — returns `None` for meta files, detected by the
  **absence of a `> Control family:` marker**, not by a filename allowlist. So
  a renamed meta file still behaves correctly.
* Column mapping is **positional** (`_COLUMNS`); all 17 files are consistent,
  and a header-name lookup would silently mis-map an abbreviated heading.
* A malformed row is logged and skipped; an unknown `Auto?` degrades to `M`.
  One bad row never loses the file.
* `load_rules()` → `(families, flat_rules)`. `validate_rule()` returns problems.

**Extensibility:** drop in `Rules/21_new_family.md` with the same table shape
and its controls appear with **zero code change**. Covered by
`test_a_new_family_file_is_picked_up_with_zero_code_changes`.

### 5.4 `app/tools/` — evidence collectors

**`browser.py` — `BrowserSession`.** The only module that drives a browser.

* One discovery context, **never cleared mid-run** — clearing it would destroy
  the session state `WEB-05` and `IAM-08` need to observe.
* One fresh context per performance profile — a warm cache would make the 3G
  numbers fiction.
* `navigate()` takes a **mandatory `reason`**, logged and counted. There is no
  unattributed traffic.
* `scroll_to_fold()` — one paced scroll and back, to settle lazy content for
  LCP and mixed-content checks. Not a crawl, and not an imitation of a human.
* `close()` is idempotent and never raises; called from a `finally` on every
  path.

**`inspection.py`** — `NetworkRecorder` (attached **before** navigation, or the
main document is missed) records requests, responses, failures, console and
CORS, redacting headers at capture. Collectors: `inspect_cookies`,
`inspect_storage`, `inspect_forms`, `inspect_scripts`, `inspect_links`,
`collect_navigation_timing`, `collect_web_vitals`, `scan_page_secrets`.
`registrable_host` / `is_same_site` classify first vs third party.

**`network.py`** — out-of-band, no browser: `collect_tls` (stdlib `ssl`;
`check_hostname=False` deliberately, so we **report** a mismatch rather than
fail on it), `collect_dns` (dnspython; costs the target nothing),
`collect_redirect_chain`, `collect_well_known`, `probe_error_page` (one benign
GET on a random path — non-destructive by construction).

**`a11y.py`** — structural heuristics always; axe-core only from a **locally
vendored** copy at `vendor/axe.min.js`. We never inject a CDN script into
someone else's page. Results are `INFORMATIONAL`: automated tooling covers a
minority of WCAG 2.2 criteria and cannot establish AA conformance.

**`performance.py`** — `apply_network_profile` via CDP
`Network.emulateNetworkConditions`; raises `ThrottleUnavailable` on non-Chromium
so a profile is marked `UNAVAILABLE` rather than reported as unthrottled
numbers. `measure_page_load` returns a measurement where every metric is
observed or `None` — never zero-filled.

**`statistics.py` — StatisticsTool.** Pure. The LLM never computes a statistic.

* `calculate_percentile` — linear interpolation between closest ranks.
* `stddev` is the **sample** deviation (n−1) and is `None` for n=1 — zero would
  imply perfect consistency.
* An empty sample returns all-`None`, never zeros: a zero would read as "0 ms",
  a measurement we never took.
* Failed iterations are excluded from central tendency but counted in
  `failure_rate`, so a profile failing 2 of 3 loads reads as unstable, not fast.
* `n` is always reported beside `p95`, so a 3-sample "95th percentile" is not
  mistaken for a population percentile.

**`evidence_projection.py`** — the quiet load-bearing piece. Slices the bundle
to just what one rule needs, driven **entirely by `CollectorCode`**, never by
control identity. A CSP question gets the CSP header and console violations,
not a megabyte of DOM. Output is hard-capped at `MAX_PROJECTION_CHARS`, so no
prompt can blow the context. `evidence_corpus()` produces the flat text the
anti-fabrication check searches.

**`evaluation.py`** — see §8.

**`report.py`** — console rendering. Leads with **coverage**, not a score.

### 5.5 `app/llm/`

* **`base.py`** — `LLMProvider` Protocol; `extract_json` (whole string → fenced
  block → first balanced `{...}`, because small models wrap JSON in prose even
  when told not to); `parse_into` returns `None` rather than raising.
* **`qwen.py`** — `Qwen3CoderProvider` over Ollama `/api/chat` with
  `format: json`. `health_check()` resolves the model and **falls back** through
  `fallback_models` if the configured one is absent, recording the substitution
  — `GOV-05` and `IN-07` both require the report to state which tools produced
  it. `build_provider()` is the factory; add providers there.
* **`cache.py`** — `InterpretationCache`, keyed on `content_hash`. Corrupt
  entries are discarded, not fatal.
* **`prompts.py`** — three system prompts, written against the pack's own words.

### 5.6 `app/agents/`

* **`planner.py`** — `interpret()` (skips non-passive controls entirely → cache
  → model → safe empty default), `interpret_all()` (bounded concurrency),
  `build_plan()` (pure Python: unions collector sets, honours config switches,
  emits the action list and the request estimate).
* **`browser_agent.py`** — `EvidenceCollector`. Runs out-of-band collectors
  **concurrently** with the navigation, gates on anti-bot before collecting
  anything else, runs each in-page collector under its own guard so one failure
  never aborts the rest, and scrubs secret literals from retained HTML after the
  `WEB-09` scan.
* **`performance_agent.py`** — profiles in series, fresh context each, per-profile
  budget; exceeding it retains completed iterations and marks the profile
  `PARTIAL`.
* **`aggregator.py`** — `validate_results()` (final invariants, §8),
  `family_coverage()`, `deterministic_summary()` (always computed, used as
  fallback), `write_summary()` (one LLM call, cannot alter a verdict).

### 5.7 `app/graph/`

`state.py` defines `AssessmentState`; `errors` uses an `Annotated` reducer
because both fork branches append to it. `nodes.py` has one function per phase,
each defensive — a failure records a `ComponentError` and returns usable state.
`workflow.py` compiles the graph and documents the fork.

### 5.8 `app/api/` — the HTTP surface

A shell around the same compiled graph, so the API cannot drift into
evaluating rules differently from the CLI. It holds no rule knowledge.

    POST   /analyze             -> {"assessment_id": ...}
    GET    /analyze/{id}/stream -> text/event-stream of Progress
    GET    /analyze/{id}        -> Report (409 while still running)
    DELETE /analyze/{id}        -> cancel
    GET    /health · GET /analyze

* **`runner.py`** — builds the identical state dict as `main.py` and invokes
  the identical workflow. `RunManager` bounds concurrency (2) and retains the
  last 50 finished runs. Every safety property carries over because each is
  structural: the `TrafficBudget` still attributes and caps every request, and
  the browser still closes in a `finally` on every path.
* **`progress.py`** — maps graph nodes onto the stages `web/lib/stages.ts`
  already names. The `requests` counter is read live from the budget, so the
  number on screen is the number the target actually received. `pct` is the
  one interpolated value, and it never touches a verdict.
* **`serializers.py`** — projects terminal state onto `web/lib/types.ts`.
  A missing metric serialises as `null`, never `0`, exactly as §9 requires.
* **Streaming through the fork.** `EVALUATE` and `PERFORMANCE` are a single
  superstep, so state snapshots cannot expose their individual completions.
  `AssessmentState.progress` is an optional hook those two nodes call; the CLI
  leaves it unset and behaves exactly as before.

**Binding.** Defaults to `127.0.0.1`. Exposing this on a public interface would
let anyone point it at anyone, which is the authorization boundary in §11
undone by deployment rather than by code. `AGENTQA_HOST` overrides it; §11
still applies to whoever does.

### 5.9 `app/repositories/`

`base.py` defines the Protocol and `build_repository()` factory. **No agent,
node or tool imports openpyxl or asyncpg.** `excel.py` buffers rows and writes
one workbook atomically (temp file + `os.replace`). `postgres.py` is
schema-complete with the same Protocol; `commit()` raises `NotImplementedError`
with instructions. Migration replaces one class and one config line.

### 5.10 `app/safety/`

* **`redaction.py`** — applied at **capture**, not at report time.
  `redact_headers`, `redact_set_cookie` (keeps attributes, drops the value —
  `WEB-05` needs flags), `redact_url`, `scan_for_secrets` (returns kind +
  location + a redacted neighbourhood, **never the matched value**),
  `redact_secrets_in_text` (scrubs literals from retained HTML after scanning),
  `looks_like_jwt` / `looks_like_token` / `shannon_entropy`.
* **`antibot.py`** — `detect()` on status codes, body markers and edge-vendor
  headers. `blocked_reason()` produces the sentence recorded on every dependent
  control. Policy: **detect, stop, record, report.** Never bypass.
* **`limits.py`** — `TrafficBudget` counts navigations, auxiliary requests and
  pages, enforces the timeout, and keeps an attributed log of every request.

---

## 6. Evidence collectors

The authorisation boundary is not invented here.
`Rules/19_test_modes_safety.md` enumerates what passive mode may observe; the
collector set is that sentence made executable.

| Code | Source | Cost | Feeds |
|---|---|---|---|
| `HDR` | response events | free | NET-01/03 · WEB-01/02/03/04/10 · PERF-05 |
| `CK` | context.cookies() | free | WEB-05 · PRIV-06 |
| `WS` | page.evaluate | free | WEB-06 |
| `DOM` | page.content() | free | WEB-07/09 · APP-04 |
| `JS` | same-origin bodies | free | WEB-09 |
| `NET` | request/response log | free | WEB-08 · PRIV-06/10 |
| `CON` | console, pageerror | free | WEB-01/08 |
| `TIM` / `CWV` | PerformanceObserver | free | PERF-01/02 |
| `A11` | injected axe-core | free | A11Y-01/03/06 |
| `FRM` / `LNK` / `3P` / `CACHE` / `SHOT` | DOM / derived | free | various |
| `RDR` | 1 request | 1 req | NET-01 |
| `TLS` | stdlib ssl | 1 conn | NET-02/04 |
| `DNS` | dnspython | off-target | NET-05/06 |
| `WK` | 2 fetches | 2 req | IR-05 (informational) |
| `ERR` | 1 benign 404 | 1 req | WEB-10 · APP-07 |
| `CORS` / `SELF` | derived / metadata | free | informational · GOV-05 · IN-07 |

**15 of 22 come from a single page load.** A full run is roughly
**1 navigation + 4 auxiliary requests + 12 performance navigations ≈ 17
page-equivalent hits** — quieter than one human browsing session.

`CORS` and `security.txt` are authorised by the safety doc but **no control in
the 144 consumes them**. They are reported as `INFORMATIONAL` only. Adding
controls for them is a recommendation, not something the system invents.

---

## 7. The two result vocabularies

The delivery contract mandates four values. The rule pack — the stated source
of truth — mandates six, and explains why `NOT_TESTABLE` must stay distinct:

> *"keeping NOT_TESTABLE as a scanner-internal status prevents false claims of
> compliance."* — `Rules/00_README.md`

Collapsing six into four destroys that. So every result carries **both**.

| Pack-native | Contract | Typical trigger |
|---|---|---|
| `PASS` | `YES` | header present with a conforming value |
| `FAIL` | `NO` | response captured, control provably absent |
| `N/A` | `NOT_APPLICABLE` | control does not apply to this target |
| `WARN` | `UNKNOWN` | partial evidence; human review needed |
| `NOT_TESTABLE` | `UNKNOWN` | all 96 `M` and 6 `No` controls |
| `INFORMATIONAL` | `UNKNOWN` | `PERF-01` lab vitals, `A11Y-01` axe subset |

Excel Sheet 2 carries both columns plus `unknown_reason`, so a reader can
always tell *"we looked and could not decide"* from *"this is out of scope for
a browser."* That distinction is the report's integrity.

**FAIL is the evidenced negation of PASS, never the absence of evidence.** The
pack gives PASS criteria and no FAIL criteria, so `WEB-02` fails only when a
response is observed lacking `nosniff`; it returns `NOT_TESTABLE` when no
response was captured at all.

---

## 8. How a rule is evaluated (no hardcoded rule logic)

```
Markdown row
   → SecurityRule                 (positional table parse)
   → RuleInterpretation           (LLM, cached on content_hash)
   → evidence projection          (generic, keyed by CollectorCode)
   → LLM proposal                 (rule text + projected evidence)
   → deterministic validation     (Python — the important stage)
   → SecurityResult
```

There is **no `if control_id == "WEB-01"`** anywhere in `app/`.

### Stage 0 — deterministic short-circuit

If `automation.has_passive_component` is false, the result is `NOT_TESTABLE`
with a reason quoting the pack's own test method. ~102 of 144 controls, zero
LLM calls, driven by the `Auto?` column.

### Stage 2 — the anti-fabrication gate

`citation_is_grounded(observed_value, corpus)` decides whether a cited value
actually appears in the evidence. Three passes, cheapest first:

1. direct substring
2. punctuation-insensitive whole-string
3. token coverage — ≥70% of substantive tokens must appear

Short citations (a status code) skip to **whole-token** matching, because
substring matching is meaningless at that length (`"ok"` is inside `"cookies"`).

**A `PASS` or `FAIL` whose `observed_value` is not grounded is rejected and
downgraded to `NOT_TESTABLE`, with the downgrade recorded as the evidence
string.** This is a post-check in code, not a plea in a prompt — it is why the
system cannot report an invented finding.

> **Regression worth remembering.** The first implementation normalised the
> citation (stripping punctuation *and spaces*) **before** splitting into
> tokens, which collapsed every citation into one giant token and rejected
> legitimately-grounded verdicts. Tokenise first, normalise each token. Locked
> in by `test_tokeniser_splits_on_punctuation_not_into_one_blob`.

`validate_results()` in the aggregator then enforces two final invariants:
`result` is always the correct projection of `native_result`, and any
`PASS`/`FAIL` without an `observed_value` is downgraded.

---

## 9. Performance and network testing

Measured where available: DNS, TCP, TLS, TTFB, DOMContentLoaded, load,
transferred bytes, request/response/failed counts, redirects, plus **lab** LCP
and CLS.

**Not available, and never fabricated:**

* **INP** — requires real user input. Always `None`.
* **Field p75** — `PERF-01` asks for the 75th percentile of CrUX/RUM data and
  states *"lab is supplementary"*. Twelve lab loads from one machine are not a
  75th percentile of real users, so **`PERF-01` can never be `PASS` from this
  tool.** It returns `INFORMATIONAL` carrying the measurement.
* **Server p50/p95/p99 across flows** — needs APM.

Profiles are configuration (`config.yaml`), converted Mbps→bps at the config
boundary. Each profile has `per_profile_budget_seconds`; exceeding it retains
completed iterations and marks the profile `PARTIAL`. A slow target degrades
the report, never aborts the run.

---

## 10. Persistence

Four sheets as specified, plus columns preserving the pack's vocabulary.

1. **Assessment Summary** — the 9 specified columns + `native_*` counts,
   `coverage_pct`, `pack_version`, `browser_version`, `llm_model`,
   `duration_seconds`, `blocked_reason`.
2. **Security Results** — the 9 specified + `native_result`, `severity`,
   `automation_tier`, `observed_value`, `unknown_reason`, `evaluated_by`,
   `source_file`, `source_line`.
3. **Performance Results** — the 12 specified + `lcp`, `cls`, `inp`,
   `redirect_count`, `succeeded`, `error`.
4. **Performance Statistics** — the 9 specified + `n`, `success_rate`,
   `failure_rate`.

`source_file`/`source_line` give the traceability `IN-07` requires. The four
sheets map one-to-one onto four Postgres tables keyed on `assessment_id`, which
is what makes the migration a genuine drop-in.

---

## 11. Safety boundaries (non-negotiable)

**Never implemented:** exploitation · brute force · credential attacks ·
authentication bypass · DoS · destructive requests · CAPTCHA solving ·
anti-bot evasion · IP rotation · stealth patches · crawling.

**Enforced structurally, not by convention:**

| Guarantee | Mechanism |
|---|---|
| No unattributed traffic | `TrafficBudget.navigate()` requires a `reason` |
| Traffic is capped | `max_navigation_count`, `max_pages`, timeout |
| No action outside the plan | actions come from `AssessmentPlan.actions` |
| Browsing stops when done | evidence is frozen; no evaluator holds a page handle |
| Secrets never persist | redaction at capture; `html_source` `exclude=True` |
| Blocks are reported, not routed around | `antibot.detect()` → `BLOCKED` |
| No login in passive mode | default mode never authenticates |
| No form is ever submitted | forms are inventoried structurally |

**On a block:** halt all requests, set `status = BLOCKED`, record the response
as evidence, mark every dependent control `UNKNOWN` with the reason. No retry,
no backoff-and-persist, no UA or IP rotation.

**Authorization.** Passive mode is the only default. `GOV-02` requires written
authorization before active testing; anything beyond L1 needs
`assessment.mode` plus a recorded `authorization_reference`. Assess only
targets you are authorized to test.

---

## 12. Testing

```bash
pytest tests/unit           # no network, no browser
pytest tests/integration    # real Chromium, LOCAL fixture site only
pytest                      # everything
```

Integration tests bind `127.0.0.1` and **never touch a public website** — the
pack's safety boundary applies to our own suite. `tests/fixtures/site/` is
deliberately broken: no CSP, no HSTS, an insecure `sessionid` cookie, a
third-party script without SRI, a JWT in `localStorage`, an AWS key and a
password literal in `app.js`, a stack-trace-leaking 404, and version-disclosing
headers.

`tests/fixtures/ux_site/` is the behaviour agent's target and is broken in a
different way: a button with no handler bound, a 620 ms search debounce, an
add-to-cart that fetches with no pending state, a banner injected after load,
an icon button with no accessible name, `outline: none` with no replacement,
and — planted so the agent can refuse them — "Buy now", "Place order", "Empty
the cart" and a card-number field. Its server answers **405 to every POST**,
so a form submission that ever landed would fail the suite.

Notable guarantees under test: the loader parses exactly 144 controls and the
tier distribution matches the pack · a new family file needs zero code change ·
`Rules/` resolves case-insensitively · statistics match hand-computed fixtures ·
`stddev` is `None` at n=1 and empty samples fabricate no zeros · fabricated
verdicts are downgraded while reformatted-but-real ones survive · **no planted
secret reaches the serialized bundle or the retained HTML** · only requested
collectors run.

---

## 13. Known gaps and decisions

| # | Issue | Resolution |
|---|---|---|
| A1 | Contract wants 4 result values, pack defines 6 | emit both; pure projection (§7) |
| A2 | `NET-03` "organizationally approved max-age" — no number | `policy.yaml`, default 15768000s; unset → `WARN` |
| A3 | `NET-02` "organization baseline" — undefined | default TLS 1.2+, policy-overridable |
| A4 | `PERF-02` "approved SLOs" — none supplied | `INFORMATIONAL` unless configured |
| A5 | `IAM-03` marked `P` but needs account comparison, which `19_test_modes_safety.md` forbids publicly | **pack contradicts itself**; safety model wins → `NOT_TESTABLE` |
| A6 | PASS criteria given, FAIL never | FAIL = evidenced negation only |
| A7 | Schema defines `test_layer`/`framework_mapping`/`remediation`/`owner`; no table populates them | derive `test_layer`; leave the rest null |
| A8 | `A11Y-01` "WCAG 2.2 AA" — automation covers a minority of criteria | `INFORMATIONAL` |
| A9 | No control declares dependencies | treat all 144 as independent — makes the fan-out safe |
| A10 | `GOV-05`, `IN-07` are about the audit report itself | self-satisfying; the engine emits the required metadata |

**Optional, off by default:** a CrUX API client would be the only route to a
real `PERF-01` verdict, but it sends the target URL to Google, so it stays off
unless explicitly enabled. `vendor/axe.min.js` is not shipped; drop a copy in
to enable full axe-core analysis (structural heuristics run regardless).

---

## 14. Extending the system

| To add | Do this | Do NOT |
|---|---|---|
| a security control | add a row to a `Rules/*.md` table | write Python |
| a control family | add `Rules/NN_name.md` with the same table shape | touch the loader |
| an evidence collector | add a `CollectorCode`, a collector fn, a `_PROJECTORS` entry, mention it in `INTERPRETER_SYSTEM` | hardcode which rule uses it |
| an LLM provider | implement `LLMProvider`, register in `build_provider()` | import it outside `app/llm/` |
| a storage backend | implement the repository Protocol, register in `build_repository()` | import it in an agent |
| a network profile | add it to `network_profiles` in `config.yaml` | hardcode bandwidth |
| an org threshold | add it to `policy.yaml` + `Policy` | bake it into a rule check |
| a user journey | add it to `heuristic_journeys()` in `app/behaviour/brain.py`, gated on an observed affordance | assume the affordance exists |
| a UX finding | add a block to `generate_findings()` citing `ActionRecord.seq` | write one without evidence |
| a browser action the agent can take | add an `ActionKind`, a dispatch branch in `executor.py`, a category in `INTERACTION_CATEGORY` | let it bypass `safety.guard()` |

### House rules

1. **Evidence first.** Every claim traces to something observed.
2. **Prefer `UNKNOWN`.** Never force a verdict evidence does not support.
3. **The LLM never computes.** Arithmetic, counts and percentiles are Python.
4. **The LLM never drives the browser.** It plans; Python executes.
5. **Every browser action names the control that needs it.**
6. **Redact at capture,** never at report time.
7. **One failure is scoped.** A `ComponentError` is recorded; the run continues.
8. **Never invent a rule.** `Rules/` is the source of truth; recommendations go
   in documentation, not into the assessment.

---

## 15. The User Behaviour Agent

A second product surface, added alongside the security assessment and sharing
nothing with it but the browser, the LLM provider, the traffic budget and the
safety layer. `Rules/` is not consulted here at all.

The two answer different questions:

| | Security assessment | User Behaviour Agent |
|---|---|---|
| asks | is this control satisfied? | what would a real user experience? |
| source of truth | `Rules/` — 144 controls | the site itself |
| interaction | one instrumented page load | an autonomous session, ~20-60 actions |
| output | coverage, per-control verdicts | a UX score, findings, a journey |
| entry points | `python -m app.main` · `POST /analyze` | `python -m app.behaviour` · `POST /behaviour` |

```bash
python -m app.behaviour --url https://example.com
python -m app.behaviour --url https://example.com --dry-run     # plan + budget only
python -m app.behaviour --url https://example.com --no-llm      # deterministic
python -m app.behaviour --url https://example.com --headed --pacing 0.4
python -m app.behaviour --url https://example.com --json out.json
```

Exit codes match `app/main.py`: `0` completed · `1` failed · `2` bad URL ·
`4` blocked by the target · `130` interrupted.

### 15.1 The loop

```
                        OBSERVE
                           │  observer.py — DOM, a11y, structure, vitals
                           ▼
                       UNDERSTAND
                           │  brain.py — what is this site? (1 LLM call)
                           ▼
                          PLAN
                           │  brain.py — what journeys? (1 LLM call)
                           ▼
        ┌──────────────► DECIDE ◄──────────────┐
        │                  │  what would a person do next?
        │                  ▼
        │                 ACT      executor.py — the only thing that
        │                  │       touches the page
        │                  ▼
        │               MEASURE    measure.py — four clocks
        │                  │
        │                  ▼
        │             OBSERVE AGAIN
        │                  │
        │            did it do what a
        │            visitor would expect?
        │             ┌────┴────┐
        └── yes ──────┘         └────── no ──► ADAPT ──┐
                                                       │
        └──────────────────────────────────────────────┘
                           │
                           ▼
                        REPORT      scoring.py + report.py — pure Python
```

The state machine (`AgentState`) is `DISCOVERING → UNDERSTANDING → PLANNING →
NAVIGATING → INTERACTING → OBSERVING → MEASURING → ADAPTING → REPORTING →
COMPLETED`, and the interface renders it live.

### 15.2 The house rules, applied

The repository's rules hold here unchanged, and each one is enforced
structurally rather than by convention:

| Rule | How |
|---|---|
| The LLM never computes | every latency, percentile and score comes from `measure.py` / `scoring.py` |
| The LLM never drives the browser | it returns an `ActionIntent` naming a `ref` the observer already saw and classified; there is no path from a model response to a selector, a URL or a script |
| Evidence first | a `UXFinding` cannot be constructed without `observed`, `expected` and the `ActionRecord.seq` values behind it |
| Prefer UNKNOWN | an unobserved metric is `None`, never `0`; an undecidable outcome is `INCONCLUSIVE`, never a pass |
| Every action names its reason | `ActionIntent.reason` is mandatory and reaches the report |
| One failure is scoped | a journey that fails is recorded and the session continues |

**The model plans; Python walks.** `understand` and `plan_journeys` are two
LLM calls. Resolving a planned step against the elements on the page is
deterministic — `llm_decides_steps` turns per-step model calls on, and it is
off by default because it adds one round trip per action (~45 s each against
a local 7B, so a 60-action session becomes a 45-minute one). `adapt` still
calls the model: a failure has actually happened and the judgement earns its
latency.

**Every model call has a deadline.** `llm_call_timeout_seconds` (45 s) is not
`llm.timeout_seconds` (the HTTP timeout, which has retries behind it). Past
the deadline the heuristic answer is used, `derived_by` records `heuristic`,
and the report says the model was too slow. A run with `--no-llm` is a
heuristic agent, not a broken one.

### 15.3 The four clocks

§10 of the brief is the reason `measure.py` exists apart from the executor.
"How fast is the site?" has several answers that routinely disagree by an
order of magnitude:

```
dispatch ──► something reacted          input_latency_ms
         ──► the user could SEE it      ui_response_ms
         ──► the request came back      network_first_byte_ms / _complete_ms
         ──► the page stopped changing  state_complete_ms
```

A button whose network call returns in 90 ms but whose spinner appears at
600 ms is a slow button, and only the second clock says so. `perceived_ms` is
the one the scores use: what the user saw, falling back to the network only
when nothing was painted — which is itself the signature of the `UX-SILENT`
finding.

Three measurement hazards are handled explicitly, each discovered against
`tests/fixtures/ux_site/`:

* **Contamination.** Deferred work from the previous action — a 620 ms
  debounce, a late banner — lands during the next measurement and is
  attributed to it. A dead button gets credited with a response it did not
  cause. `MeasurementEngine.isolate()` waits for the page to go still before
  marking `t0`, and `PROBE_MARK` clears everything observed before it.
* **Patience.** Concluding "no response" after a few hundred milliseconds
  reports every debounced control on the web as broken. `no_response_ms`
  (2.5 s) is deliberately much larger than `quiet_ms` (260 ms).
* **Document replacement.** A navigation destroys the in-page probe, so
  reading it afterwards returns null. Reporting that as "inconclusive" is how
  a working link is counted as a broken one. Navigations are measured from
  the new document's own navigation timing instead.

**Never measured, never fabricated:** INP. It requires real users'
interactions over a session. It serialises as `null` and always will.

### 15.4 What the agent will not do

The classifier in `app/behaviour/safety.py` decides this once, per element,
before the model ever sees the page. `executor.py` asks only "is this
cleared?", and a refusal becomes an `Outcome.REFUSED` record in the report —
data, not a silent skip.

* **FORBIDDEN, never dispatched:** place order · buy now · pay · transfer
  funds · delete · close account · cancel an order · unsubscribe · empty the
  cart · reset password · publish · post a comment · send a message · any
  credential, card or identity field · `mailto:`/`tel:`/`javascript:` links.
* **SENSITIVE, approached and never completed:** sign in · sign up ·
  checkout · contact forms · start a trial. The agent may *reach* a checkout
  page; it may not press the button that charges a card.
* **No form is ever submitted.** The single exception is a search box, whose
  entire payload is a query the agent wrote from the site's own words.
* **One host.** Off-site links are inventoried and never followed.
* **Blocks are reported, not routed around** — `antibot.detect()` halts the
  session, exactly as in §11.

On human pacing: the agent hovers before clicking, pauses after navigating,
and scrolls in steps. This is a *measurement* requirement, not an evasion
one — a hover menu never opens if you teleport the cursor onto the link, and
lazy content never arrives if you jump to the footer, so a robotic agent
measures a page no user ever sees. The browser still identifies itself
normally and carries no stealth patches.

### 15.5 Scoring

`scoring.py` is pure. Seven components, each carrying its own sample size:

`Interaction Speed` · `Navigation` · `Responsiveness` · `Visual Experience` ·
`Accessibility` · `Interaction Reliability` · `Scroll Experience`

Three refusals define it:

1. **A component with no observations scores `None` and is excluded** from
   the weighted mean — never scored zero. A site where nothing was scrollable
   is not punished for it, and `UNRATED` is a real outcome.
2. **The sample size travels with the number.** "Navigation: 88" off two page
   loads is not the claim "88" off twenty.
3. **Every threshold is published and named at the point of use** — RAIL's
   100 ms / 1 s, Core Web Vitals' LCP and CLS boundaries. Where none exists
   (scroll smoothness, reliability) the boundary is arithmetic on the frame
   budget or a plain ratio, and says so.

`Accessibility` is structural only and labelled as such: automated tooling
reaches a minority of WCAG 2.2 criteria — the same limit §13/A8 records for
`A11Y-01`.

### 15.6 Modules

```
app/behaviour/
  models.py      three vocabularies: what was SEEN, DONE, CONCLUDED
  safety.py      the classifier — what may and may not be touched
  js.py          the injected probes; the only code that runs in the target's origin
  observer.py    DOM + a11y + structure + vitals -> PageModel
  measure.py     the four clocks, scroll frames, the isolate/settle lifecycle
  memory.py      visited / tried / dead / learned — what stops a random walk
  brain.py       understand, plan, decide, adapt — each with a full heuristic
  prompts.py     four prompts, one per question the model may answer
  executor.py    the only module that touches the page
  scoring.py     UX score + findings, pure
  report.py      journey timeline, insights, summaries
  agent.py       the loop, the state machine, and the four brakes
  runner.py      one session, driven identically from CLI and API
  serializers.py projection onto web/lib/behaviourTypes.ts
  main.py        CLI
app/api/behaviour.py   the /behaviour router, mounted alongside /analyze
```

**Four independent brakes**, any one of which ends a session cleanly: the
traffic budget · a per-journey step ceiling · a global action ceiling ·
consecutive-failure detection per journey. A block from the target is not a
brake — it is an answer.

### 15.7 The interface

`web/components/behaviour/` — the journey map with the travelling pixel agent
(§14), the live HUD (§15), the agent log (§16), the score dial (§17) and the
report (§18-20, §24). `web/lib/fluid.ts` is the scroll engine §13 asks for.

Two notes worth keeping:

* **Velocity, not position.** Most "smooth scroll" lerps the scroll position
  toward a target, which literally delays the content behind the user's
  input: smooth, and slower. `fluid.ts` leaves the position honest and
  interpolates the *reaction* — signed velocity is published to `--v`/`--va`
  on `<html>` from one rAF loop, and animations scale with it. Fast **and**
  smooth, which is what §13 asks for and what most implementations get
  backwards.
* **Accumulate in the callback, not the render.** React batches state
  updates, and the SSE stream replays its whole history the moment the
  browser subscribes — so a dozen frames can collapse into one render.
  Anything carried by exactly one frame is then lost, and the journey map is
  carried by exactly one frame. The map and the visited trail are accumulated
  in the message callback, which runs once per message.

### 15.8 Known gaps and decisions

| # | Issue | Resolution |
|---|---|---|
| B1 | "Perceived response" has no single definition | four clocks, all reported; `perceived_ms` is defined and documented (§15.3) |
| B2 | Deferred work contaminates the next measurement | `isolate()` before `mark()`; the report notes when a page never went still |
| B3 | A debounced control looks dead under a short patience | `no_response_ms` is 2.5 s, an order above `quiet_ms` |
| B4 | Focus is a real response for a field and a non-response for a button | focus feeds `input_latency_ms` always, and `ui_response_ms` only for text fields |
| B5 | A hover that opens nothing is not a defect | only *pressed* actions can mark a control dead or produce `UX-DEAD` |
| B6 | Journey completion cannot be inferred from the action log | recovery actions reuse their step label; the loop's own bookkeeping decides |
| B7 | A local 7B is too slow for a per-step call | `llm_decides_steps: false`, plus a deadline on every call (§15.2) |
| B8 | INP cannot be produced by a lab agent | always `null`, and the report says why |
| B9 | The agent's exploration order is not deterministic | session-level tests assert on properties; the specific measurements are pinned by driving the executor directly |
