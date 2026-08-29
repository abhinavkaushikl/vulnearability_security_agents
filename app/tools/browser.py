"""BrowserNavigationTool — the controlled Playwright session.

This is the ONLY module that drives a browser. The LLM never receives a page
handle; it plans and interprets, and this executes. Every navigation is
attributed to a control through TrafficBudget.

Behaviour is restrained, not evasive: a normal user agent, a normal viewport,
no randomised mouse paths, no stealth patches. The goal is a small legible
footprint, never defeating bot detection.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from playwright.async_api import (Browser, BrowserContext, Page, Playwright,
                                  async_playwright)

from app.config.settings import Settings
from app.safety.limits import TrafficBudget

log = logging.getLogger(__name__)


class BrowserSession:
    """One browser process for one assessment.

    Context model:
      * ONE discovery context, never cleared mid-run — clearing it would
        destroy the session state WEB-05 and IAM-08 need to observe.
      * ONE fresh context per performance profile — a warm cache would make
        the 3G numbers fiction.
      * Everything closed on exit, on every path.
    """

    def __init__(self, settings: Settings, budget: TrafficBudget,
                 artifact_dir: Path):
        self.settings = settings
        self.budget = budget
        self.artifact_dir = artifact_dir
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._contexts: list[BrowserContext] = []
        self.browser_version = ""

    async def start(self) -> None:
        self._pw = await async_playwright().start()
        launcher = getattr(self._pw, self.settings.browser.type)
        self._browser = await launcher.launch(
            headless=self.settings.browser.headless,
            args=["--disable-blink-features=AutomationControlled"]
            if self.settings.browser.type == "chromium" else [],
        )
        self.browser_version = f"{self.settings.browser.type} {self._browser.version}"
        log.info("browser started: %s", self.browser_version)

    async def close(self) -> None:
        """Close everything. Safe to call twice; never raises."""
        for ctx in self._contexts:
            try:
                await ctx.close()
            except Exception:                                   # noqa: BLE001
                pass
        self._contexts.clear()
        for obj, name in ((self._browser, "browser"), (self._pw, "playwright")):
            if obj is None:
                continue
            try:
                await (obj.close() if name == "browser" else obj.stop())
            except Exception:                                   # noqa: BLE001
                pass
        self._browser = self._pw = None
        log.info("browser closed")

    async def new_context(self, *, label: str) -> BrowserContext:
        """A clean, isolated context. No storage state is ever carried in."""
        if self._browser is None:
            raise RuntimeError("browser not started")
        b = self.settings.browser
        ctx = await self._browser.new_context(
            viewport={"width": b.viewport.width, "height": b.viewport.height},
            locale=b.locale,
            ignore_https_errors=b.ignore_https_errors,
            # No custom UA: we identify as a normal Chromium, and do not
            # attempt to look like anything we are not.
        )
        ctx.set_default_timeout(b.timeout_ms)
        ctx.set_default_navigation_timeout(b.navigation_timeout_ms)
        self._contexts.append(ctx)
        log.debug("context created: %s", label)
        return ctx

    async def close_context(self, ctx: BrowserContext) -> None:
        try:
            await ctx.close()
        except Exception:                                       # noqa: BLE001
            pass
        if ctx in self._contexts:
            self._contexts.remove(ctx)

    @asynccontextmanager
    async def context(self, *, label: str):
        ctx = await self.new_context(label=label)
        try:
            yield ctx
        finally:
            await self.close_context(ctx)

    async def open_page(self, ctx: BrowserContext) -> Page:
        self.budget.open_page()
        return await ctx.new_page()

    async def navigate(self, page: Page, url: str, *, reason: str,
                       wait_until: str = "load"):
        """Navigate, counting the request against the budget.

        `reason` names the control that needs this. It is mandatory and it is
        logged — there is no unattributed traffic in this system.
        """
        self.budget.navigate(url, reason)
        return await page.goto(url, wait_until=wait_until)

    async def wait_for_ready(self, page: Page, *, settle_ms: int = 1200) -> None:
        """Wait for a reasonable readiness point, then a short settle.

        `networkidle` is deliberately best-effort: many commerce sites hold
        long-poll connections open and would never reach it. We wait, accept
        a timeout, then give late resources a brief moment.
        """
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:                                       # noqa: BLE001
            log.debug("networkidle not reached; continuing with load state")
        await page.wait_for_timeout(settle_ms)

    async def scroll_to_fold(self, page: Page) -> None:
        """One paced scroll to the fold and back.

        Purpose: settle lazy-loaded content so LCP and mixed-content checks see
        what a real visitor sees. This is NOT a crawl of the page, and it is
        not an imitation of human behaviour — it is the minimum needed to make
        below-the-fold resources load.
        """
        await page.evaluate(
            "() => window.scrollTo({top: window.innerHeight, behavior: 'instant'})")
        await page.wait_for_timeout(600)
        await page.evaluate("() => window.scrollTo({top: 0, behavior: 'instant'})")
        await page.wait_for_timeout(200)
