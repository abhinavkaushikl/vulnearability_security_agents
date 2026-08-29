"""Auto-registration of every built-in tool into the global registry.

Import this module once at startup to populate the registry with all
available tools. The orchestrator then discovers them dynamically.

To add a new tool: either use @registry.tool(...) in any module, or add
a registration block here.
"""
from __future__ import annotations

from app.tools.registry import ToolCategory, registry


# ── NETWORK / OUT-OF-BAND COLLECTORS ─────────────────────────────────────

@registry.tool(
    name="collect_tls",
    category=ToolCategory.NETWORK,
    description="TLS handshake against the target. Returns protocol version, "
                "cipher suite, certificate chain, SAN, expiry, hostname match.",
    parameters={"hostname": "target hostname", "port": "TLS port (default 443)"},
    requires_network=True,
    collector_code="TLS",
    tags=["security", "tls", "certificate", "NET-02", "NET-04"],
)
async def _collect_tls(hostname: str, port: int = 443):
    from app.tools.network import collect_tls
    return await collect_tls(hostname, port)


@registry.tool(
    name="collect_dns",
    category=ToolCategory.NETWORK,
    description="DNS resolution: A, AAAA, CNAME, NS, MX, CAA records and DNSSEC. "
                "Resolved off-target — costs the site nothing.",
    parameters={"hostname": "target hostname"},
    requires_network=True,
    collector_code="DNS",
    tags=["security", "dns", "dnssec", "NET-05", "NET-06"],
)
async def _collect_dns(hostname: str):
    from app.tools.network import collect_dns
    return await collect_dns(hostname)


@registry.tool(
    name="collect_redirect_chain",
    category=ToolCategory.NETWORK,
    description="Follow HTTP to HTTPS redirect chain. Checks if plain HTTP "
                "redirects properly to HTTPS without leaking content.",
    parameters={"url": "target URL"},
    requires_network=True,
    collector_code="RDR",
    tags=["security", "https", "redirect", "NET-01"],
)
async def _collect_redirect_chain(url: str):
    from app.tools.network import collect_redirect_chain
    return await collect_redirect_chain(url)


@registry.tool(
    name="collect_well_known",
    category=ToolCategory.NETWORK,
    description="Fetch /.well-known/security.txt and /robots.txt. Two cheap GETs.",
    parameters={"base_url": "target base URL"},
    requires_network=True,
    collector_code="WK",
    tags=["security", "security-txt", "robots", "IR-05"],
)
async def _collect_well_known(base_url: str):
    from app.tools.network import collect_well_known
    return await collect_well_known(base_url)


@registry.tool(
    name="probe_error_page",
    category=ToolCategory.NETWORK,
    description="One benign 404 on a random path. Checks if the server leaks "
                "stack traces, internal paths, or version strings in error pages.",
    parameters={"base_url": "target base URL"},
    requires_network=True,
    collector_code="ERR",
    tags=["security", "information-disclosure", "WEB-10", "APP-07"],
)
async def _probe_error_page(base_url: str):
    from app.tools.network import probe_error_page
    return await probe_error_page(base_url)


# ── BROWSER / IN-PAGE COLLECTORS ─────────────────────────────────────────

@registry.tool(
    name="inspect_cookies",
    category=ToolCategory.BROWSER,
    description="Read all cookies with their security attributes (Secure, HttpOnly, "
                "SameSite, Domain, Path). Cookie VALUES are never stored.",
    parameters={"context": "browser context", "page_url": "current page URL"},
    requires_browser=True,
    collector_code="CK",
    tags=["security", "cookies", "WEB-05", "PRIV-06"],
)
async def _inspect_cookies(context, page_url: str):
    from app.tools.inspection import inspect_cookies
    return await inspect_cookies(context, page_url)


@registry.tool(
    name="inspect_storage",
    category=ToolCategory.BROWSER,
    description="Inventory localStorage and sessionStorage keys. Detects JWT-shaped "
                "and token-shaped values. Values are classified, never stored.",
    parameters={"page": "Playwright page"},
    requires_browser=True,
    collector_code="WS",
    tags=["security", "storage", "jwt", "WEB-06"],
)
async def _inspect_storage(page):
    from app.tools.inspection import inspect_storage
    return await inspect_storage(page)


