"""CLI entry point.

    python -m app.main --url https://example.com
    python -m app.main --url https://example.com \
        --network-profiles fast,4g,3g --iterations 3
    python -m app.main --url https://example.com --dry-run

`--dry-run` prints the resolved plan and the exact request budget without
opening a browser. It is the review step before pointing this at anything real.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from app.config.settings import load_settings
from app.graph.state import AssessmentState
from app.graph.workflow import build_workflow
from app.llm.qwen import build_provider
from app.models.assessment import AssessmentStatus
from app.repositories.base import build_repository
from app.safety.limits import TrafficBudget
from app.tools.browser import BrowserSession
from app.tools.report import render_console_report

log = logging.getLogger("assessment")


def setup_logging(level: str, log_file: Path | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file))
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)-28s %(message)s",
        datefmt="%H:%M:%S", handlers=handlers, force=True)
    for noisy in ("httpx", "httpcore", "asyncio", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m app.main",
        description="Agentic website security & performance assessment. "
                    "Passive by default; assess only targets you are "
                    "authorized to test.")
    p.add_argument("--url", required=True, help="target website URL")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--policy", default="policy.yaml")
    p.add_argument("--network-profiles",
                   help="comma-separated, e.g. fast,4g,3g,slow")
    p.add_argument("--iterations", type=int, help="performance iterations per profile")
    p.add_argument("--families", help="evaluate only these families, e.g. NET,WEB")
    p.add_argument("--skip-performance", action="store_true")
    p.add_argument("--no-llm", action="store_true",
                   help="skip the model entirely; deterministic results only")
    p.add_argument("--headed", action="store_true", help="show the browser")
    p.add_argument("--dry-run", action="store_true",
                   help="print the plan and request budget; open no browser")
    p.add_argument("--output", help="override the report output directory")
    p.add_argument("--log-level", default=None)
    return p.parse_args(argv)


def build_overrides(args: argparse.Namespace) -> dict:
    o: dict = {}
    if args.network_profiles:
        o.setdefault("performance", {})["profiles"] = [
            s.strip() for s in args.network_profiles.split(",") if s.strip()]
    if args.iterations:
        o.setdefault("performance", {})["iterations"] = args.iterations
    if args.skip_performance:
        o.setdefault("performance", {})["enabled"] = False
    if args.headed:
        o.setdefault("browser", {})["headless"] = False
    if args.log_level:
        o.setdefault("logging", {})["level"] = args.log_level
    if args.output:
        o.setdefault("storage", {})["excel_path"] = str(
            Path(args.output) / "{assessment_id}" / "assessment_results.xlsx")
    return o


async def run_assessment(args: argparse.Namespace) -> int:
    settings = load_settings(args.config, args.policy, build_overrides(args))
    assessment_id = uuid.uuid4().hex[:16]
    artifact_dir = settings.artifact_dir(assessment_id)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    setup_logging(settings.logging.level, settings.log_path(assessment_id))

    parsed = urlparse(args.url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        log.error("invalid target URL: %r", args.url)
        return 2

    log.info("=" * 68)
    log.info("assessment %s starting", assessment_id)
    log.info("target      %s", args.url)
    log.info("mode        %s", settings.assessment.mode)
    log.info("artifacts   %s", artifact_dir)
    log.info("=" * 68)

    # --- LLM availability is resolved once, up front.
    provider = build_provider(settings.llm)
    llm_available = False
    if args.no_llm:
        log.warning("--no-llm: running deterministically; controls needing "
                    "interpretation will be reported UNKNOWN")
    else:
        try:
            llm_available, msg = await provider.health_check()
            log.info("LLM: %s", msg)
        except Exception as exc:                                # noqa: BLE001
            log.warning("LLM unavailable: %s", exc)
        if not llm_available and settings.llm.required:
            log.error("llm.required is true but no model is available")
            return 3

    rules_filter = ({f.strip().upper() for f in args.families.split(",")}
                    if args.families else None)

    budget = TrafficBudget(
        max_navigations=settings.assessment.max_navigation_count,
        max_pages=settings.assessment.max_pages,
        timeout_seconds=settings.assessment.timeout_seconds)

    # --- dry run: plan only, no browser.
    if args.dry_run:
        return await dry_run(settings, provider, llm_available, args.url,
                            rules_filter, budget)

    session = BrowserSession(settings, budget, artifact_dir)
    repository = build_repository(settings, assessment_id)
    workflow = build_workflow()

    state: AssessmentState = {
        "assessment_id": assessment_id,
        "target_url": args.url,
        "settings": settings,
        "status": AssessmentStatus.INITIALIZING,
        "started_at": time.monotonic(),
        "provider": provider,
        "llm_available": llm_available,
        "session": session,
        "budget": budget,
        "repository": repository,
        "errors": [],
    }

    await session.start()
    try:
        final = await workflow.ainvoke(state, {"recursion_limit": 50})
    finally:
        # Always close the browser, on every path.
        await session.close()

    if rules_filter:
        final["security_results"] = [r for r in final.get("security_results", [])
                                     if r.category in rules_filter]

    render_console_report(final, budget)

    status = final.get("status", AssessmentStatus.FAILED)
    return {AssessmentStatus.COMPLETED: 0, AssessmentStatus.PARTIAL: 0,
            AssessmentStatus.BLOCKED: 4}.get(status, 1)


async def dry_run(settings, provider, llm_available, url, rules_filter,
                  budget) -> int:
    """Print the plan without touching the target."""
    from app.agents.planner import Planner
    from app.tools.rules import load_rules

    families, rules = load_rules(settings.project_root, settings.rules.directory)
    if rules_filter:
        rules = [r for r in rules if r.family in rules_filter]

    planner = Planner(provider, settings, llm_available=llm_available)
    await planner.interpret_all(rules)
    plan = planner.build_plan(url, rules)

    print("\n" + "=" * 72)
    print("DRY RUN — no request was made to the target")
    print("=" * 72)
    print(f"target                 {url}")
    print(f"controls loaded        {len(rules)} from {len(families)} families")
    print(f"passive evidence route {len(plan.evaluable_rules)}")
    print(f"not testable at L1     {len(plan.not_testable_rules)}")
    print(f"collectors required    {', '.join(c.value for c in plan.required_collectors)}")
    print(f"\nPLANNED ACTIONS ({len(plan.actions)}) — this is the entire interaction budget:")
    for a in plan.actions:
        print(f"  - {a.kind:20} {a.reason}")
        if a.required_by:
            print(f"    {' ' * 20} required by: {', '.join(a.required_by[:8])}"
                  f"{' ...' if len(a.required_by) > 8 else ''}")
    print(f"\nESTIMATED TARGET TRAFFIC: {plan.estimated_requests} requests")
    print(f"  budget allows: {budget.max_navigations} navigations, "
          f"{budget.max_pages} pages")
    for note in plan.notes:
        print(f"\n  note: {note}")
    print("=" * 72 + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return asyncio.run(run_assessment(args))
    except KeyboardInterrupt:
        log.warning("interrupted by user")
        return 130


if __name__ == "__main__":
    sys.exit(main())
