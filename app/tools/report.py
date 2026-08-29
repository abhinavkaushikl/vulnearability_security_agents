"""ReportTool — console rendering.

Leads with COVERAGE, not a score. A single site-wide number over a pack that
is 71% organizational evidence would be actively misleading; PCI-10 says so
explicitly. The reader sees what was decided and what was never reachable.
"""
from __future__ import annotations

from app.models.assessment import AssessmentStatus
from app.models.results import NativeResult

_BAR = "=" * 78


def _fmt(v, nd=1):
    return f"{v:.{nd}f}" if isinstance(v, (int, float)) else "-"


def render_console_report(state: dict, budget) -> None:
    tally = state.get("tally")
    results = state.get("security_results", [])
    status: AssessmentStatus = state.get("status", AssessmentStatus.FAILED)

    print("\n" + _BAR)
    print(f"  ASSESSMENT REPORT — {state.get('assessment_id', '?')}")
    print(_BAR)
    print(f"  Website   {state.get('target_url')}")
    print(f"  Status    {status.value}")
    if reason := state.get("anti_bot"):
        if reason.detected:
            print(f"  Blocked   {reason.kind}: {reason.detail}")

    if tally:
        print(f"\n  SECURITY SUMMARY")
        print(f"    Total controls   {tally.total}")
        print(f"    YES              {tally.yes}")
        print(f"    NO               {tally.no}")
        print(f"    NOT_APPLICABLE   {tally.not_applicable}")
        print(f"    UNKNOWN          {tally.unknown}")
        print(f"\n    rule-pack native: {tally.native_pass} PASS, "
              f"{tally.native_fail} FAIL, {tally.native_warn} WARN, "
              f"{tally.native_informational} INFORMATIONAL, "
              f"{tally.native_not_testable} NOT_TESTABLE, {tally.native_na} N/A")
        print(f"    coverage: a verdict was reached for {tally.decided} of "
              f"{tally.total} controls ({tally.coverage_pct}%)")

    decided = [r for r in results
               if r.native_result in (NativeResult.PASS, NativeResult.FAIL,
                                      NativeResult.WARN,
                                      NativeResult.INFORMATIONAL)]
    if decided:
        print(f"\n  EVALUATED CONTROLS ({len(decided)})")
        print(f"    {'Rule':<10} {'Sev':<9} {'Result':<14} Evidence")
        print(f"    {'-'*10} {'-'*9} {'-'*14} {'-'*36}")
        order = {NativeResult.FAIL: 0, NativeResult.WARN: 1,
                 NativeResult.PASS: 2, NativeResult.INFORMATIONAL: 3}
        for r in sorted(decided, key=lambda x: (order.get(x.native_result, 4),
                                                -x.severity.rank)):
            ev = (r.evidence or "")[:70].replace("\n", " ")
            print(f"    {r.rule_id:<10} {r.severity.value:<9} "
                  f"{r.native_result.value:<14} {ev}")

    coverage = state.get("family_coverage") or {}
    if coverage:
        print(f"\n  COVERAGE BY FAMILY")
        print(f"    {'Family':<8} {'Decided':>9} {'Pass':>6} {'Fail':>6} "
              f"{'NotTest':>8} {'Reach':>7}")
        for fam, c in sorted(coverage.items(),
                             key=lambda kv: -kv[1]["coverage_pct"]):
            print(f"    {fam:<8} {c['decided']:>4}/{c['total']:<4} "
                  f"{c['passed']:>6} {c['failed']:>6} {c['not_testable']:>8} "
                  f"{c['coverage_pct']:>6}%")

    stats = state.get("performance_stats") or []
    if stats:
        by = {}
        for s in stats:
            by.setdefault(s.network_profile, {})[s.metric] = s
        print(f"\n  PERFORMANCE (lab measurements)")
        print(f"    {'Network':<9} {'AvgLoad':>10} {'Median':>10} {'P95':>10} "
              f"{'TTFB':>10} {'n':>3}")
        for prof, metrics in by.items():
            load = metrics.get("page_load_time")
            ttfb = metrics.get("ttfb")
            print(f"    {prof:<9} {_fmt(load.mean if load else None):>10} "
                  f"{_fmt(load.median if load else None):>10} "
                  f"{_fmt(load.p95 if load else None):>10} "
                  f"{_fmt(ttfb.mean if ttfb else None):>10} "
                  f"{load.n if load else 0:>3}")
        for o in state.get("profile_outcomes", []):
            if o.note:
                print(f"      {o.name}: {o.status.value} — {o.note}")

    if summary := state.get("summary_text"):
        print(f"\n  SUMMARY")
        for line in _wrap(summary, 72):
            print(f"    {line}")

    errors = state.get("errors") or []
    if errors:
        print(f"\n  ERRORS ({len(errors)}) — recorded per component, non-fatal")
        for e in errors[:10]:
            print(f"    {e.component}: {e.message[:80]}")

    print(f"\n  TRAFFIC   {budget.navigations} navigations, "
          f"{budget.aux_requests} auxiliary requests "
          f"({budget.total_requests} total) in {budget.elapsed:.1f}s")
    if path := state.get("report_path"):
        print(f"  REPORT    {path}")
    print(_BAR + "\n")


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
    return lines
