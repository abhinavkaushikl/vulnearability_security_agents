"""Evidence model.

The EvidenceBundle is written exactly once, by COLLECT_EVIDENCE, and is
read-only for the rest of the graph. That is what makes "stop when the
assessment is complete" a structural guarantee rather than a prompt
instruction: no evaluator holds a browser handle, so no evaluator can
generate traffic.

Redaction happens at *capture* time (see app/safety/redaction.py), not at
report time. A secret that is never written cannot leak through a log,
a trace or a spreadsheet.
"""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from app.models.rules import CollectorCode


class HeaderSet(BaseModel):
    """Response headers for one URL."""

    url: str
    status: int
    headers: dict[str, str] = Field(default_factory=dict)   # lower-cased keys
    resource_type: str = ""
    from_cache: bool = False

    def get(self, name: str) -> str | None:
        return self.headers.get(name.lower())


class CookieRecord(BaseModel):
    """A cookie's *attributes*. The value is never stored — WEB-05 needs flags."""

    name: str
    domain: str
    path: str
    secure: bool
    http_only: bool
    same_site: str | None = None
    expires: float | None = None
    value_length: int = 0        # shape only, for evidence quality
    session_cookie: bool = False


class StorageRecord(BaseModel):
    """A Web Storage key. WEB-06 needs key names and shapes, never contents."""

    area: str                    # "localStorage" | "sessionStorage"
    key: str
    value_length: int
    looks_like_jwt: bool = False
    looks_like_token: bool = False


class RequestRecord(BaseModel):
    url: str
    method: str
    resource_type: str
    origin: str = ""
    is_third_party: bool = False
    failed: bool = False
    failure_text: str | None = None
    status: int | None = None
    response_headers: dict[str, str] = Field(default_factory=dict)
    transferred_bytes: int = 0
    is_insecure: bool = False    # http:// subresource on an https:// page


class ConsoleRecord(BaseModel):
    level: str                   # "error" | "warning" | "info" | ...
    text: str
    location: str = ""


class FormRecord(BaseModel):
    action: str = ""
    method: str = "get"
    over_https: bool = True
    field_count: int = 0
    field_names: list[str] = Field(default_factory=list)
    field_types: list[str] = Field(default_factory=list)
    has_password_field: bool = False
    unlabelled_field_count: int = 0     # A11Y-03
    autocomplete_off: bool = False


class ScriptRecord(BaseModel):
    src: str = ""
    inline: bool = False
    is_third_party: bool = False
    has_integrity: bool = False         # WEB-07
    has_crossorigin: bool = False
    body_length: int = 0


class SecretFinding(BaseModel):
    """WEB-09. Pattern/entropy match. The matched secret itself is NOT stored."""

    kind: str                    # "aws_access_key" | "private_key" | "high_entropy"
    location: str                # URL or "inline-script#3"
    context_hint: str            # a redacted neighbourhood, never the value
    confidence: float = 0.0


class TlsEvidence(BaseModel):
    """NET-02, NET-04. Collected via stdlib ssl — Playwright cannot see this."""

    reachable: bool = False
    protocol: str | None = None            # "TLSv1.3"
    cipher: str | None = None
    subject_cn: str | None = None
    san: list[str] = Field(default_factory=list)
    issuer: str | None = None
    not_before: str | None = None
    not_after: str | None = None
    days_until_expiry: int | None = None
    hostname_matches: bool | None = None
    error: str | None = None


class DnsEvidence(BaseModel):
    """NET-05, NET-06. Resolved off-target: costs the site nothing."""

    a: list[str] = Field(default_factory=list)
    aaaa: list[str] = Field(default_factory=list)
    cname: list[str] = Field(default_factory=list)
    ns: list[str] = Field(default_factory=list)
    mx: list[str] = Field(default_factory=list)
    caa: list[str] = Field(default_factory=list)
    dnssec_present: bool | None = None
    error: str | None = None


