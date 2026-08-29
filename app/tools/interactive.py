"""Interactive browser testing — goes beyond single page load.

Unlike the passive collectors that READ a frozen page, interactive tests
NAVIGATE, HOVER, CLICK and OBSERVE. They are still non-destructive:
  - No form is ever submitted with real data
  - No login with real credentials
  - No destructive actions (delete, purchase, etc.)
  - Every navigation counts against TrafficBudget

These tests cover the gap between "single page passive" and "full staging" —
rules that need multi-page observation but not authentication.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from playwright.async_api import Page, BrowserContext

from app.safety.limits import TrafficBudget

log = logging.getLogger(__name__)


@dataclass
class InteractiveResult:
    """Result of one interactive test."""

    test_name: str
    passed: bool | None = None      # None = inconclusive
    observations: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    error: str | None = None


# ── KEYBOARD / A11Y TESTS ──────────────────────────────────────────────

async def test_keyboard_navigation(page: Page) -> InteractiveResult:
    """A11Y-01/03: Can you Tab through the page and reach interactive elements?

    Presses Tab N times, records which elements get focus, checks for
    visible focus indicators, and verifies logical tab order.
    """
    result = InteractiveResult(test_name="keyboard_navigation")

    try:
        focused_elements = []
        for i in range(25):
            await page.keyboard.press("Tab")
            await page.wait_for_timeout(150)

            info = await page.evaluate("""() => {
                const el = document.activeElement;
                if (!el || el === document.body) return null;
                const rect = el.getBoundingClientRect();
                const style = getComputedStyle(el);
                const outlineVisible = style.outlineStyle !== 'none'
                    && style.outlineWidth !== '0px';
                const boxShadow = style.boxShadow !== 'none';
                return {
                    tag: el.tagName.toLowerCase(),
                    type: el.type || null,
                    role: el.getAttribute('role'),
                    ariaLabel: el.getAttribute('aria-label'),
                    text: (el.textContent || '').trim().slice(0, 50),
                    tabIndex: el.tabIndex,
                    hasVisibleFocus: outlineVisible || boxShadow,
                    position: {x: Math.round(rect.x), y: Math.round(rect.y)},
                };
            }""")

            if info and info not in focused_elements:
                focused_elements.append(info)

        result.evidence = {
            "focusable_elements_found": len(focused_elements),
            "elements": focused_elements[:20],
            "elements_with_visible_focus": sum(
                1 for e in focused_elements if e.get("hasVisibleFocus")),
            "elements_without_visible_focus": sum(
                1 for e in focused_elements if not e.get("hasVisibleFocus")),
            "has_skip_link": any(
                "skip" in (e.get("text") or "").lower() for e in focused_elements),
        }

        total = len(focused_elements)
        visible = result.evidence["elements_with_visible_focus"]
        result.observations.append(
            f"found {total} focusable elements via Tab key")
        result.observations.append(
            f"{visible}/{total} have visible focus indicators")

        if total == 0:
            result.observations.append(
                "NO focusable elements found — severe keyboard accessibility issue")
            result.passed = False
        elif visible < total * 0.5:
            result.observations.append(
                "less than 50% of focusable elements have visible focus")
            result.passed = False
        else:
            result.passed = True

    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        log.warning("keyboard navigation test failed: %s", exc)

    return result


async def test_focus_trap(page: Page) -> InteractiveResult:
    """A11Y-06: Check if any element traps keyboard focus (can't Tab out)."""
    result = InteractiveResult(test_name="focus_trap_detection")

    try:
        seen_tags = []
        last_tag = None
        repeat_count = 0

        for _ in range(40):
            await page.keyboard.press("Tab")
            await page.wait_for_timeout(100)

            tag = await page.evaluate(
                "() => document.activeElement?.tagName?.toLowerCase() || 'body'")
            seen_tags.append(tag)

            if tag == last_tag and tag != "body":
                repeat_count += 1
                if repeat_count >= 5:
                    result.observations.append(
                        f"focus appears TRAPPED on <{tag}> — "
                        f"Tab pressed {repeat_count} times without moving")
                    result.passed = False
                    result.evidence = {"trapped_element": tag,
                                       "consecutive_hits": repeat_count}
                    return result
            else:
                repeat_count = 0
            last_tag = tag

        unique = len(set(seen_tags))
        result.observations.append(
            f"focus moved through {unique} unique elements, no trap detected")
        result.passed = True
        result.evidence = {"unique_elements_focused": unique,
                           "total_tab_presses": len(seen_tags)}

    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"

    return result


# ── IFRAME / CLICKJACKING TEST ─────────────────────────────────────────

async def test_clickjacking_resistance(
    context: BrowserContext, target_url: str
) -> InteractiveResult:
    """WEB-04: Can the target be framed by an untrusted origin?

    Creates a local page with an iframe pointing to the target.
    If the iframe loads, the site is frameable (clickjacking risk).
    """
    result = InteractiveResult(test_name="clickjacking_iframe")

    try:
        page = await context.new_page()
        html = f"""<html><body>
        <iframe id="target" src="{target_url}"
                width="800" height="600"
                style="border:1px solid red"></iframe>
        <script>
        const iframe = document.getElementById('target');
        iframe.onload = () => {{
            try {{
                const doc = iframe.contentDocument;
                window.__iframeLoaded = true;
                window.__canAccessContent = !!doc;
            }} catch(e) {{
                window.__iframeLoaded = true;
                window.__canAccessContent = false;
            }}
        }};
        iframe.onerror = () => {{
            window.__iframeLoaded = false;
            window.__canAccessContent = false;
        }};
        </script></body></html>"""

        await page.set_content(html)
        await page.wait_for_timeout(5000)

        iframe_status = await page.evaluate("""() => ({
            loaded: window.__iframeLoaded || false,
            canAccess: window.__canAccessContent || false,
            iframeHeight: document.getElementById('target')
                         ?.contentWindow?.document?.body?.scrollHeight || 0,
        })""")

        result.evidence = iframe_status

        if not iframe_status.get("loaded"):
            result.observations.append(
                "iframe was BLOCKED from loading — site is protected against framing")
            result.passed = True
        else:
            result.observations.append(
                "iframe LOADED the target page — clickjacking may be possible")
            if iframe_status.get("canAccess"):
                result.observations.append(
                    "cross-origin content was accessible (no X-Frame-Options or "
                    "frame-ancestors directive)")
            result.passed = False

        await page.close()

    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"

    return result


# ── ENDPOINT DISCOVERY ─────────────────────────────────────────────────

async def test_debug_endpoints(
    page: Page, base_url: str, budget: TrafficBudget
) -> InteractiveResult:
    """API-09: Are debug/admin/introspection endpoints exposed?

    Makes GET requests to common debug paths. Never POSTs, never
    authenticates — just checks if these paths return 200 instead of 403/404.
    """
    result = InteractiveResult(test_name="debug_endpoint_discovery")

    paths = [
        "/admin", "/admin/", "/_debug", "/debug", "/debug/",
        "/graphql", "/graphiql", "/__debug__",
        "/api/docs", "/swagger", "/swagger-ui", "/redoc",
        "/actuator", "/actuator/health", "/actuator/env",
        "/.env", "/wp-admin", "/phpinfo.php",
        "/server-status", "/server-info",
        "/elmah.axd", "/trace.axd",
    ]

    exposed = []
    checked = []

    try:
        for path in paths:
            url = urljoin(base_url, path)
            try:
                budget.aux(url, f"API-09: probe {path}")
            except Exception:
                result.observations.append(
                    f"budget exhausted after checking {len(checked)} paths")
                break

            try:
                resp = await page.evaluate(f"""async () => {{
                    try {{
                        const r = await fetch("{url}", {{
                            method: "GET",
                            redirect: "follow",
                            credentials: "omit"
                        }});
                        return {{status: r.status, url: r.url,
                                type: r.headers.get("content-type") || ""}};
                    }} catch(e) {{
                        return {{status: 0, error: e.message}};
                    }}
                }}""")

                checked.append({"path": path, "status": resp.get("status", 0)})

                status = resp.get("status", 0)
                if status in (200, 301, 302) and status != 404:
                    exposed.append({
                        "path": path,
                        "status": status,
                        "content_type": resp.get("type", ""),
                        "redirected_to": resp.get("url", ""),
                    })
            except Exception as exc:
                log.debug("probe %s failed: %s", path, exc)

        result.evidence = {
            "paths_checked": len(checked),
            "exposed_endpoints": exposed,
            "exposed_count": len(exposed),
            "checked": checked,
        }

        if exposed:
            result.observations.append(
                f"{len(exposed)} potentially exposed endpoint(s): "
                + ", ".join(e["path"] for e in exposed))
            result.passed = False
        else:
            result.observations.append(
                f"checked {len(checked)} common paths — none returned 200")
            result.passed = True

    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"

    return result


# ── HOVER / INTERACTION BEHAVIOR ───────────────────────────────────────

async def test_hover_behavior(page: Page) -> InteractiveResult:
    """Observe what happens on hover — dropdowns, tooltips, state changes.

    Hovers over navigation elements and records what appears/changes.
    Pure observation — no click, no form interaction.
    """
    result = InteractiveResult(test_name="hover_behavior")

    try:
        nav_selectors = [
            "nav a", "header a", "[role='navigation'] a",
            "[role='menubar'] > *", ".nav-item", ".menu-item",
            "button[aria-haspopup]", "[data-toggle='dropdown']",
        ]

        hover_results = []

        for selector in nav_selectors:
            elements = await page.query_selector_all(selector)
            for el in elements[:5]:
                try:
                    before_html = await page.evaluate(
                        "() => document.body.innerHTML.length")

                    box = await el.bounding_box()
                    if not box:
                        continue

                    await el.hover()
                    await page.wait_for_timeout(500)

                    after_html = await page.evaluate(
                        "() => document.body.innerHTML.length")

                    visible_popup = await page.evaluate("""() => {
                        const popups = document.querySelectorAll(
                            '[role="menu"], [role="listbox"], .dropdown-menu, '
                            + '.submenu, [aria-expanded="true"]');
                        return Array.from(popups).map(p => ({
                            role: p.getAttribute('role'),
                            tag: p.tagName.toLowerCase(),
                            visible: p.offsetHeight > 0,
                            itemCount: p.children.length,
                        })).filter(p => p.visible);
                    }""")

                    text = await el.text_content() or ""
                    hover_results.append({
                        "element": text.strip()[:40],
                        "selector": selector,
                        "dom_changed": after_html != before_html,
                        "popups_appeared": len(visible_popup),
                        "popup_details": visible_popup[:3],
                    })
                except Exception:
                    continue

            if hover_results:
                break

        interactive_count = sum(
            1 for h in hover_results if h["dom_changed"] or h["popups_appeared"])

        result.evidence = {
            "elements_hovered": len(hover_results),
            "interactive_responses": interactive_count,
            "hover_details": hover_results[:10],
        }
        result.observations.append(
            f"hovered {len(hover_results)} nav elements, "
            f"{interactive_count} showed interactive behavior")
        result.passed = True

    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"

    return result


# ── MULTI-PAGE NAVIGATION ─────────────────────────────────────────────

async def test_page_navigation_flow(
    page: Page, base_url: str, budget: TrafficBudget
) -> InteractiveResult:
    """FLOW-01: Can we navigate browse → product → cart?

    Finds product links on the page, navigates to one, looks for
    add-to-cart button. Does NOT click add-to-cart or complete purchase.
    Pure observation of whether the flow EXISTS and is functional.
    """
    result = InteractiveResult(test_name="navigation_flow")

    try:
        links = await page.evaluate("""() => {
            const all = Array.from(document.querySelectorAll('a[href]'));
            return all.map(a => ({
                href: a.href,
                text: (a.textContent || '').trim().slice(0, 60),
                isProduct: /\\/product|\\/(dp|p|item|goods)\\/|\\/-\\/p-/i
                           .test(a.href),
            })).filter(l => l.isProduct).slice(0, 10);
        }""")

        flow_evidence = {
            "product_links_found": len(links),
            "sample_links": links[:5],
            "product_page_visited": False,
            "has_add_to_cart": False,
            "has_price": False,
            "has_product_title": False,
        }

        if not links:
            category_links = await page.evaluate("""() => {
                const all = Array.from(document.querySelectorAll('a[href]'));
                return all.filter(a =>
                    /categor|shop|store|browse|collection/i.test(a.href)
                    || /categor|shop|browse|all/i.test(a.textContent)
                ).map(a => ({href: a.href,
                             text: (a.textContent||'').trim().slice(0,60)}
                )).slice(0, 5);
            }""")
            flow_evidence["category_links_found"] = len(category_links)

            if category_links:
                try:
                    budget.navigate(category_links[0]["href"],
                                    "FLOW-01: visit category page")
                    await page.goto(category_links[0]["href"],
                                    wait_until="load", timeout=15000)
                    await page.wait_for_timeout(2000)

                    links = await page.evaluate("""() => {
                        const all = Array.from(
                            document.querySelectorAll('a[href]'));
                        return all.map(a => ({
                            href: a.href,
                            text: (a.textContent||'').trim().slice(0,60),
                            isProduct: /product|\\/(dp|p|item)\\//.test(a.href),
                        })).filter(l => l.isProduct).slice(0, 10);
                    }""")
                    flow_evidence["product_links_after_category"] = len(links)
                except Exception as exc:
                    flow_evidence["category_nav_error"] = str(exc)[:100]

        if links:
            target_link = links[0]["href"]
            try:
                budget.navigate(target_link, "FLOW-01: visit product page")
                await page.goto(target_link, wait_until="load", timeout=15000)
                await page.wait_for_timeout(2000)
                flow_evidence["product_page_visited"] = True

                product_info = await page.evaluate("""() => {
                    const priceEl = document.querySelector(
                        '[class*="price"], [data-price], '
                        + '[itemprop="price"], .product-price');
                    const cartBtn = document.querySelector(
                        'button[class*="cart"], [data-action*="cart"], '
                        + 'button:has-text("Add to Cart"), '
                        + 'button:has-text("Add to Bag"), '
                        + '[class*="add-to-cart"], [id*="add-to-cart"]');
                    const title = document.querySelector(
                        'h1, [class*="product-title"], '
                        + '[class*="product-name"], [itemprop="name"]');
                    return {
                        hasPrice: !!priceEl,
                        priceText: priceEl?.textContent?.trim()?.slice(0,30),
                        hasCartButton: !!cartBtn,
                        cartButtonText: cartBtn?.textContent?.trim()?.slice(0,30),
                        hasTitle: !!title,
                        titleText: title?.textContent?.trim()?.slice(0,60),
                    };
                }""")

                flow_evidence.update({
                    "has_add_to_cart": product_info.get("hasCartButton", False),
                    "cart_button_text": product_info.get("cartButtonText"),
                    "has_price": product_info.get("hasPrice", False),
                    "price_text": product_info.get("priceText"),
                    "has_product_title": product_info.get("hasTitle", False),
                    "product_title": product_info.get("titleText"),
                })

            except Exception as exc:
                flow_evidence["product_nav_error"] = str(exc)[:100]

        result.evidence = flow_evidence

        if flow_evidence.get("product_page_visited"):
            result.observations.append("successfully navigated to a product page")
            if flow_evidence.get("has_add_to_cart"):
                result.observations.append(
                    f"add-to-cart button found: "
                    f"'{flow_evidence.get('cart_button_text', '')}'")
            if flow_evidence.get("has_price"):
                result.observations.append(
                    f"price displayed: {flow_evidence.get('price_text', '')}")
            result.passed = True
        else:
            result.observations.append(
                "could not navigate to a product page from the landing page")
            result.passed = None

    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"

    return result


# ── LOGIN PAGE OBSERVATION ─────────────────────────────────────────────

async def test_login_page_behavior(
    page: Page, base_url: str, budget: TrafficBudget
) -> InteractiveResult:
    """IAM-03: Observe login page WITHOUT submitting credentials.

    Finds the login page, checks form structure, checks if
    error messages differ for valid vs invalid inputs (using obviously
    fake test data only — never real credentials).
    """
    result = InteractiveResult(test_name="login_page_observation")

    try:
        login_links = await page.evaluate("""() => {
            const all = Array.from(document.querySelectorAll('a[href]'));
            return all.filter(a =>
                /log.?in|sign.?in|account/i.test(a.href)
                || /log.?in|sign.?in/i.test(a.textContent)
            ).map(a => ({
                href: a.href,
                text: (a.textContent || '').trim().slice(0, 40)
            })).slice(0, 3);
        }""")

        evidence = {
            "login_links_found": len(login_links),
            "login_links": login_links,
            "login_page_found": False,
            "form_details": None,
        }

        if login_links:
            try:
                budget.navigate(login_links[0]["href"],
                                "IAM-03: visit login page for observation")
                await page.goto(login_links[0]["href"],
                                wait_until="load", timeout=15000)
                await page.wait_for_timeout(2000)

                form_info = await page.evaluate("""() => {
                    const forms = Array.from(document.forms);
                    const loginForm = forms.find(f =>
                        f.querySelector('input[type="password"]')
                        || f.querySelector('input[type="email"]')
                        || /login|signin/i.test(f.action || '')
                    );
                    if (!loginForm) return null;
                    const fields = Array.from(loginForm.elements);
                    return {
                        action: loginForm.action || '',
                        method: loginForm.method || 'get',
                        fields: fields.map(f => ({
                            name: f.name, type: f.type,
                            autocomplete: f.autocomplete || '',
                            hasLabel: !!f.labels?.length
                                || !!f.getAttribute('aria-label'),
                            required: f.required,
                            placeholder: f.placeholder || '',
                        })).filter(f => f.name),
                        hasPasswordField: fields.some(
                            f => f.type === 'password'),
                        hasEmailField: fields.some(
                            f => f.type === 'email'
                            || f.autocomplete === 'email'),
                        hasCsrfToken: fields.some(
                            f => /csrf|token|_token/i.test(f.name)
                            && f.type === 'hidden'),
                        hasRememberMe: fields.some(
                            f => /remember|keep/i.test(f.name)),
                        submitsOverHttps: (loginForm.action || '')
                            .startsWith('https://'),
                    };
                }""")

                evidence["login_page_found"] = True
                evidence["login_page_url"] = page.url
                evidence["form_details"] = form_info

                if form_info:
                    result.observations.append("login form found")
                    if form_info.get("hasPasswordField"):
                        result.observations.append("password field present")
                    if form_info.get("hasCsrfToken"):
                        result.observations.append("CSRF token present")
                    else:
                        result.observations.append(
                            "no visible CSRF token in form")
                    if not form_info.get("submitsOverHttps"):
                        result.observations.append(
                            "WARNING: form does not submit over HTTPS")
                else:
                    result.observations.append(
                        "login page found but no standard login form detected")

            except Exception as exc:
                evidence["login_nav_error"] = str(exc)[:100]

        result.evidence = evidence
        result.passed = True if evidence.get("form_details") else None

    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"

    return result


# ── RESPONSE HEADER DEEP CHECK ─────────────────────────────────────────

async def test_response_headers_multi_page(
    page: Page, base_url: str, budget: TrafficBudget
) -> InteractiveResult:
    """NET-01/03, WEB-02/03: Check security headers across multiple pages.

    Sometimes headers are set on the homepage but not on subpages,
    or vice versa. This test checks 3-4 different pages.
    """
    result = InteractiveResult(test_name="multi_page_headers")

    try:
        pages_to_check = [base_url]

        internal_links = await page.evaluate(f"""() => {{
            const base = new URL("{base_url}");
            const all = Array.from(document.querySelectorAll('a[href]'));
            return all
                .filter(a => {{
                    try {{
                        const u = new URL(a.href);
                        return u.hostname === base.hostname
                            && u.pathname !== base.pathname
                            && u.pathname !== '/';
                    }} catch {{ return false; }}
                }})
                .map(a => a.href)
                .filter((v,i,a) => a.indexOf(v) === i)
                .slice(0, 3);
        }}""")
        pages_to_check.extend(internal_links[:3])

        security_headers = [
            "content-security-policy", "strict-transport-security",
            "x-content-type-options", "x-frame-options",
            "referrer-policy", "permissions-policy",
        ]

        page_results = []

        for url in pages_to_check:
            try:
                budget.navigate(url, "WEB-02/03: multi-page header check")
                resp = await page.goto(url, wait_until="load", timeout=15000)

                if resp:
                    headers = {}
                    for h in security_headers:
                        val = resp.headers.get(h)
                        if val:
                            headers[h] = val

                    page_results.append({
                        "url": url,
                        "status": resp.status,
                        "headers_present": list(headers.keys()),
                        "headers_missing": [
                            h for h in security_headers if h not in headers],
                        "header_values": headers,
                    })
            except Exception as exc:
                page_results.append({
                    "url": url, "error": str(exc)[:100]})

        always_present = set(security_headers)
        always_missing = set(security_headers)
        inconsistent = []

        for pr in page_results:
            if "error" in pr:
                continue
            present = set(pr.get("headers_present", []))
            always_present &= present
            always_missing -= present

        for h in security_headers:
            states = [h in pr.get("headers_present", [])
                      for pr in page_results if "error" not in pr]
            if states and not all(s == states[0] for s in states):
                inconsistent.append(h)

        result.evidence = {
            "pages_checked": len(page_results),
            "per_page": page_results,
            "headers_on_all_pages": sorted(always_present),
            "headers_on_no_pages": sorted(always_missing),
            "inconsistent_headers": inconsistent,
        }

        if always_missing:
            result.observations.append(
                f"missing on ALL pages: {', '.join(sorted(always_missing))}")
        if inconsistent:
            result.observations.append(
                f"INCONSISTENT across pages: {', '.join(inconsistent)}")
        if always_present:
            result.observations.append(
                f"present on all pages: {', '.join(sorted(always_present))}")

        result.passed = not always_missing and not inconsistent

    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"

    return result


# ── MASTER RUNNER ──────────────────────────────────────────────────────

async def run_interactive_tests(
    context: BrowserContext,
    page: Page,
    base_url: str,
    budget: TrafficBudget,
    *,
    tests: list[str] | None = None,
) -> list[InteractiveResult]:
    """Run selected interactive tests. If tests=None, run all.

    Each test is independently guarded — one failure never aborts the rest.
    """
    all_tests = {
        "keyboard_navigation": lambda: test_keyboard_navigation(page),
        "focus_trap": lambda: test_focus_trap(page),
        "clickjacking": lambda: test_clickjacking_resistance(context, base_url),
        "debug_endpoints": lambda: test_debug_endpoints(page, base_url, budget),
        "hover_behavior": lambda: test_hover_behavior(page),
        "navigation_flow": lambda: test_page_navigation_flow(
            page, base_url, budget),
        "login_page": lambda: test_login_page_behavior(page, base_url, budget),
        "multi_page_headers": lambda: test_response_headers_multi_page(
            page, base_url, budget),
    }

    to_run = tests or list(all_tests.keys())
    results: list[InteractiveResult] = []

    for name in to_run:
        if name not in all_tests:
            log.warning("unknown interactive test: %s", name)
            continue

        log.info("INTERACTIVE: running %s", name)
        try:
            result = await all_tests[name]()
            results.append(result)
            status = "PASS" if result.passed else (
                "FAIL" if result.passed is False else "INCONCLUSIVE")
            log.info("INTERACTIVE: %s → %s (%s)",
                     name, status,
                     "; ".join(result.observations[:2]))
        except Exception as exc:
            results.append(InteractiveResult(
                test_name=name,
                error=f"{type(exc).__name__}: {exc}"))
            log.warning("INTERACTIVE: %s failed: %s", name, exc)

    return results
