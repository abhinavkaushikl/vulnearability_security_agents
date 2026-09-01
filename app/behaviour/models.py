"""Domain model for the User Behaviour Agent.

Three vocabularies live here and are deliberately kept apart:

  * what the agent SAW      — PageModel, InteractiveElement
  * what the agent DID      — ActionIntent, ActionRecord, InteractionTiming
  * what the agent CONCLUDED— UXFinding, UXScore, BehaviourReport

Nothing in the third group may be constructed without something from the
first two to point at. That is the same evidence discipline the security
engine runs on, applied to experience rather than to controls.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


# ══════════════════════════════════════════════════════ state machine


class AgentState(str, Enum):
    """§26. The frontend mirrors these names exactly."""

    DISCOVERING = "DISCOVERING"
    UNDERSTANDING = "UNDERSTANDING"
    PLANNING = "PLANNING"
    NAVIGATING = "NAVIGATING"
    INTERACTING = "INTERACTING"
    OBSERVING = "OBSERVING"
    MEASURING = "MEASURING"
    ADAPTING = "ADAPTING"
    REPORTING = "REPORTING"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"

    @property
    def is_terminal(self) -> bool:
        return self in (AgentState.COMPLETED, AgentState.BLOCKED,
                        AgentState.FAILED)


# ══════════════════════════════════════════════════════ what was seen


class ElementKind(str, Enum):
    """How the agent will treat an element, not what tag it is.

    Derived from role + accessible name + surrounding structure, so a `<div
    role="button">` and a `<button>` are the same kind of thing to the agent.
    """

    LINK = "link"
    BUTTON = "button"
    TEXT_INPUT = "text_input"
    SEARCH_INPUT = "search_input"
    PASSWORD_INPUT = "password_input"
    EMAIL_INPUT = "email_input"
    SELECT = "select"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    TEXTAREA = "textarea"
    NAV = "nav"
    MENU_TOGGLE = "menu_toggle"
    TAB = "tab"
    ACCORDION = "accordion"
    MODAL_CLOSE = "modal_close"
    MEDIA = "media"
    PRODUCT_CARD = "product_card"
    ADD_TO_CART = "add_to_cart"
    QUANTITY = "quantity"
    PAGINATION = "pagination"
    SUBMIT = "submit"
    OTHER = "other"


class Risk(str, Enum):
    """The safety classification of touching an element. See safety.py."""

    SAFE = "SAFE"              # click freely
    SENSITIVE = "SENSITIVE"    # observe, may interact, never complete
    FORBIDDEN = "FORBIDDEN"    # never dispatched, under any plan


class InteractiveElement(BaseModel):
    """One thing on the page a user could act on.

    `ref` is the only handle the LLM ever receives. It cannot express a
    selector, so it cannot direct the browser anywhere the observer did not
    already see and classify.
    """

    ref: str                              # "e17" — stable within one PageModel
    kind: ElementKind = ElementKind.OTHER
    role: str = ""
    name: str = ""                        # accessible name
    text: str = ""
    tag: str = ""
    href: str | None = None
    selector: str = ""                    # resolved by the observer, never by the LLM
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    in_viewport: bool = False
    visible: bool = True
    enabled: bool = True
    focusable: bool = False
    has_accessible_name: bool = True
    risk: Risk = Risk.SAFE
    risk_reason: str = ""

    @property
    def label(self) -> str:
        """What to call this control in a report.

        An unnamed control is named as unnamed. Falling back to the tag would
        print "button" — which reads like a name, and hides the fact that a
        screen reader has nothing to announce here.
        """
        for candidate in (self.name, self.text, self.href):
            if candidate and candidate.strip():
                return candidate.strip()[:80]
        return f"unnamed {self.tag or self.role or 'control'}"


class FormModel(BaseModel):
    ref: str
    name: str = ""
    action: str = ""
    method: str = "get"
    field_refs: list[str] = Field(default_factory=list)
    has_password: bool = False
    has_payment_field: bool = False
    submit_ref: str | None = None
    risk: Risk = Risk.SAFE


class A11ySnapshot(BaseModel):
    """Structural accessibility facts. Not a WCAG conformance claim."""

    focusable_count: int = 0
    unlabelled_controls: int = 0
    images_missing_alt: int = 0
    heading_levels: list[int] = Field(default_factory=list)
    heading_order_ok: bool = True
    landmark_roles: list[str] = Field(default_factory=list)
    has_skip_link: bool = False
    focus_visible_ratio: float | None = None   # sampled by the keyboard walk
    contrast_suspects: int = 0


class PageVitals(BaseModel):
    """Everything observed for one page load. Unobserved stays None."""

    status: int | None = None
    redirects: int = 0
    dns_ms: float | None = None
    tcp_ms: float | None = None
    tls_ms: float | None = None
    ttfb_ms: float | None = None
    dom_content_loaded_ms: float | None = None
    load_ms: float | None = None
    fcp_ms: float | None = None
    lcp_ms: float | None = None
    cls: float | None = None
    js_execution_ms: float | None = None
    transferred_bytes: int | None = None
    request_count: int = 0
    failed_request_count: int = 0
    console_error_count: int = 0
    #: INP needs real user input over a session. We never synthesise it.
    inp_ms: None = None


class PageModel(BaseModel):
    """The agent's understanding of one page at one moment."""

    url: str
    title: str = ""
    reached_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    fingerprint: str = ""                 # structural hash; detects "same page"
    headings: list[str] = Field(default_factory=list)
    text_excerpt: str = ""
    elements: list[InteractiveElement] = Field(default_factory=list)
    forms: list[FormModel] = Field(default_factory=list)
    a11y: A11ySnapshot = Field(default_factory=A11ySnapshot)
    vitals: PageVitals = Field(default_factory=PageVitals)
    scrollable: bool = False
    scroll_height: float = 0.0
    viewport_height: float = 0.0
    has_modal: bool = False
    screenshot: str | None = None         # artifact-relative path
    console_errors: list[str] = Field(default_factory=list)

    def by_ref(self, ref: str) -> InteractiveElement | None:
        return next((e for e in self.elements if e.ref == ref), None)

    @property
    def actionable(self) -> list[InteractiveElement]:
        return [e for e in self.elements
                if e.visible and e.enabled and e.risk is not Risk.FORBIDDEN]


