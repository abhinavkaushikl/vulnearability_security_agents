"""NetworkThrottleTool + PerformanceMeasurementTool.

Throttling uses CDP Network.emulateNetworkConditions, which is Chromium-only.
On any other engine the profile is marked UNAVAILABLE rather than silently
reported as unthrottled — an unthrottled number labelled "3G" would be a
fabricated measurement.
"""
from __future__ import annotations

import logging

from playwright.async_api import BrowserContext, Page

from app.models.evidence import WebVitals
from app.models.performance import NetworkProfile, PerformanceMeasurement
from app.tools import inspection

log = logging.getLogger(__name__)


class ThrottleUnavailable(Exception):
    """Raised when the engine cannot emulate network conditions."""


async def apply_network_profile(context: BrowserContext, page: Page,
                                profile: NetworkProfile):
    """Apply a throttling profile via CDP. Returns the CDP session."""
    try:
        cdp = await context.new_cdp_session(page)
    except Exception as exc:                                    # noqa: BLE001
        raise ThrottleUnavailable(
            f"CDP unavailable on this browser: {exc}") from exc
    try:
        await cdp.send("Network.enable")
        await cdp.send("Network.emulateNetworkConditions", {
            "offline": False,
            "latency": profile.latency_ms,
            "downloadThroughput": profile.download_bps,
            "uploadThroughput": profile.upload_bps,
        })
        log.info("network profile applied: %s (%.1f Mbps down, %d ms RTT)",
                 profile.name, profile.download_mbps, int(profile.latency_ms))
        return cdp
    except Exception as exc:                                    # noqa: BLE001
        raise ThrottleUnavailable(
            f"emulateNetworkConditions failed: {exc}") from exc


async def clear_profile(cdp) -> None:
    try:
        await cdp.send("Network.emulateNetworkConditions", {
            "offline": False, "latency": 0,
            "downloadThroughput": -1, "uploadThroughput": -1})
    except Exception:                                           # noqa: BLE001
        pass


async def measure_page_load(
    *,
    session,
    context: BrowserContext,
    url: str,
    profile: NetworkProfile,
    iteration: int,
    assessment_id: str,
    scope_host: str,
    collect_vitals: bool = True,
) -> PerformanceMeasurement:
    """One measured page load. Every metric is observed or left None."""
    m = PerformanceMeasurement(assessment_id=assessment_id,
                               network_profile=profile.name, iteration=iteration)
    page = None
    cdp = None
    try:
        page = await session.open_page(context)
        recorder = inspection.NetworkRecorder(scope_host)
        recorder.attach(page, url)

        if profile.name != "unthrottled":
            cdp = await apply_network_profile(context, page, profile)

        await session.navigate(
            page, url, reason=f"PERF: profile={profile.name} iteration={iteration}")
        try:
            await page.wait_for_load_state("load", timeout=60_000)
        except Exception:                                       # noqa: BLE001
            log.debug("load state not reached for %s iter %d", profile.name, iteration)

        timing = await inspection.collect_navigation_timing(page)
        m.dns_time = timing.get("dns_time")
        m.tcp_time = timing.get("tcp_time")
        m.tls_time = timing.get("tls_time")
        m.ttfb = timing.get("ttfb")
        m.dom_content_loaded = timing.get("dom_content_loaded")
        m.page_load_time = timing.get("page_load_time")
        m.redirect_count = int(timing.get("redirect_count") or 0)

        if collect_vitals:
            v: WebVitals = await inspection.collect_web_vitals(page)
            m.lcp = v.lcp_ms
            m.cls = v.cls
            # m.inp stays None: not measurable without real user input.

        m.request_count = len(recorder.requests)
        m.response_count = len(recorder.headers)
        m.failed_requests = sum(1 for r in recorder.requests if r.failed)
        m.transferred_bytes = int(timing.get("transfer_size") or 0) + sum(
            r.transferred_bytes for r in recorder.requests)
        m.succeeded = True
    except Exception as exc:                                    # noqa: BLE001
        m.succeeded = False
        m.error = f"{type(exc).__name__}: {exc}"
        log.warning("measurement failed (%s iter %d): %s",
                    profile.name, iteration, exc)
    finally:
        if cdp:
            await clear_profile(cdp)
        if page:
            try:
                await page.close()
            except Exception:                                   # noqa: BLE001
                pass
    return m
