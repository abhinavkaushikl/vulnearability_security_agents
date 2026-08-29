"""Browser Discovery + Evidence Collection agent.

Executes the plan's action list against ONE navigation, then freezes the
EvidenceBundle. After this returns, nothing in the graph can generate traffic:
no evaluator holds a page handle. That is what makes "stop when complete" a
structural property rather than a prompt instruction.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from urllib.parse import urlparse

from app.config.settings import Settings
from app.models.assessment import AntiBotSignal
from app.models.evidence import EvidenceBundle
from app.models.rules import CollectorCode
from app.safety import antibot, redaction
from app.safety.limits import BudgetExceeded, TrafficBudget
from app.tools import a11y as a11y_tool
from app.tools import inspection, network, screenshots
from app.tools.browser import BrowserSession

log = logging.getLogger(__name__)


class EvidenceCollector:
    """Collects everything the plan asked for, and nothing it did not."""

    def __init__(self, session: BrowserSession, settings: Settings,
                 budget: TrafficBudget, artifact_dir: Path):
        self.session = session
        self.settings = settings
        self.budget = budget
        self.artifact_dir = artifact_dir

    async def collect(self, *, assessment_id: str, target_url: str,
                      required: set[CollectorCode]
                      ) -> tuple[EvidenceBundle, AntiBotSignal]:
        bundle = EvidenceBundle(assessment_id=assessment_id,
                                target_url=target_url)
        scope_host = inspection.registrable_host(target_url)
        hostname = urlparse(target_url).hostname or ""
        signal = AntiBotSignal()

        # --- out-of-band collectors run CONCURRENTLY with the navigation.
        # They touch different endpoints (or no endpoint at all, for DNS),
        # so they add no contention and no meaningful load.
        oob = self._out_of_band_tasks(target_url, hostname, required)

        try:
            signal = await self._navigate_and_collect(
                bundle, target_url, scope_host, required)
        except BudgetExceeded as exc:
            bundle.collector_errors["budget"] = str(exc)
            log.warning("traffic budget stopped evidence collection: %s", exc)
        except Exception as exc:                                # noqa: BLE001
            bundle.collector_errors["navigation"] = f"{type(exc).__name__}: {exc}"
            log.error("navigation failed: %s", exc)

        await self._gather_out_of_band(bundle, oob)
        bundle.audit_metadata = {
            "browser": self.session.browser_version,
            "collectors_run": ",".join(c.value for c in bundle.collectors_run),
            "navigations": str(self.budget.navigations),
            "aux_requests": str(self.budget.aux_requests),
        }
        return bundle, signal

    # -- out of band -------------------------------------------------------
    def _out_of_band_tasks(self, target_url: str, hostname: str,
                           required: set[CollectorCode]) -> dict:
        a = self.settings.assessment
        tasks: dict[str, asyncio.Task] = {}
        if hostname and a.collect_tls and CollectorCode.TLS in required:
            tasks["tls"] = asyncio.create_task(network.collect_tls(hostname))
        if hostname and a.collect_dns and CollectorCode.DNS in required:
            tasks["dns"] = asyncio.create_task(network.collect_dns(hostname))
        if CollectorCode.RDR in required:
            self.budget.aux(target_url, "NET-01: HTTP->HTTPS redirect chain")
            tasks["redirect"] = asyncio.create_task(
                network.collect_redirect_chain(target_url))
        if a.probe_well_known and CollectorCode.WK in required:
            self.budget.aux(target_url, "IR-05: security.txt / robots.txt")
            tasks["wk"] = asyncio.create_task(network.collect_well_known(target_url))
        if a.probe_error_page and CollectorCode.ERR in required:
            self.budget.aux(target_url, "WEB-10/APP-07: benign 404 probe")
            tasks["err"] = asyncio.create_task(network.probe_error_page(target_url))
        return tasks

    async def _gather_out_of_band(self, bundle: EvidenceBundle,
                                  tasks: dict) -> None:
        for name, task in tasks.items():
            try:
                result = await task
            except Exception as exc:                            # noqa: BLE001
                bundle.collector_errors[name] = f"{type(exc).__name__}: {exc}"
                continue
            match name:
                case "tls":
                    bundle.tls = result
                    bundle.collectors_run.append(CollectorCode.TLS)
                case "dns":
                    bundle.dns = result
                    bundle.collectors_run.append(CollectorCode.DNS)
                case "redirect":
                    bundle.redirect_chain, bundle.http_scheme_reachable = result
                    bundle.collectors_run.append(CollectorCode.RDR)
                case "wk":
                    bundle.well_known = result
                    bundle.collectors_run.append(CollectorCode.WK)
                case "err":
                    bundle.error_page = result
                    bundle.collectors_run.append(CollectorCode.ERR)

    # -- the single instrumented navigation --------------------------------
    async def _navigate_and_collect(self, bundle: EvidenceBundle,
                                    target_url: str, scope_host: str,
                                    required: set[CollectorCode]) -> AntiBotSignal:
        async with self.session.context(label="discovery") as ctx:
            page = await self.session.open_page(ctx)
            recorder = inspection.NetworkRecorder(scope_host)
            recorder.attach(page, target_url)   # BEFORE navigation, or we miss the doc

            response = await self.session.navigate(
                page, target_url,
                reason="primary evidence collection for all L1 controls")
            await self.session.wait_for_ready(page)

            bundle.final_url = page.url
            bundle.page_title = await page.title()
            html = await page.content()
            bundle.html_source = html
            bundle.html_length = len(html)

            # --- anti-bot gate. Detect, stop, record, report. Never bypass.
            status = response.status if response else None
            hdrs = dict(response.headers) if response else {}
            signal = antibot.detect(status=status, headers=hdrs,
                                    body=html, url=page.url)
            if signal.detected:
                log.warning("anti-bot / rate-limit detected (%s) — halting",
                            signal.kind)
                self._record_network(bundle, recorder, required)
                return signal

            # Settle lazy content only if a rule needs what is below the fold.
            if {CollectorCode.CWV, CollectorCode.NET} & required:
                await self.session.scroll_to_fold(page)

            await self._run_in_page_collectors(bundle, ctx, page, html,
                                               scope_host, required)
            self._record_network(bundle, recorder, required)
            return signal

    def _record_network(self, bundle: EvidenceBundle,
                        recorder: inspection.NetworkRecorder,
                        required: set[CollectorCode]) -> None:
        bundle.requests = recorder.requests
        bundle.all_headers = recorder.headers
        bundle.console = recorder.console
        bundle.main_response = recorder.main_response
        bundle.third_party_origins = recorder.third_party_origins
        bundle.cors_headers = recorder.cors
        for code in (CollectorCode.NET, CollectorCode.HDR, CollectorCode.CON,
                     CollectorCode.THIRD_PARTY, CollectorCode.CACHE,
                     CollectorCode.CORS):
            if code in required and code not in bundle.collectors_run:
                bundle.collectors_run.append(code)

    async def _run_in_page_collectors(self, bundle, ctx, page, html,
                                      scope_host, required) -> None:
        """Each collector is independently guarded: one failure never aborts."""
        async def run(code: CollectorCode, coro, assign):
            if code not in required:
                return
            try:
                assign(await coro())
                bundle.collectors_run.append(code)
            except Exception as exc:                            # noqa: BLE001
                bundle.collector_errors[code.value] = f"{type(exc).__name__}: {exc}"
                log.warning("collector %s failed: %s", code.value, exc)

        def set_scripts(v):
            bundle.scripts = v

        await run(CollectorCode.DOM, lambda: _identity(html),
                  lambda v: None)
        await run(CollectorCode.CK,
                  lambda: inspection.inspect_cookies(ctx, page.url),
                  lambda v: setattr(bundle, "cookies", v))
        await run(CollectorCode.WS, lambda: inspection.inspect_storage(page),
                  lambda v: setattr(bundle, "storage", v))
        await run(CollectorCode.FRM, lambda: inspection.inspect_forms(page),
                  lambda v: setattr(bundle, "forms", v))
        await run(CollectorCode.LNK, lambda: inspection.inspect_links(page),
                  lambda v: setattr(bundle, "links", v))
        await run(CollectorCode.JS,
                  lambda: inspection.inspect_scripts(page, scope_host),
                  set_scripts)
        await run(CollectorCode.TIM,
                  lambda: inspection.collect_navigation_timing(page),
                  lambda v: setattr(bundle, "navigation_timing", v))
        await run(CollectorCode.CWV, lambda: inspection.collect_web_vitals(page),
                  lambda v: setattr(bundle, "vitals", v))
        await run(CollectorCode.A11,
                  lambda: a11y_tool.collect_a11y(
                      page, run_axe=self.settings.assessment.run_axe),
                  lambda v: setattr(bundle, "a11y", v))

        # WEB-09 needs the script inventory, so it runs after JS.
        if CollectorCode.JS in required:
            try:
                bundle.secrets = await inspection.scan_page_secrets(
                    page, html, bundle.scripts)
            except Exception as exc:                            # noqa: BLE001
                bundle.collector_errors["secrets"] = str(exc)

        # The scan has recorded WHAT exists; the literals themselves are now
        # scrubbed from the retained HTML. Downstream consumers (evidence
        # projection, LLM prompts, report excerpts) never see a live secret.
        bundle.html_source = redaction.redact_secrets_in_text(bundle.html_source)

        if self.settings.screenshots.enabled and CollectorCode.SHOT in required:
            shot = await screenshots.capture_screenshot(
                page, self.artifact_dir, "landing",
                full_page=self.settings.screenshots.full_page)
            if shot:
                bundle.screenshots.append(shot)
                bundle.collectors_run.append(CollectorCode.SHOT)


async def _identity(value):
    return value