# ══════════════════════════════════════════════════════ what was understood


class SiteKind(str, Enum):
    ECOMMERCE = "ecommerce"
    BANKING = "banking"
    SAAS = "saas"
    NEWS = "news"
    TRAVEL = "travel"
    HEALTHCARE = "healthcare"
    MARKETPLACE = "marketplace"
    SOCIAL = "social"
    GOVERNMENT = "government"
    PORTFOLIO = "portfolio"
    EDUCATION = "education"
    DOCUMENTATION = "documentation"
    UNKNOWN = "unknown"


class SiteUnderstanding(BaseModel):
    """§4. What the site is and what a user comes here to do."""

    kind: SiteKind = SiteKind.UNKNOWN
    confidence: float = 0.0               # 0..1, the model's own, never a score
    primary_goal: str = ""
    secondary_goals: list[str] = Field(default_factory=list)
    audience: str = ""
    key_affordances: list[str] = Field(default_factory=list)
    rationale: str = ""
    derived_by: str = "heuristic"         # "llm" | "heuristic"


class JourneyStep(BaseModel):
    """One intended step of a journey. Intent, not a selector."""

    label: str                            # "Search for a product"
    action: str                           # ActionKind value the agent should attempt
    target_hint: str = ""                 # words to match against element names
    expectation: str = ""                 # what a user would expect to happen
    optional: bool = False


class Journey(BaseModel):
    """§5. A realistic route through the site."""

    id: str
    name: str
    goal: str
    steps: list[JourneyStep] = Field(default_factory=list)
    priority: int = 1                     # 1 = run first
    derived_by: str = "heuristic"


# ══════════════════════════════════════════════════════ what was done


