# Website Security & Performance Assessment System

An agentic assessment system that drives a real browser against a website,
evaluates it against the **144-control rule pack** in [`Rules/`](Rules/), measures
performance under several network profiles, and writes a structured report.

`Rules/` is the source of truth. **No security rule is hardcoded** — adding a
Markdown file adds controls with zero code change.

> **Read [`CLAUDE.md`](CLAUDE.md)** for the full architecture and module reference.

---

## The honest headline

The rule pack is an enterprise e-commerce audit baseline, not a list of website
checks. Of its 144 controls, its own `Auto?` column marks:

```
 25  P     passive automation possible          ███▌
 17  P/M   hybrid — partial browser evidence    ██▍
 96  M     needs staging / authorized testing   █████████████▌
  6  No    not provable from a website at all   ▊
```

**102 of 144 are unreachable from any browser.** This system loads all of them,
evaluates what the evidence supports, and returns `UNKNOWN` *with a stated
reason* for the rest. It reports coverage, not a score — because the pack says
so itself:

> `PCI-10`: *"Never treat a web header/SSL scan as proof of PCI compliance."*

---

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

Optional local model — improves coverage, but the system runs without it:

```bash
ollama pull qwen3-coder     # any qwen2.5-coder / qwen2.5 build also works
```

## Run

```bash
# Print the plan and the exact request budget WITHOUT touching the target
python -m app.main --url https://example.com --dry-run

# Full assessment
python -m app.main --url https://example.com

# Subset
python -m app.main --url https://example.com \
    --families NET,WEB --network-profiles fast,3g --iterations 2 --skip-performance
```

Output lands in `artifacts/<assessment_id>/` — Excel workbook, screenshots, logs.

## Test

```bash
pytest                    # 116 tests
pytest tests/unit         # no network, no browser
pytest tests/integration  # real Chromium against a LOCAL fixture site only
```

Integration tests bind `127.0.0.1` and never touch a public website.

---

## How it works

```
LOAD_RULES → PLAN → COLLECT_EVIDENCE → ┬→ EVALUATE (parallel, zero traffic)
                                       └→ PERFORMANCE (sequential, owns network)
                                          → AGGREGATE → PERSIST
```

* **One instrumented page load** feeds 15 of 22 evidence collectors. A full run
  is ~17 page-equivalent hits — quieter than one human browsing session.
* **The LLM never drives the browser** and never computes a statistic. It
  interprets Markdown rules (cached forever), judges evidence, and writes prose.
* **Rule evaluations run in parallel** because they read a frozen in-memory
  bundle. **Network profiles run in series** because they share one uplink —
  running them concurrently would measure contention, not the profile.
* **A verdict citing evidence that was never collected is rejected** by a
  deterministic post-check in Python and downgraded to `UNKNOWN`.

## Results carry two vocabularies

The pack defines six result values; the delivery contract wants four. Both are
persisted, so a reader can always tell *"we looked and could not decide"* from
*"this is out of scope for a browser."*

| Pack-native | Contract |
|---|---|
| `PASS` / `FAIL` / `N/A` | `YES` / `NO` / `NOT_APPLICABLE` |
| `WARN` / `NOT_TESTABLE` / `INFORMATIONAL` | `UNKNOWN` |

## Configuration

`config.yaml` — browser, traffic limits, network profiles, LLM, storage.
`policy.yaml` — organizational thresholds the pack references but never defines
(HSTS max-age, TLS baseline, performance SLOs). Unset thresholds produce `WARN`
rather than a fabricated verdict.

---

## Safety

Authorized, defensive, passive by default. This system does **not** implement
exploitation, brute force, credential attacks, authentication bypass, DoS,
CAPTCHA solving, anti-bot evasion, IP rotation or crawling. It submits no forms
and attempts no logins in passive mode.

If a target challenges or rate-limits the assessment, it **stops, records the
response, and reports it** — there is no bypass path in the code.

`GOV-02` requires written authorization before active testing. **Assess only
targets you are authorized to test.**