@registry.tool(
    name="inspect_forms",
    category=ToolCategory.BROWSER,
    description="Inventory all forms: action, method, field names/types, password "
                "fields, unlabelled fields. No form is ever submitted.",
    parameters={"page": "Playwright page"},
    requires_browser=True,
    collector_code="FRM",
    tags=["security", "forms", "a11y", "PRIV-02", "A11Y-03"],
)
async def _inspect_forms(page):
    from app.tools.inspection import inspect_forms
    return await inspect_forms(page)


@registry.tool(
    name="inspect_scripts",
    category=ToolCategory.BROWSER,
    description="Inventory all script tags: src, inline, third-party, SRI integrity, "
                "crossorigin attribute.",
    parameters={"page": "Playwright page", "scope_host": "site's registrable host"},
    requires_browser=True,
    collector_code="JS",
    tags=["security", "scripts", "sri", "WEB-07"],
)
async def _inspect_scripts(page, scope_host: str):
    from app.tools.inspection import inspect_scripts
    return await inspect_scripts(page, scope_host)


@registry.tool(
    name="inspect_links",
    category=ToolCategory.BROWSER,
    description="Inventory all links on the page (up to 500). Links are recorded, never followed.",
    parameters={"page": "Playwright page"},
    requires_browser=True,
    collector_code="LNK",
    tags=["discovery", "links"],
)
async def _inspect_links(page):
    from app.tools.inspection import inspect_links
    return await inspect_links(page)


@registry.tool(
    name="collect_web_vitals",
    category=ToolCategory.BROWSER,
    description="Lab Core Web Vitals: LCP, CLS (INP not measurable without real "
                "user input). These are LAB measurements, not field data.",
    parameters={"page": "Playwright page"},
    requires_browser=True,
    collector_code="CWV",
    tags=["performance", "vitals", "lcp", "cls", "PERF-01"],
)
async def _collect_web_vitals(page):
    from app.tools.inspection import collect_web_vitals
    return await collect_web_vitals(page)


@registry.tool(
    name="collect_navigation_timing",
    category=ToolCategory.BROWSER,
    description="PerformanceNavigationTiming: DNS, TCP, TLS, TTFB, DOMContentLoaded, "
                "page load time, redirect count, transfer size.",
    parameters={"page": "Playwright page"},
    requires_browser=True,
    collector_code="TIM",
    tags=["performance", "timing", "PERF-02"],
)
async def _collect_navigation_timing(page):
    from app.tools.inspection import collect_navigation_timing
    return await collect_navigation_timing(page)


@registry.tool(
    name="scan_page_secrets",
    category=ToolCategory.BROWSER,
    description="Scan HTML and same-origin scripts for secrets: AWS keys, private keys, "
                "JWTs, Slack/GitHub/Stripe tokens, passwords, source maps. "
                "Matched values are NEVER stored — only kind and location.",
    parameters={"page": "Playwright page", "html": "page HTML", "scripts": "script records"},
    requires_browser=True,
    collector_code="JS",
    tags=["security", "secrets", "WEB-09"],
)
async def _scan_page_secrets(page, html: str, scripts):
    from app.tools.inspection import scan_page_secrets
    return await scan_page_secrets(page, html, scripts)


@registry.tool(
    name="collect_a11y",
    category=ToolCategory.BROWSER,
    description="Accessibility audit: structural heuristics (images missing alt, "
                "unlabelled inputs, landmarks, lang attribute) plus axe-core "
                "violations if vendored. Result is INFORMATIONAL — automated "
                "tooling covers a minority of WCAG 2.2.",
    parameters={"page": "Playwright page", "run_axe": "whether to run axe-core"},
    requires_browser=True,
    collector_code="A11",
    tags=["accessibility", "wcag", "A11Y-01", "A11Y-03"],
)
async def _collect_a11y(page, run_axe: bool = True):
    from app.tools.a11y import collect_a11y
    return await collect_a11y(page, run_axe=run_axe)


@registry.tool(
    name="capture_screenshot",
    category=ToolCategory.UTILITY,
    description="Capture a screenshot of the current page state.",
    parameters={"page": "Playwright page", "artifact_dir": "output directory",
                "name": "screenshot name", "full_page": "capture full page?"},
    requires_browser=True,
    collector_code="SHOT",
    tags=["evidence", "visual"],
)
async def _capture_screenshot(page, artifact_dir, name: str, full_page: bool = False):
    from pathlib import Path
    from app.tools.screenshots import capture_screenshot
    return await capture_screenshot(page, Path(artifact_dir), name, full_page=full_page)