class RedirectHop(BaseModel):
    url: str
    status: int
    location: str | None = None


class WellKnownEvidence(BaseModel):
    security_txt_present: bool = False
    security_txt_fields: list[str] = Field(default_factory=list)
    robots_txt_present: bool = False
    robots_disallow_count: int = 0


class ErrorPageEvidence(BaseModel):
    """One benign 404 on a random path. Non-destructive. WEB-10, APP-07."""

    probed_url: str = ""
    status: int | None = None
    server_header: str | None = None
    powered_by: str | None = None
    body_length: int = 0
    leaks_stack_trace: bool = False
    leaks_internal_path: bool = False
    version_strings: list[str] = Field(default_factory=list)


class A11yEvidence(BaseModel):
    """A11Y-01/03/06. axe-core is a *subset* of WCAG — never a conformance claim."""

    axe_available: bool = False
    violations: list[dict] = Field(default_factory=list)
    violation_count: int = 0
    critical_count: int = 0
    images_missing_alt: int = 0
    unlabelled_inputs: int = 0
    landmark_count: int = 0
    lang_attribute: str | None = None


class WebVitals(BaseModel):
    """Lab measurements only. PERF-01 asks for field p75; we cannot supply it."""

    lcp_ms: float | None = None
    cls: float | None = None
    inp_ms: None = None          # structurally unmeasurable without real input
    fcp_ms: float | None = None


class EvidenceBundle(BaseModel):
    """Everything one assessment observed. Frozen after COLLECT_EVIDENCE."""

    assessment_id: str
    target_url: str
    final_url: str = ""
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    collectors_run: list[CollectorCode] = Field(default_factory=list)
    collector_errors: dict[str, str] = Field(default_factory=dict)

    # in-page collectors (one navigation feeds all of these)
    page_title: str = ""
    html_length: int = 0
    # Held in memory for scanning only. exclude=True keeps it out of every
    # model_dump / model_dump_json, so it can never reach Excel, a log or
    # an LLM prompt. Secret literals in it are ALSO redacted post-scan.
    html_source: str = Field(default="", exclude=True, repr=False)
    main_response: HeaderSet | None = None
    all_headers: list[HeaderSet] = Field(default_factory=list)
    cookies: list[CookieRecord] = Field(default_factory=list)
    storage: list[StorageRecord] = Field(default_factory=list)
    requests: list[RequestRecord] = Field(default_factory=list)
    console: list[ConsoleRecord] = Field(default_factory=list)
    forms: list[FormRecord] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    scripts: list[ScriptRecord] = Field(default_factory=list)
    third_party_origins: list[str] = Field(default_factory=list)
    secrets: list[SecretFinding] = Field(default_factory=list)
    a11y: A11yEvidence = Field(default_factory=A11yEvidence)
    vitals: WebVitals = Field(default_factory=WebVitals)
    screenshots: list[str] = Field(default_factory=list)
    navigation_timing: dict[str, float] = Field(default_factory=dict)

    # out-of-band collectors (run concurrently with the navigation)
    tls: TlsEvidence = Field(default_factory=TlsEvidence)
    dns: DnsEvidence = Field(default_factory=DnsEvidence)
    redirect_chain: list[RedirectHop] = Field(default_factory=list)
    http_scheme_reachable: bool | None = None
    well_known: WellKnownEvidence = Field(default_factory=WellKnownEvidence)
    error_page: ErrorPageEvidence = Field(default_factory=ErrorPageEvidence)
    cors_headers: dict[str, dict[str, str]] = Field(default_factory=dict)

    # audit metadata — GOV-05 and IN-07 are controls about the report itself
    audit_metadata: dict[str, str] = Field(default_factory=dict)

    def has(self, code: CollectorCode) -> bool:
        return code in self.collectors_run

    def header(self, name: str) -> str | None:
        """Main-document response header, lower-cased lookup."""
        return self.main_response.get(name) if self.main_response else None