class ActionKind(str, Enum):
    NAVIGATE = "navigate"
    CLICK = "click"
    HOVER = "hover"
    SCROLL = "scroll"
    SCROLL_BACK = "scroll_back"
    TYPE = "type"
    CLEAR = "clear"
    SELECT_OPTION = "select_option"
    CHECK = "check"
    PRESS_KEY = "press_key"
    SUBMIT_SEARCH = "submit_search"
    BACK = "back"
    READ = "read"                         # a deliberate pause, measured as dwell
    PLAY_MEDIA = "play_media"
    PAUSE_MEDIA = "pause_media"
    DONE = "done"                         # the journey is finished


#: Which categories §11 groups an action's timings under.
INTERACTION_CATEGORY: dict[ActionKind, str] = {
    ActionKind.NAVIGATE: "navigation",
    ActionKind.BACK: "navigation",
    ActionKind.CLICK: "button",
    ActionKind.HOVER: "menu",
    ActionKind.SCROLL: "scroll",
    ActionKind.SCROLL_BACK: "scroll",
    ActionKind.TYPE: "form",
    ActionKind.CLEAR: "form",
    ActionKind.SELECT_OPTION: "form",
    ActionKind.CHECK: "form",
    ActionKind.SUBMIT_SEARCH: "search",
    ActionKind.PRESS_KEY: "form",
    ActionKind.PLAY_MEDIA: "media",
    ActionKind.PAUSE_MEDIA: "media",
    ActionKind.READ: "dwell",
    ActionKind.DONE: "control",
}


class ActionIntent(BaseModel):
    """What the brain decided to do next. The executor validates every field.

    This is the entire channel between reasoning and the browser. It carries
    no selector, no URL the observer did not surface, and no script.
    """

    kind: ActionKind
    element_ref: str | None = None
    value: str | None = None              # text to type, option to select
    amount: float | None = None           # scroll delta in viewport fractions
    expectation: str = ""                 # what the agent expects to observe
    reason: str = ""                      # why a user would do this — mandatory
    journey_id: str | None = None
    step_label: str = ""


class Outcome(str, Enum):
    SUCCESS = "SUCCESS"                   # the expected state change was observed
    NO_RESPONSE = "NO_RESPONSE"           # dispatched, nothing changed at all
    UNEXPECTED = "UNEXPECTED"             # something changed, not what was expected
    ERROR = "ERROR"                       # the action itself raised
    REFUSED = "REFUSED"                   # the safety layer declined it
    INCONCLUSIVE = "INCONCLUSIVE"         # observed, cannot decide — never a pass


class InteractionTiming(BaseModel):
    """§10. Three distinct clocks, because they answer different questions.

    Every field is `None` when the probe did not observe it. A missing UI
    response is *evidence of a dead control*, so collapsing it to zero would
    invert the finding.
    """

    #: dispatch -> the page's first observable reaction of any kind.
    input_latency_ms: float | None = None
    #: dispatch -> first DOM mutation that changes what is on screen.
    ui_response_ms: float | None = None
    #: dispatch -> first byte of the first request the action caused.
    network_first_byte_ms: float | None = None
    #: dispatch -> last response of the requests the action caused.
    network_complete_ms: float | None = None
    #: dispatch -> DOM quiescent for the settle window (the honest "done").
    state_complete_ms: float | None = None
    #: What a user would call "it responded": UI if painted, else network.
    perceived_ms: float | None = None

    mutation_count: int = 0
    request_count: int = 0
    failed_request_count: int = 0
    layout_shift: float | None = None
    long_task_ms: float | None = None
    #: Only populated for scroll actions.
    frame_count: int | None = None
    dropped_frames: int | None = None
    scroll_fps: float | None = None


class ActionRecord(BaseModel):
    """§9. One dispatched action and everything measured about it."""

    seq: int
    at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    state: AgentState = AgentState.INTERACTING
    intent: ActionIntent
    page_url: str = ""
    element_label: str = ""
    element_kind: ElementKind | None = None
    category: str = "other"
    expectation: str = ""
    observed: str = ""                    # what actually happened, in one line
    outcome: Outcome = Outcome.INCONCLUSIVE
    timing: InteractionTiming = Field(default_factory=InteractionTiming)
    url_changed: bool = False
    new_url: str | None = None
    console_errors: list[str] = Field(default_factory=list)
    note: str = ""

    @property
    def succeeded(self) -> bool:
        return self.outcome is Outcome.SUCCESS


