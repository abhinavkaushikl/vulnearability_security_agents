"""CLI for the User Behaviour Agent.

    python -m app.behaviour --url https://example.com
    python -m app.behaviour --url https://example.com --no-llm --pacing 0.4
    python -m app.behaviour --url https://example.com --headed --max-actions 30
    python -m app.behaviour --url https://example.com --dry-run

Exit codes mirror app/main.py so the two can be scripted together:
  0 completed · 1 failed · 2 bad URL · 4 blocked by the target · 130 interrupted
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from app.behaviour.models import AgentState, BehaviourProgress, Severity
from app.behaviour.runner import InvalidTarget, SessionOptions, run_session
from app.behaviour.serializers import to_json
from app.config.settings import load_settings

log = logging.getLogger("behaviour")

# The security engine's report renderer leads with coverage rather than a
# score, for reasons CLAUDE.md §1 sets out at length. This one leads with the
# score because the score IS the finding — but every component still carries
# its sample size, and an unmeasured component prints "—", never a zero.

_RESET = "\033[0m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_AMBER = "\033[38;5;214m"
_RED = "\033[38;5;203m"
_GREEN = "\033[38;5;114m"


def _c(text: str, colour: str, enabled: bool) -> str:
    return f"{colour}{text}{_RESET}" if enabled else text


def _bar(value: int | None, width: int = 22) -> str:
    if value is None:
        return "─" * width
    filled = int(round(width * value / 100))
    return "█" * filled + "·" * (width - filled)


def render(report, colour: bool) -> str:
    out: list[str] = []
    add = out.append
    score = report.score

    add("")
    add(_c("  USER BEHAVIOUR REPORT", _BOLD, colour))
    add(f"  {report.target}")
    add(f"  {_c(report.state.value, _AMBER, colour)} · "
        f"{report.duration_seconds:.1f}s · {report.requests_made} requests")
    add("")

    if report.blocked_reason:
        add(_c("  BLOCKED", _RED, colour))
        add(f"  {report.blocked_reason}")
        add("")

    add(f"  The agent read this as a {_c(report.understanding.kind.value, _BOLD, colour)} "
        f"site ({report.understanding.derived_by}, "
        f"confidence {report.understanding.confidence:.0%}).")
    if report.understanding.primary_goal:
        add(f"  A visitor comes here to {report.understanding.primary_goal}.")
    add("")

    # ── the score ────────────────────────────────────────────────────────
    if score.overall is not None:
        add(f"  {_c(f'{score.overall}', _BOLD, colour)}/100   "
            f"{_c(score.band.value, _AMBER, colour)}")
    else:
        add(f"  {_c('UNRATED', _DIM, colour)} — too little was observable to "
            "put a number on it")
    add(f"  {_DIM if colour else ''}{score.method}{_RESET if colour else ''}")
    add("")
    for c in score.components:
        value = f"{c.score:>3}" if c.score is not None else "  —"
        add(f"    {c.name:<26} {value}  {_bar(c.score)}  "
            f"{_DIM if colour else ''}n={c.n}{_RESET if colour else ''}")
    add("")

    # ── journeys ─────────────────────────────────────────────────────────
    add(_c("  JOURNEYS", _BOLD, colour))
    for j in report.journey_outcomes:
        mark = (_c("✓", _GREEN, colour) if j.completed
                else _c("✗", _RED, colour))
        add(f"    {mark} {j.name:<30} "
            f"{j.steps_succeeded}/{j.steps_planned} steps"
            + (f"  — stopped at {j.abandoned_at}" if not j.completed
               and j.abandoned_at else ""))
    if not report.journey_outcomes:
        add(f"    {_c('no journey produced an action', _DIM, colour)}")
    add("")

    # ── the walk, with the latency on each arrow ─────────────────────────
    from app.behaviour.report import journey_timeline
    timeline = journey_timeline(report)
    if timeline:
        add(_c("  WHAT HAPPENED", _BOLD, colour))
        for row in timeline[:24]:
            if row["ms"] is not None:
                ms = f"{row['ms']:.0f} ms"
            elif row["outcome"] == "NO_RESPONSE":
                ms = "no response"
            elif row["outcome"] == "SUCCESS":
                ms = "—"          # it worked; there was nothing to time
            else:
                ms = row["outcome"].lower()
            flag = (_c(" ⚠", _AMBER, colour) if row["slow"]
                    else _c(" ✗", _RED, colour) if not row["ok"] else "")
            add(f"    {row['label'][:44]:<44} {ms:>12}{flag}")
        if len(timeline) > 24:
            add(f"    {_c(f'... {len(timeline) - 24} more', _DIM, colour)}")
        add("")

    # ── findings ─────────────────────────────────────────────────────────
    add(_c("  FINDINGS", _BOLD, colour))
    if not report.findings:
        add(f"    {_c('nothing crossed a reporting threshold', _DIM, colour)}")
    for f in report.findings:
        col = (_RED if f.severity in (Severity.CRITICAL, Severity.HIGH)
               else _AMBER)
        sev = f.severity.value.ljust(9)
        add(f"    {_c(sev, col, colour)} {f.title}")
        add(f"      observed  {f.observed}")
        add(f"      expected  {f.expected}")
        add(f"      fix       {f.recommendation}")
        add("")

    # ── refusals: the agent saying what it would not do ──────────────────
    refused = [a for a in report.actions if a.outcome.value == "REFUSED"]
    if refused:
        add(_c("  DECLINED", _BOLD, colour))
        for a in refused[:6]:
            add(f"    {a.observed}")
        add("")

    add(_c("  INSIGHTS", _BOLD, colour))
    for q, answer in report.insights.items():
        add(f"    {_c(q, _DIM, colour)}")
        add(f"      {answer}")
    add("")

    add(_c("  SUMMARY", _BOLD, colour))
    for line in _wrap(report.summary, 76):
        add(f"    {line}")
    add("")

    add(f"  {_c('MISSION COMPLETE', _BOLD, colour)}   "
        f"pages {report.pages_explored} · interactions {report.interactions_total} "
        f"· journeys {report.journeys_run} · issues {report.issues_detected} "
        f"({report.critical_issues} critical)")
    if report.errors:
        add(f"  {_c('non-fatal:', _DIM, colour)} {'; '.join(report.errors[:3])}")
    add("")
    return "\n".join(out)


def _wrap(text: str, width: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines or [""]


def _progress_printer(quiet: bool):
    seen = {"n": 0}

    def sink(p: BehaviourProgress) -> None:
        if quiet:
            return
        if p.thought is not None:
            t = p.thought
            lat = f"  {t.latency_ms:.0f}ms" if t.latency_ms is not None else ""
            mark = "·" if t.ok is None else ("✓" if t.ok else "✗")
            print(f"  {mark} [{t.state.value:<13}] {t.action}{lat}",
                  file=sys.stderr)
            if t.result:
                print(f"      {t.result[:110]}", file=sys.stderr)
            seen["n"] += 1
    return sink


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m app.behaviour",
        description="Send an autonomous AI user into a website and measure "
                    "what it experiences.")
    p.add_argument("--url", required=True, help="target (required)")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--policy", default="policy.yaml")
    p.add_argument("--max-actions", type=int,
                   help="ceiling on dispatched actions for the session")
    p.add_argument("--max-steps", type=int, dest="max_steps",
                   help="ceiling on steps per journey")
    p.add_argument("--pacing", type=float,
                   help="human pause multiplier; 0 removes every pause")
    p.add_argument("--seed", type=int,
                   help="fix the pacing jitter so a run reproduces exactly")
    p.add_argument("--llm-steps", action="store_true", dest="llm_steps",
                   help="ask the model for every step, not just the plan "
                        "(one round trip per action — slow on a local model)")
    p.add_argument("--no-llm", action="store_true",
                   help="heuristics only; journeys and decisions become "
                        "deterministic and the report says so")
    p.add_argument("--headed", action="store_true", help="show the browser")
    p.add_argument("--no-screenshots", action="store_true")
    p.add_argument("--json", dest="json_path",
                   help="also write the full report as JSON to this path")
    p.add_argument("--quiet", action="store_true",
                   help="suppress the live action feed")
    p.add_argument("--dry-run", action="store_true",
                   help="print the plan and the budget; open no browser")
    p.add_argument("--no-colour", action="store_true")
    return p


async def _run(args) -> int:
    options = SessionOptions(
        max_actions=args.max_actions,
        max_steps_per_journey=args.max_steps,
        pacing=args.pacing,
        no_llm=args.no_llm,
        headed=args.headed,
        screenshots=False if args.no_screenshots else None,
        seed=args.seed,
        llm_decides_steps=True if args.llm_steps else None)

    if args.dry_run:
        settings = load_settings(args.config, args.policy, options.overrides())
        b = settings.behaviour
        print(f"\n  target            {args.url}")
        print(f"  mode              autonomous behaviour session "
              f"({'heuristic' if args.no_llm else 'llm-assisted'})")
        print(f"  action ceiling    {b.max_actions} dispatched actions")
        print(f"  per journey       {b.max_steps_per_journey} steps")
        print(f"  navigation budget {b.max_navigations} page loads")
        print(f"  pacing            {b.pacing}× human pauses")
        print(f"  settle window     {b.settle_quiet_ms} ms quiet, "
              f"{b.settle_max_ms} ms ceiling")
        print(f"  timeout           {b.timeout_seconds}s")
        print("\n  The agent will never: complete a purchase, submit "
              "credentials, send a\n  message, delete anything, or follow a "
              "link off this host.\n")
        return 0

    colour = sys.stdout.isatty() and not args.no_colour
    try:
        report = await run_session(
            args.url, config=args.config, policy=args.policy,
            options=options, progress=_progress_printer(args.quiet))
    except InvalidTarget as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(render(report, colour))

    if args.json_path:
        path = Path(args.json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(to_json(report), indent=2, default=str))
        print(f"  report written to {path}\n")

    if report.state is AgentState.BLOCKED:
        return 4
    if report.state is AgentState.FAILED:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)-7s %(name)-22s %(message)s",
        datefmt="%H:%M:%S")
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("\ninterrupted; the browser was closed", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
