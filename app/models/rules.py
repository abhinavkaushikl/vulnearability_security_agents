"""Rule domain model.

Mirrors `Rules/18_rule_object_schema.md`. Fields are split into three groups:
parsed verbatim from the Markdown table, derived deterministically by the
engine, and (optionally) interpreted once by the LLM and cached.

Nothing here invents a control. Fields the pack defines but never populates
(framework_mapping, remediation, owner) stay empty rather than being guessed.
"""
from __future__ import annotations

import hashlib
from enum import Enum

from pydantic import BaseModel, Field


class Automation(str, Enum):
    """The `Auto?` column. Defined in every family file's "Automation notes"."""

    PASSIVE = "P"  # passive/observable automation is normally possible
    MANUAL = "M"  # manual review or authorized active testing required
    HYBRID = "P/M"  # automate observable evidence, then review the remainder
    HYBRID_M = "M/P"  # same, written the other way round in some files
    NOT_PROVABLE = "No"  # organizational/legal evidence, not provable from a website

    @property
    def has_passive_component(self) -> bool:
        return self in (Automation.PASSIVE, Automation.HYBRID, Automation.HYBRID_M)

    @property
    def is_fully_passive(self) -> bool:
        return self is Automation.PASSIVE


class Severity(str, Enum):
    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"
    INFO = "Info"

    @property
    def rank(self) -> int:
        return {"Critical": 4, "High": 3, "Medium": 2, "Low": 1, "Info": 0}[self.value]


class TestLayer(str, Enum):
    """Automation layers from `Rules/00_README.md`."""

    #: Domain enum, not a pytest test class. Stops pytest trying to collect it.
    __test__ = False

    L1 = "L1"  # public passive
    L2 = "L2"  # authenticated, controlled test accounts
    L3 = "L3"  # business logic, staging/sandbox
    L4 = "L4"  # organization/compliance evidence
    L5 = "L5"  # operations/resilience

    @classmethod
    def from_automation(cls, automation: Automation) -> "TestLayer":
        """Derive the layer from the Auto? tier.

        The family tables never populate `test_layer` even though
        `18_rule_object_schema.md` defines it, so we derive rather than invent.
        Hybrids are L2: they have an L1 component but cannot be *closed* at L1.
        """
        if automation is Automation.PASSIVE:
            return cls.L1
        if automation in (Automation.HYBRID, Automation.HYBRID_M):
            return cls.L2
        if automation is Automation.NOT_PROVABLE:
            return cls.L4
        return cls.L3


class CollectorCode(str, Enum):
    """Evidence collectors. See CLAUDE.md section "Evidence collectors".

    The set is bounded by `Rules/19_test_modes_safety.md`, which enumerates what
    public passive mode may observe. Nothing outside that sentence is collected.
    """

    HDR = "HDR"      # response headers, main document + subresources
    CK = "CK"        # cookies with attributes (values redacted)
    WS = "WS"        # localStorage / sessionStorage key inventory
    DOM = "DOM"      # rendered DOM + raw HTML source
    JS = "JS"        # script bodies and source-map references
    NET = "NET"      # request/response log
    CON = "CON"      # console messages and page errors
    TIM = "TIM"      # navigation + resource timing
    CWV = "CWV"      # Core Web Vitals (lab: LCP, CLS only)
    A11 = "A11"      # accessibility tree + axe heuristics
    FRM = "FRM"      # form inventory
    LNK = "LNK"      # link inventory
    THIRD_PARTY = "3P"   # distinct third-party origins
    CACHE = "CACHE"  # cache-control family
    SHOT = "SHOT"    # screenshots
    RDR = "RDR"      # HTTP -> HTTPS redirect chain
    TLS = "TLS"      # certificate chain / protocol
    DNS = "DNS"      # DNS records, DNSSEC, CAA
    WK = "WK"        # /.well-known/security.txt, /robots.txt
    ERR = "ERR"      # one benign 404
    CORS = "CORS"    # CORS headers on observed cross-origin responses
    SELF = "SELF"    # audit metadata about this run (GOV-05, IN-07)


class RuleInterpretation(BaseModel):
    """The only thing the LLM decides about a rule. Computed once, then cached.

    Keyed on SecurityRule.content_hash, so re-runs cost zero LLM calls and the
    interpretation is stable across runs (temperature 0 plus a disk cache).
    """

    required_collectors: list[CollectorCode] = Field(default_factory=list)
    evaluable_at_l1: bool = False
    applicability_test: str = ""
    observable_signals: list[str] = Field(default_factory=list)
    not_observable: list[str] = Field(default_factory=list)


class SecurityRule(BaseModel):
    """One control, parsed from one row of one family table."""

    # --- parsed verbatim from the Markdown table row ---
    control_id: str
    control: str
    test_method: str
    pass_criteria: str
    evidence: str
    automation: Automation
    severity: Severity

    # --- parsed from the family file header ---
    family: str
    control_domain: str
    family_purpose: str = ""
    source_file: str
    source_line: int
    pack_version: str = ""

    # --- derived deterministically ---
    test_layer: TestLayer
    requires_authorization: bool

    # --- filled once by the LLM, then cached ---
    interpretation: RuleInterpretation | None = None

    # --- defined by 18_rule_object_schema.md but never populated by the pack ---
    framework_mapping: list[str] = Field(default_factory=list)
    remediation: str | None = None
    owner: str | None = None

    @property
    def content_hash(self) -> str:
        """Stable identity of this rule's *text*, for the interpretation cache.

        Changing the wording of a control in Markdown invalidates its cached
        interpretation automatically; renaming a file does not.
        """
        payload = "␟".join(
            [self.control_id, self.control, self.test_method,
             self.pass_criteria, self.evidence, self.automation.value]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    @property
    def name(self) -> str:
        """Short human-readable name: the first clause of the control text."""
        head = self.control.split(".")[0].split(";")[0].strip()
        return head[:117] + "..." if len(head) > 120 else head


class RuleFamily(BaseModel):
    """One `Rules/NN_*.md` file: a control family."""

    family: str                    # "NET"
    title: str                     # "Network, DNS, TLS & Edge Security"
    purpose: str
    control_domain: str            # "network_dns_tls_edge"
    source_file: str
    pack_version: str = ""
    rules: list[SecurityRule] = Field(default_factory=list)

    @property
    def passive_count(self) -> int:
        return sum(1 for r in self.rules if r.automation.has_passive_component)