# ── ANALYZER TOOLS ───────────────────────────────────────────────────────

@registry.tool(
    name="analyze_headers",
    category=ToolCategory.ANALYZER,
    description="Analyze response headers for security issues: missing CSP, HSTS, "
                "X-Content-Type-Options, Referrer-Policy, Permissions-Policy, "
                "frame-ancestors. Works on already-collected header data.",
    parameters={"headers": "dict of response headers"},
    tags=["security", "headers", "WEB-01", "WEB-02", "WEB-03", "WEB-04"],
)
async def _analyze_headers(headers: dict) -> dict:
    expected = [
        "content-security-policy", "strict-transport-security",
        "x-content-type-options", "x-frame-options", "referrer-policy",
        "permissions-policy", "cross-origin-opener-policy",
    ]
    present = {h: headers.get(h) for h in expected if headers.get(h)}
    missing = [h for h in expected if h not in headers]
    issues = []
    csp = headers.get("content-security-policy", "")
    if "'unsafe-inline'" in csp:
        issues.append("CSP contains 'unsafe-inline'")
    if "'unsafe-eval'" in csp:
        issues.append("CSP contains 'unsafe-eval'")
    hsts = headers.get("strict-transport-security", "")
    if hsts and "max-age=" in hsts:
        import re
        m = re.search(r"max-age=(\d+)", hsts)
        if m and int(m.group(1)) < 15768000:
            issues.append(f"HSTS max-age={m.group(1)} is below 6 months")
    return {"present": present, "missing": missing, "issues": issues}


@registry.tool(
    name="analyze_cookies_security",
    category=ToolCategory.ANALYZER,
    description="Analyze collected cookies for security flags: missing Secure, "
                "HttpOnly, SameSite. Identifies session/auth cookies by name pattern.",
    parameters={"cookies": "list of CookieRecord dicts"},
    tags=["security", "cookies", "WEB-05"],
)
async def _analyze_cookies_security(cookies: list[dict]) -> dict:
    session_patterns = ["sess", "sid", "auth", "token", "jwt", "login", "csrf"]
    issues = []
    for c in cookies:
        name_lower = c.get("name", "").lower()
        is_session = any(p in name_lower for p in session_patterns)
        if is_session:
            if not c.get("secure"):
                issues.append(f"session cookie '{c['name']}' missing Secure flag")
            if not c.get("http_only"):
                issues.append(f"session cookie '{c['name']}' missing HttpOnly flag")
            if c.get("same_site", "").lower() not in ("strict", "lax"):
                issues.append(f"session cookie '{c['name']}' has weak SameSite={c.get('same_site')}")
    return {"total_cookies": len(cookies), "issues": issues,
            "session_cookies_found": len([c for c in cookies
                                          if any(p in c.get("name", "").lower()
                                                 for p in session_patterns)])}


@registry.tool(
    name="analyze_mixed_content",
    category=ToolCategory.ANALYZER,
    description="Check for mixed content: HTTP subresources loaded on an HTTPS page.",
    parameters={"requests": "list of RequestRecord dicts", "page_is_https": "bool"},
    tags=["security", "mixed-content", "WEB-08"],
)
async def _analyze_mixed_content(requests: list[dict], page_is_https: bool) -> dict:
    if not page_is_https:
        return {"mixed_content": False, "note": "page itself is not HTTPS"}
    insecure = [r["url"] for r in requests
                if r.get("is_insecure") and not r.get("failed")]
    return {"mixed_content": bool(insecure), "insecure_urls": insecure[:20],
            "count": len(insecure)}


@registry.tool(
    name="analyze_third_party_scripts",
    category=ToolCategory.ANALYZER,
    description="Check third-party scripts for SRI (Subresource Integrity). "
                "Cross-origin scripts without integrity attributes are a supply-chain risk.",
    parameters={"scripts": "list of ScriptRecord dicts"},
    tags=["security", "sri", "supply-chain", "WEB-07"],
)
async def _analyze_third_party_scripts(scripts: list[dict]) -> dict:
    third_party = [s for s in scripts if s.get("is_third_party")]
    without_sri = [s["src"] for s in third_party if not s.get("has_integrity")]
    return {"third_party_count": len(third_party),
            "without_integrity": without_sri,
            "all_have_sri": len(without_sri) == 0}


