"""Integration tests.

These drive a real Chromium against a LOCAL fixture site on 127.0.0.1.
They never touch a public website — the rule pack's safety boundary applies
to our own test suite too.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.agents.browser_agent import EvidenceCollector
from app.config.settings import load_settings
from app.models.rules import CollectorCode
from app.safety.limits import TrafficBudget
from app.tools.browser import BrowserSession
from tests.fixtures.server import FixtureSite

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

ROOT = Path(__file__).resolve().parents[2]

#: Secrets planted in the fixture site. None may ever reach the bundle.
PLANTED_SECRETS = [
    "abc123def456",                                     # cookie value
    "AKIAIOSFODNN7EXAMPLE",                             # AWS key in app.js
    "hunter2secret",                                    # password literal
    "dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk",       # JWT in localStorage
]


@pytest.fixture(scope="module")
def settings():
    return load_settings(project_root=ROOT)


async def _collect(settings, required=None):
    with FixtureSite() as site:
        budget = TrafficBudget(max_navigations=20, max_pages=20)
        artifact_dir = Path(tempfile.mkdtemp()) / "assessment"
        session = BrowserSession(settings, budget, artifact_dir)
        await session.start()
        try:
            collector = EvidenceCollector(session, settings, budget, artifact_dir)
            bundle, signal = await collector.collect(
                assessment_id="itest",
                target_url=site.base_url + "/",
                required=required or set(CollectorCode))
            return bundle, signal, budget
        finally:
            await session.close()


@pytest.fixture(scope="module")
async def collected(settings):
    return await _collect(settings)


async def test_browser_starts_and_navigates(collected):
    bundle, signal, _ = collected
    assert bundle.page_title == "Fixture Shop — assessment test target"
    assert not signal.detected
    assert bundle.main_response and bundle.main_response.status == 200


async def test_no_collector_errored(collected):
    bundle, _, _ = collected
    assert bundle.collector_errors == {}


async def test_header_collector_sees_present_and_absent_headers(collected):
    bundle, _, _ = collected
    assert bundle.header("x-content-type-options") == "nosniff"     # WEB-02
    assert bundle.header("content-security-policy") is None         # WEB-01
    assert bundle.header("strict-transport-security") is None       # NET-03


async def test_cookie_flags_are_captured_without_values(collected):
    """WEB-05 needs the flags; it must never receive the value."""
    bundle, _, _ = collected
    by_name = {c.name: c for c in bundle.cookies}
    assert by_name["sessionid"].secure is False
    assert by_name["sessionid"].http_only is False
    assert by_name["consent"].secure is True
    assert by_name["consent"].http_only is True
    assert all(not hasattr(c, "value") for c in bundle.cookies)


async def test_web_storage_keys_are_captured_and_classified(collected):
    """WEB-06 needs key names and shapes, never contents."""
    bundle, _, _ = collected
    by_key = {s.key: s for s in bundle.storage}
    assert by_key["auth_token"].looks_like_jwt is True
    assert by_key["theme"].looks_like_jwt is False
    assert by_key["cart_id"].area == "sessionStorage"


async def test_secret_scanner_finds_planted_secrets(collected):
    """WEB-09."""
    bundle, _, _ = collected
    kinds = {f.kind for f in bundle.secrets}
    assert "aws_access_key" in kinds
    assert "source_map_reference" in kinds


@pytest.mark.parametrize("secret", PLANTED_SECRETS)
async def test_no_planted_secret_reaches_the_serialized_bundle(collected, secret):
    """The whole point of redaction-at-capture."""
    bundle, _, _ = collected
    assert secret not in bundle.model_dump_json()


@pytest.mark.parametrize("secret", PLANTED_SECRETS)
async def test_no_planted_secret_survives_in_retained_html(collected, secret):
    bundle, _, _ = collected
    assert secret not in bundle.html_source


async def test_html_source_is_never_serialized(collected):
    bundle, _, _ = collected
    assert "html_source" not in bundle.model_dump_json()


async def test_third_party_scripts_and_sri_are_recorded(collected):
    """WEB-07."""
    bundle, _, _ = collected
    third = [s for s in bundle.scripts if s.is_third_party]
    assert third and not any(s.has_integrity for s in third)
    assert "cdn.example-third-party.test" in bundle.third_party_origins


async def test_forms_are_inventoried_but_never_submitted(collected):
    bundle, _, _ = collected
    assert len(bundle.forms) == 1
    form = bundle.forms[0]
    assert form.has_password_field
    assert form.unlabelled_field_count == 1        # the password input
    assert "username" in form.field_names


async def test_error_page_probe_detects_disclosure(collected):
    """WEB-10 and APP-07, from ONE benign 404."""
    bundle, _, _ = collected
    assert bundle.error_page.status == 404
    assert bundle.error_page.leaks_stack_trace is True
    assert bundle.error_page.leaks_internal_path is True
    assert "PHP/8.1.2" in bundle.error_page.version_strings


async def test_navigation_timing_and_lab_vitals_collected(collected):
    bundle, _, _ = collected
    assert bundle.navigation_timing.get("ttfb") is not None
    assert bundle.vitals.inp_ms is None, "INP must never be estimated"


async def test_accessibility_heuristics_run(collected):
    bundle, _, _ = collected
    assert bundle.a11y.images_missing_alt == 1
    assert bundle.a11y.lang_attribute == "en"


async def test_traffic_footprint_stays_tiny(collected):
    """One navigation plus a handful of auxiliary requests."""
    _, _, budget = collected
    assert budget.navigations == 1
    assert budget.aux_requests <= 4
    assert budget.total_requests <= 5


async def test_only_requested_collectors_run(settings):
    """The plan is the entire interaction budget."""
    bundle, _, _ = await _collect(settings, required={CollectorCode.HDR,
                                                     CollectorCode.NET,
                                                     CollectorCode.CK})
    assert CollectorCode.CK in bundle.collectors_run
    assert CollectorCode.A11 not in bundle.collectors_run
    assert CollectorCode.ERR not in bundle.collectors_run
    assert bundle.a11y.lang_attribute is None       # never collected