class ThoughtEntry(BaseModel):
    """§16. What the interface shows. Never chain-of-thought.

    These are three statements of fact — what was on screen, what was
    dispatched, what came back. They are assembled from the ActionRecord in
    Python, so nothing here can describe an action that did not happen.
    """

    seq: int
    at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    state: AgentState
    observation: str
    action: str
    result: str = ""
    latency_ms: float | None = None
    ok: bool | None = None


# ══════════════════════════════════════════════════════ what was concluded


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"

    @property
    def rank(self) -> int:
        return {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2,
                "LOW": 1, "INFO": 0}[self.value]


class UXFinding(BaseModel):
    """§19. Generated from measurements, never from an opinion.

    `observed` and `expected` are both required and both must be quantified
    or quoted, so a reader can check the arithmetic.
    """

    id: str
    title: str
    category: str                         # navigation | search | form | ...
    severity: Severity
    observed: str
    expected: str
    impact: str
    recommendation: str
    evidence_seq: list[int] = Field(default_factory=list)   # ActionRecord.seq
    page_url: str = ""


class ScoreBand(str, Enum):
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"
    UNRATED = "UNRATED"                   # not enough observations to score


class ScoreComponent(BaseModel):
    """One dimension of the UX score, with the sample behind it."""

    name: str
    score: int | None                     # None when n == 0. Never 0-as-unknown.
    n: int = 0
    basis: str = ""                       # the sentence that explains the number


class UXScore(BaseModel):
    """§17. Deterministic. Computed in scoring.py, never by the model."""

    overall: int | None = None
    band: ScoreBand = ScoreBand.UNRATED
    components: list[ScoreComponent] = Field(default_factory=list)
    method: str = ""
    observations: int = 0


class JourneyOutcome(BaseModel):
    """How one journey actually went."""

    journey_id: str
    name: str
    goal: str
    completed: bool = False
    steps_planned: int = 0
    steps_attempted: int = 0
    steps_succeeded: int = 0
    abandoned_at: str | None = None
    abandon_reason: str | None = None
    action_seqs: list[int] = Field(default_factory=list)
    total_ms: float | None = None


class PageVisit(BaseModel):
    url: str
    title: str = ""
    visits: int = 1
    vitals: PageVitals = Field(default_factory=PageVitals)
    interactions: int = 0
    errors: int = 0


class BehaviourReport(BaseModel):
    """§18/§24. The whole session, as a user would describe it."""

    session_id: str
    target: str
    state: AgentState
    started_at: datetime
    duration_seconds: float = 0.0

    understanding: SiteUnderstanding = Field(default_factory=SiteUnderstanding)
    journeys: list[Journey] = Field(default_factory=list)
    journey_outcomes: list[JourneyOutcome] = Field(default_factory=list)

    actions: list[ActionRecord] = Field(default_factory=list)
    thoughts: list[ThoughtEntry] = Field(default_factory=list)
    pages: list[PageVisit] = Field(default_factory=list)

    score: UXScore = Field(default_factory=UXScore)
    findings: list[UXFinding] = Field(default_factory=list)
    summary: str = ""
    insights: dict[str, str] = Field(default_factory=dict)

    pages_explored: int = 0
    interactions_total: int = 0
    journeys_run: int = 0
    issues_detected: int = 0
    critical_issues: int = 0
    avg_response_ms: float | None = None
    requests_made: int = 0

    blocked_reason: str | None = None
    errors: list[str] = Field(default_factory=list)
    llm_model: str | None = None
    browser_version: str = ""


class BehaviourProgress(BaseModel):
    """One SSE frame. Mirrors web/lib/behaviourTypes.ts exactly."""

    state: AgentState
    pct: float = 0.0
    objective: str = ""
    current_action: str = ""
    page_url: str = ""
    pages_visited: int = 0
    interactions: int = 0
    actions_dispatched: int = 0
    avg_response_ms: float | None = None
    requests: int = 0
    journeys_done: int = 0
    journeys_total: int = 0
    thought: ThoughtEntry | None = None
    node: str | None = None               # journey-map node the agent occupies
    map_nodes: list[dict] | None = None   # emitted once, when the map is known