# ── PERFORMANCE TOOLS ────────────────────────────────────────────────────

@registry.tool(
    name="measure_page_load",
    category=ToolCategory.PERFORMANCE,
    description="Measure one page load under a network profile (throttled). "
                "Returns timing, vitals, request counts.",
    parameters={"session": "BrowserSession", "context": "browser context",
                "url": "target URL", "profile": "NetworkProfile",
                "iteration": "iteration number", "assessment_id": "assessment ID",
                "scope_host": "site registrable host"},
    requires_browser=True,
    requires_network=True,
    tags=["performance", "timing", "PERF-01", "PERF-02"],
)
async def _measure_page_load(session, context, url, profile, iteration,
                              assessment_id, scope_host):
    from app.tools.performance import measure_page_load
    return await measure_page_load(
        session=session, context=context, url=url, profile=profile,
        iteration=iteration, assessment_id=assessment_id, scope_host=scope_host)


# ── UTILITY TOOLS ────────────────────────────────────────────────────────

@registry.tool(
    name="calculate_statistics",
    category=ToolCategory.UTILITY,
    description="Compute statistics (mean, median, p95, stddev) for a set of "
                "performance measurements. Pure Python, deterministic.",
    parameters={"measurements": "list of PerformanceMeasurement",
                "assessment_id": "assessment ID"},
    tags=["statistics", "performance"],
)
async def _calculate_statistics(measurements, assessment_id: str):
    from app.tools.statistics import summarise_measurements
    return summarise_measurements(measurements, assessment_id)


@registry.tool(
    name="evaluate_rule",
    category=ToolCategory.EVALUATOR,
    description="Evaluate a single security rule against collected evidence. "
                "Uses LLM for interpretation, with deterministic anti-fabrication "
                "validation on the result.",
    parameters={"rule": "SecurityRule", "bundle": "EvidenceBundle",
                "assessment_id": "assessment ID"},
    tags=["evaluation", "security"],
)
async def _evaluate_rule(rule, bundle, assessment_id, evaluator=None):
    if evaluator is None:
        raise ValueError("evaluator must be provided")
    return await evaluator.evaluate_rule(rule, bundle, assessment_id)


@registry.tool(
    name="load_rules",
    category=ToolCategory.UTILITY,
    description="Load all security rules from the Rules/ Markdown pack. "
                "Returns (families, flat_rules).",
    parameters={"root": "project root path", "directory": "rules directory name"},
    tags=["rules", "loading"],
)
async def _load_rules(root: str = ".", directory: str = "Rules"):
    from app.tools.rules import load_rules
    return load_rules(root, directory)


# ── INTERACTIVE BROWSER TESTS ───────────────────────────────────────────

@registry.tool(
    name="test_keyboard_navigation",
    category=ToolCategory.BROWSER,
    description="Press Tab 25 times, record which elements get focus, check "
                "for visible focus indicators and logical tab order. "
                "Tests keyboard accessibility without any mouse interaction.",
    parameters={"page": "Playwright page"},
    requires_browser=True,
    tags=["accessibility", "keyboard", "a11y", "A11Y-01", "A11Y-03"],
)
async def _test_keyboard_navigation(page):
    from app.tools.interactive import test_keyboard_navigation
    return await test_keyboard_navigation(page)


@registry.tool(
    name="test_focus_trap",
    category=ToolCategory.BROWSER,
    description="Detect keyboard focus traps — elements that capture Tab "
                "and prevent navigation. Tabs 40 times watching for stuck focus.",
    parameters={"page": "Playwright page"},
    requires_browser=True,
    tags=["accessibility", "focus-trap", "A11Y-06"],
)
async def _test_focus_trap(page):
    from app.tools.interactive import test_focus_trap
    return await test_focus_trap(page)


@registry.tool(
    name="test_clickjacking",
    category=ToolCategory.BROWSER,
    description="Test clickjacking resistance by attempting to load the target "
                "in an iframe. If the iframe loads, the site is frameable.",
    parameters={"context": "browser context", "target_url": "URL to test"},
    requires_browser=True,
    tags=["security", "clickjacking", "iframe", "WEB-04"],
)
async def _test_clickjacking(context, target_url: str):
    from app.tools.interactive import test_clickjacking_resistance
    return await test_clickjacking_resistance(context, target_url)


@registry.tool(
    name="test_debug_endpoints",
    category=ToolCategory.BROWSER,
    description="Probe common debug/admin/introspection paths (/admin, /debug, "
                "/graphql, /swagger, /actuator, /.env, etc.) with GET requests. "
                "Checks if they return 200 instead of 403/404.",
    parameters={"page": "Playwright page", "base_url": "target base URL",
                "budget": "TrafficBudget"},
    requires_browser=True,
    requires_network=True,
    tags=["security", "debug", "admin", "API-09"],
)
async def _test_debug_endpoints(page, base_url: str, budget):
    from app.tools.interactive import test_debug_endpoints
    return await test_debug_endpoints(page, base_url, budget)


@registry.tool(
    name="test_hover_behavior",
    category=ToolCategory.BROWSER,
    description="Hover over navigation elements and record what appears — "
                "dropdowns, tooltips, popups, DOM changes. Pure observation.",
    parameters={"page": "Playwright page"},
    requires_browser=True,
    tags=["behavior", "interaction", "navigation"],
)
async def _test_hover_behavior(page):
    from app.tools.interactive import test_hover_behavior
    return await test_hover_behavior(page)


@registry.tool(
    name="test_navigation_flow",
    category=ToolCategory.BROWSER,
    description="Navigate browse → product → observe cart button. Tests if "
                "the e-commerce flow EXISTS and is functional. Does NOT "
                "click add-to-cart or complete any purchase.",
    parameters={"page": "Playwright page", "base_url": "target URL",
                "budget": "TrafficBudget"},
    requires_browser=True,
    requires_network=True,
    tags=["e-commerce", "flow", "FLOW-01"],
)
async def _test_navigation_flow(page, base_url: str, budget):
    from app.tools.interactive import test_page_navigation_flow
    return await test_page_navigation_flow(page, base_url, budget)


@registry.tool(
    name="test_login_page",
    category=ToolCategory.BROWSER,
    description="Find and visit the login page, observe form structure: "
                "CSRF token, HTTPS submission, field types, autocomplete. "
                "Does NOT submit any credentials.",
    parameters={"page": "Playwright page", "base_url": "target URL",
                "budget": "TrafficBudget"},
    requires_browser=True,
    requires_network=True,
    tags=["security", "login", "IAM-03", "IAM-08"],
)
async def _test_login_page(page, base_url: str, budget):
    from app.tools.interactive import test_login_page_behavior
    return await test_login_page_behavior(page, base_url, budget)


@registry.tool(
    name="test_multi_page_headers",
    category=ToolCategory.BROWSER,
    description="Check security headers across 3-4 different pages on the site. "
                "Finds inconsistencies: headers present on homepage but missing "
                "on subpages, or vice versa.",
    parameters={"page": "Playwright page", "base_url": "target URL",
                "budget": "TrafficBudget"},
    requires_browser=True,
    requires_network=True,
    tags=["security", "headers", "NET-01", "NET-03", "WEB-02", "WEB-03"],
)
async def _test_multi_page_headers(page, base_url: str, budget):
    from app.tools.interactive import test_response_headers_multi_page
    return await test_response_headers_multi_page(page, base_url, budget)


@registry.tool(
    name="run_all_interactive_tests",
    category=ToolCategory.BROWSER,
    description="Run ALL interactive browser tests: keyboard navigation, "
                "focus trap detection, clickjacking, debug endpoints, hover "
                "behavior, navigation flow, login page observation, and "
                "multi-page header checks. Comprehensive interactive audit.",
    parameters={"context": "browser context", "page": "Playwright page",
                "base_url": "target URL", "budget": "TrafficBudget",
                "tests": "optional list of specific test names to run"},
    requires_browser=True,
    requires_network=True,
    tags=["interactive", "comprehensive", "A11Y-01", "WEB-04", "API-09",
          "FLOW-01", "IAM-03"],
)
async def _run_all_interactive(context, page, base_url: str, budget,
                                tests=None):
    from app.tools.interactive import run_interactive_tests
    return await run_interactive_tests(context, page, base_url, budget,
                                       tests=tests)


def get_registry() -> "ToolRegistry":
    """Return the populated global registry."""
    from app.tools.registry import registry
    return registry
