"""Agent Brain — the only component that reasons, and the only one that guesses.

It answers exactly four questions and nothing else:

    1. UNDERSTAND   what is this site, and what does a visitor come here for?
    2. PLAN         what journeys would a real visitor take?
    3. DECIDE       given this page and this step, what would a person do next?
    4. ADAPT        that did not work — what would a person do about it?

Every answer is a *choice from what the observer already saw*. The model
receives labels and refs; it cannot express a selector, a URL, or a script,
so the widest thing it can say is "act on element e12", and e12's safety
classification was decided before the model was called.

Every method has a complete deterministic fallback. `--no-llm` is not a
degraded mode that stops working — it is a heuristic agent that explores less
imaginatively and says so in the report (`derived_by: "heuristic"`). Nothing
downstream branches on which one produced the plan.
"""
from __future__ import annotations

import asyncio
import logging
import re

from pydantic import BaseModel, Field

from app.behaviour.models import (ActionIntent, ActionKind, ActionRecord,
                                  ElementKind, InteractiveElement, Journey,
                                  JourneyStep, PageModel, Risk, SiteKind,
                                  SiteUnderstanding)
from app.behaviour.memory import AgentMemory
from app.behaviour.prompts import (ADAPT_SYSTEM, DECIDE_SYSTEM,
                                   JOURNEYS_SYSTEM, SUMMARY_SYSTEM,
                                   UNDERSTAND_SYSTEM)

log = logging.getLogger(__name__)

#: How many elements the model is shown. Beyond this the list stops being a
#: menu and starts being a haystack, and small models pick worse from it.
MAX_ELEMENTS_IN_PROMPT = 46


# ══════════════════════════════════════════════════ model response schemas


class _Understanding(BaseModel):
    kind: str = "unknown"
    confidence: float = 0.0
    primary_goal: str = ""
    secondary_goals: list[str] = Field(default_factory=list)
    audience: str = ""
    key_affordances: list[str] = Field(default_factory=list)
    rationale: str = ""


class _Step(BaseModel):
    label: str = ""
    action: str = "click"
    target_hint: str = ""
    expectation: str = ""
    optional: bool = False


class _Journey(BaseModel):
    name: str = ""
    goal: str = ""
    priority: int = 1
    steps: list[_Step] = Field(default_factory=list)


class _Journeys(BaseModel):
    journeys: list[_Journey] = Field(default_factory=list)


class _Decision(BaseModel):
    action: str = "read"
    element_ref: str | None = None
    value: str | None = None
    amount: float | None = None
    expectation: str = ""
    reason: str = ""


class _Adaptation(BaseModel):
    diagnosis: str = ""
    recovery: str = "alternate_route"
    action: str = "read"
    element_ref: str | None = None
    value: str | None = None
    reason: str = ""


class _Summary(BaseModel):
    summary: str = ""


# ══════════════════════════════════════════════════ prompt rendering


def render_elements(page: PageModel, limit: int = MAX_ELEMENTS_IN_PROMPT) -> str:
    """The element menu the model chooses from.

    Ordered by how likely a visitor is to notice the control: things in the
    viewport first, then by vertical position. That ordering is itself a
    modelling decision — it is what makes "pick the first plausible one"
    behave like a person reading down the page rather than like a scraper.
    """
    els = [e for e in page.elements if e.visible and e.enabled]
    els.sort(key=lambda e: (not e.in_viewport, e.y, e.x))
    lines = []
    for e in els[:limit]:
        flag = "" if e.risk is Risk.SAFE else f"  {e.risk.value}"
        label = e.label or "(unnamed)"
        lines.append(f'{e.ref} [{e.kind.value}] "{label}"{flag}')
    if not lines:
        return "(no interactive elements are visible on this page)"
    hidden = len(els) - len(lines)
    if hidden > 0:
        lines.append(f"... and {hidden} more further down the page")
    return "\n".join(lines)


def render_page(page: PageModel) -> str:
    parts = [f"URL: {page.url}", f"Title: {page.title or '(none)'}"]
    if page.headings:
        parts.append("Headings: " + " | ".join(page.headings[:8]))
    if page.text_excerpt:
        parts.append("Text: " + page.text_excerpt[:600])
    parts.append(f"Scrollable: {'yes' if page.scrollable else 'no'}"
                 + (f" ({page.scroll_height:.0f}px of content, "
                    f"{page.viewport_height:.0f}px viewport)"
                    if page.scrollable else ""))
    if page.has_modal:
        parts.append("A dialog is currently open.")
    return "\n".join(parts)


# ══════════════════════════════════════════════════ heuristics
#
# These run when there is no model, and they also run whenever the model
# returns something that does not validate. They are not a stub: a run with
# --no-llm produces a real report, with `derived_by: heuristic` on everything
# the model would otherwise have decided.

_SIGNALS: list[tuple[SiteKind, re.Pattern, int]] = [
    (SiteKind.ECOMMERCE, re.compile(
        r"\b(add to (cart|bag|basket)|shopping (cart|bag|basket)|checkout|"
        r"shop now|free (shipping|delivery)|in stock|add to wishlist|sku|"
        r"our products|view (the )?(cart|basket)|proceed to checkout)\b",
        re.I), 3),
    # A cart and a price are the two things every shop has and very little
    # else does. Weak on their own, decisive together.
    (SiteKind.ECOMMERCE, re.compile(r"\b(cart|basket)\b", re.I), 2),
    (SiteKind.ECOMMERCE, re.compile(r"[£$€₹]\s?\d+(?:[.,]\d{2})?"), 2),
    (SiteKind.BANKING, re.compile(
        r"\b(account balance|routing|internet banking|net banking|ifsc|"
        r"credit card|debit card|loan|mortgage|fd rates|transfer funds)\b",
        re.I), 3),
    (SiteKind.SAAS, re.compile(
        r"\b(start (your )?free trial|book a demo|pricing|per (user|seat|month)"
        r"|integrations|api docs|sign up free|no credit card)\b", re.I), 2),
    (SiteKind.NEWS, re.compile(
        r"\b(latest news|breaking|top stories|opinion|editorial|subscribe to "
        r"the (paper|newsletter)|read more|published \d)\b", re.I), 2),
    (SiteKind.TRAVEL, re.compile(
        r"\b(book (a )?(flight|hotel|room|trip)|one[- ]way|round[- ]trip|"
        r"check[- ]in|departure|destination|passengers)\b", re.I), 3),
    (SiteKind.HEALTHCARE, re.compile(
        r"\b(book an appointment|find a doctor|patient portal|symptoms|"
        r"clinic|prescription|specialit(y|ies))\b", re.I), 3),
    (SiteKind.MARKETPLACE, re.compile(
        r"\b(sell (on|with)|become a seller|buyer protection|listings?|bids?)\b",
        re.I), 2),
    (SiteKind.SOCIAL, re.compile(
        r"\b(follow|followers|your feed|post an update|likes?|share this|"
        r"friend request)\b", re.I), 2),
    (SiteKind.GOVERNMENT, re.compile(
        r"\b(gov\.|ministry of|department of|citizen|public services|"
        r"apply for a (licence|license|permit)|tax return)\b", re.I), 3),
    (SiteKind.EDUCATION, re.compile(
        r"\b(courses?|enrol|enroll|syllabus|semester|admissions|students?|"
        r"faculty|tuition)\b", re.I), 2),
    (SiteKind.DOCUMENTATION, re.compile(
        r"\b(getting started|api reference|installation|npm install|pip "
        r"install|quickstart|changelog|on this page)\b", re.I), 3),
    (SiteKind.PORTFOLIO, re.compile(
        r"\b(my work|selected works|about me|get in touch|portfolio|"
        r"case stud(y|ies))\b", re.I), 2),
]


def heuristic_understanding(page: PageModel) -> SiteUnderstanding:
    """Classify from the words on the page and the controls that exist.

    Confidence is the winning score expressed against a fixed ceiling, so a
    site that matched one weak pattern reports 0.2, not "definitely a shop".
    """
    corpus = " ".join([page.title, " ".join(page.headings),
                       page.text_excerpt,
                       " ".join(e.label for e in page.elements[:120])])
    scores: dict[SiteKind, int] = {}
    for kind, rx, weight in _SIGNALS:
        hits = len(rx.findall(corpus))
        if hits:
            scores[kind] = scores.get(kind, 0) + weight * min(hits, 4)

    kinds = {e.kind for e in page.elements}
    if ElementKind.ADD_TO_CART in kinds:
        scores[SiteKind.ECOMMERCE] = scores.get(SiteKind.ECOMMERCE, 0) + 6

    affordances = []
    if ElementKind.SEARCH_INPUT in kinds:
        affordances.append("search")
    # A cart link on the landing page is as good a signal as an add-to-cart
    # button, and it is the one most shops actually show above the fold.
    if ElementKind.ADD_TO_CART in kinds or any(
            re.search(r"\b(cart|basket|bag)\b", e.label, re.I)
            for e in page.elements):
        affordances.append("cart")
    if any(f.has_password for f in page.forms):
        affordances.append("login")
    if ElementKind.PAGINATION in kinds:
        affordances.append("pagination")
    if ElementKind.MEDIA in kinds:
        affordances.append("media")
    if ElementKind.MENU_TOGGLE in kinds:
        affordances.append("menu")
    if page.forms:
        affordances.append("forms")
    if ElementKind.NAV in kinds:
        affordances.append("navigation")

    if not scores:
        kind, conf = SiteKind.UNKNOWN, 0.0
    else:
        kind = max(scores, key=lambda k: scores[k])
        conf = round(min(0.85, scores[kind] / 18.0), 2)

    goals = {
        SiteKind.ECOMMERCE: "find a product and add it to the cart",
        SiteKind.BANKING: "reach an account or a service",
        SiteKind.SAAS: "understand the product and what it costs",
        SiteKind.NEWS: "find and read a story",
        SiteKind.TRAVEL: "search for and choose a booking",
        SiteKind.HEALTHCARE: "find a service or book an appointment",
        SiteKind.MARKETPLACE: "find a listing",
        SiteKind.SOCIAL: "browse the feed",
        SiteKind.GOVERNMENT: "find a service or a form",
        SiteKind.PORTFOLIO: "look at the work and get in touch",
        SiteKind.EDUCATION: "find a course or programme",
        SiteKind.DOCUMENTATION: "find how to do one specific thing",
        SiteKind.UNKNOWN: "find what the site is for and act on it",
    }
    return SiteUnderstanding(
        kind=kind, confidence=conf, primary_goal=goals[kind],
        key_affordances=affordances,
        rationale=("derived from the page's own words and the controls that "
                   f"exist on it ({', '.join(affordances) or 'no notable controls'})"),
        derived_by="heuristic")


def _step(label: str, action: ActionKind, hint: str = "",
          expectation: str = "", optional: bool = False) -> JourneyStep:
    return JourneyStep(label=label, action=action.value, target_hint=hint,
                       expectation=expectation, optional=optional)


def heuristic_journeys(u: SiteUnderstanding, page: PageModel) -> list[Journey]:
    """Journeys built only from affordances that were actually observed.

    The brief is explicit that not every site is a shop, so nothing here is
    unconditional: a search journey exists only if a search box does.
    """
    aff = set(u.key_affordances)
    journeys: list[Journey] = []

    # Everyone does this one. It is also the only journey that is guaranteed
    # to be possible, which matters when the page has nothing else on it.
    orient = Journey(
        id="j-orient", name="First impression", priority=1,
        goal="find out what this site offers, the way a first-time visitor would",
        derived_by="heuristic",
        steps=[
            _step("Read what is above the fold", ActionKind.READ, "",
                  "the page has already painted something meaningful"),
            _step("Scroll down the page", ActionKind.SCROLL, "",
                  "more content appears smoothly as the page scrolls"),
            _step("Keep scrolling", ActionKind.SCROLL, "",
                  "the page keeps up; nothing jumps"),
            _step("Scroll back to the top", ActionKind.SCROLL_BACK, "",
                  "returning to the top is immediate"),
        ])
    journeys.append(orient)

    if "menu" in aff or "navigation" in aff:
        journeys.append(Journey(
            id="j-nav", name="Find the way around", priority=2,
            goal="use the navigation to reach a second page",
            derived_by="heuristic",
            steps=[
                # Optional: plenty of navigation is click-driven, and a
                # hover that opens nothing there is correct behaviour.
                _step("Hover the main navigation", ActionKind.HOVER, "menu",
                      "a menu opens without a perceptible delay", optional=True),
                _step("Open the menu", ActionKind.CLICK, "menu",
                      "the menu opens", optional=True),
                _step("Open a section", ActionKind.CLICK, "",
                      "the section page loads"),
                _step("Look at what is there", ActionKind.READ, "",
                      "the page is usable"),
                _step("Go back", ActionKind.BACK, "",
                      "returning is instant"),
            ]))

    if "search" in aff:
        journeys.append(Journey(
            id="j-search", name="Search for something", priority=2,
            goal="use search and get to a result",
            derived_by="heuristic",
            steps=[
                _step("Click the search box", ActionKind.CLICK, "search",
                      "the field takes focus immediately"),
                _step("Type a query", ActionKind.TYPE, "search",
                      "suggestions appear while typing, or the field keeps up"),
                _step("Submit the search", ActionKind.SUBMIT_SEARCH, "search",
                      "results appear"),
                _step("Open a result", ActionKind.CLICK, "", "the result loads",
                      optional=True),
            ]))

    if u.kind is SiteKind.ECOMMERCE and "cart" in aff:
        journeys.append(Journey(
            id="j-buy", name="Shop for a product", priority=1,
            goal="get from the homepage to a product in the cart",
            derived_by="heuristic",
            steps=[
                # No hint: the decision falls through to "the most prominent
                # thing not already tried", which is what a visitor scanning a
                # grid of products actually does.
                _step("Open a product", ActionKind.CLICK, "",
                      "the product page loads"),
                _step("Look at the product", ActionKind.SCROLL, "",
                      "the details and the price are visible"),
                _step("Choose an option", ActionKind.SELECT_OPTION,
                      "size colour quantity", "the choice registers",
                      optional=True),
                _step("Add it to the cart", ActionKind.CLICK, "add to cart",
                      "the cart acknowledges the item"),
                _step("Open the cart", ActionKind.CLICK, "cart",
                      "the cart shows the item that was added"),
            ]))

    if "login" in aff:
        journeys.append(Journey(
            id="j-auth", name="Reach the sign-in", priority=3,
            goal=("find the sign-in and see how it behaves — the agent never "
                  "submits credentials"),
            derived_by="heuristic",
            steps=[
                _step("Find the sign-in", ActionKind.CLICK, "sign in login",
                      "a sign-in form appears"),
                _step("Focus the first field", ActionKind.CLICK, "email user",
                      "the field takes focus and is labelled"),
                _step("Look at the form", ActionKind.READ, "",
                      "the form explains what it needs"),
            ]))

    if u.kind in (SiteKind.NEWS, SiteKind.DOCUMENTATION, SiteKind.EDUCATION):
        journeys.append(Journey(
            id="j-read", name="Read something", priority=2,
            goal="get from the front page into a piece of content and read it",
            derived_by="heuristic",
            steps=[
                _step("Open an article", ActionKind.CLICK, "",
                      "the article loads"),
                _step("Read it", ActionKind.READ, "", "the text is readable"),
                _step("Scroll through it", ActionKind.SCROLL, "",
                      "scrolling is smooth and nothing shifts"),
                _step("Go back", ActionKind.BACK, "", "returning is instant"),
            ]))

    if "media" in aff:
        journeys.append(Journey(
            id="j-media", name="Play the media", priority=4,
            goal="start a video or audio player and see how it responds",
            derived_by="heuristic",
            steps=[
                _step("Start playback", ActionKind.PLAY_MEDIA, "",
                      "playback starts"),
                _step("Pause it", ActionKind.PAUSE_MEDIA, "", "playback stops"),
            ]))

    journeys.sort(key=lambda j: j.priority)
    return journeys[:4]


#: Query terms are taken from the site's OWN words. A hardcoded "shoes" would
#: measure a zero-result page on most sites, which measures nothing.
_STOP = {"the", "and", "for", "with", "your", "you", "our", "are", "from",
         "this", "that", "all", "new", "get", "how", "what", "why", "shop",
         "more", "now", "home", "about", "menu", "search", "here", "can",
         "will", "has", "have", "was", "were", "not", "but", "its"}


def search_query(page: PageModel, understanding: SiteUnderstanding) -> str:
    """Invent a plausible query out of what the site itself says it sells.

    Two words, because a one-word query on a big catalogue measures the
    result page and a five-word query measures the empty-state page.
    """
    corpus = " ".join(page.headings[:10] + [
        e.label for e in page.elements
        if e.kind in (ElementKind.PRODUCT_CARD, ElementKind.NAV,
                      ElementKind.LINK)][:40])
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z-]{3,}", corpus)
             if w.lower() not in _STOP]
    seen: list[str] = []
    for w in words:
        if w.lower() not in {s.lower() for s in seen}:
            seen.append(w)
        if len(seen) == 2:
            break
    if seen:
        return " ".join(seen).lower()
    return {SiteKind.ECOMMERCE: "gift", SiteKind.NEWS: "today",
            SiteKind.DOCUMENTATION: "install"}.get(understanding.kind, "help")


def _match(elements: list[InteractiveElement], hint: str,
           kinds: tuple[ElementKind, ...] = ()) -> InteractiveElement | None:
    """Find the control a step is talking about.

    Scored rather than filtered: an exact label match beats a kind match beats
    a loose word match, and being in the viewport breaks ties — because that
    is the one a person would actually reach for.
    """
    words = [w for w in re.split(r"\W+", hint.lower()) if len(w) > 2]
    best: tuple[float, InteractiveElement] | None = None
    for el in elements:
        if el.risk is Risk.FORBIDDEN or not el.visible or not el.enabled:
            continue
        label = el.label.lower()
        kind_hit = bool(kinds) and el.kind in kinds
        word_hits = sum(1 for w in words if w in label)
        # A match needs a REASON: the right kind of control, or a word from
        # the hint in its label. Without this the tie-breakers alone can
        # carry an element over the line, and the agent "finds" a cookie
        # banner dismisser on a page that has no banner — then reports the
        # click that did nothing as the site's fault.
        if not kind_hit and word_hits == 0:
            continue
        score = 6.0 if kind_hit else 0.0
        if label == hint.lower():
            score += 10
        score += word_hits * 3
        if el.in_viewport:
            score += 1.5
        if el.risk is Risk.SENSITIVE:
            score -= 2
        if best is None or score > best[0]:
            best = (score, el)
    return best[1] if best and best[0] > 0 else None


_KIND_FOR_STEP: dict[str, tuple[ElementKind, ...]] = {
    "search": (ElementKind.SEARCH_INPUT,),
    "cart": (ElementKind.ADD_TO_CART,),
    "menu": (ElementKind.MENU_TOGGLE, ElementKind.NAV),
    "product": (ElementKind.PRODUCT_CARD,),
}


def heuristic_decision(page: PageModel, journey: Journey, step_index: int,
                       memory: AgentMemory, understanding: SiteUnderstanding
                       ) -> ActionIntent:
    """Choose the next action without a model. Deterministic and explainable."""
    if step_index >= len(journey.steps):
        return ActionIntent(kind=ActionKind.DONE, reason="the journey's steps are done")

    step = journey.steps[step_index]
    kind = ActionKind(step.action) if step.action in {
        k.value for k in ActionKind} else ActionKind.READ
    place = memory.place(page)

    hint = step.target_hint or step.label
    kinds = ()
    for word, ks in _KIND_FOR_STEP.items():
        if word in hint.lower():
            kinds = ks
            break

    el: InteractiveElement | None = None
    if kind in (ActionKind.CLICK, ActionKind.HOVER, ActionKind.TYPE,
                ActionKind.SUBMIT_SEARCH, ActionKind.SELECT_OPTION,
                ActionKind.CHECK, ActionKind.PLAY_MEDIA,
                ActionKind.PAUSE_MEDIA):
        if kind in (ActionKind.PLAY_MEDIA, ActionKind.PAUSE_MEDIA):
            kinds = (ElementKind.MEDIA,)
        if kind is ActionKind.SELECT_OPTION:
            kinds = (ElementKind.SELECT, ElementKind.QUANTITY)
        el = _match(page.actionable, hint, kinds)

        if el is None and kind is ActionKind.CLICK:
            # Nothing matched the hint. Take the most prominent thing the
            # agent has not already tried — which is what a person does when
            # the thing they were looking for is not where they expected.
            candidates = [e for e in page.actionable
                          if e.kind in (ElementKind.PRODUCT_CARD,
                                        ElementKind.LINK, ElementKind.NAV,
                                        ElementKind.BUTTON)
                          and not memory.has_tried(place, e.label)
                          and not memory.is_dead(place, e.label)
                          and e.in_viewport and e.label]
            candidates.sort(key=lambda e: (e.kind is not ElementKind.PRODUCT_CARD,
                                           e.y, e.x))
            el = candidates[0] if candidates else None

        if el is not None and memory.is_dead(place, el.label):
            el = None

    if el is None and kind in (ActionKind.CLICK, ActionKind.HOVER,
                               ActionKind.TYPE, ActionKind.SUBMIT_SEARCH,
                               ActionKind.SELECT_OPTION, ActionKind.CHECK,
                               ActionKind.PLAY_MEDIA, ActionKind.PAUSE_MEDIA):
        # The step is not possible here. Scrolling is what a person does when
        # they cannot see what they came for — and it is measured either way.
        return ActionIntent(
            kind=ActionKind.SCROLL, amount=0.9,
            expectation="the control this step needs comes into view",
            reason=(f"{step.label!r} is not reachable on this screen; "
                    "looking further down the page"),
            journey_id=journey.id, step_label=step.label)

    value = None
    if kind is ActionKind.TYPE:
        value = search_query(page, understanding) if (
            el and el.kind is ElementKind.SEARCH_INPUT) else "test"

    return ActionIntent(
        kind=kind,
        element_ref=el.ref if el else None,
        value=value,
        amount=0.85 if kind in (ActionKind.SCROLL, ActionKind.SCROLL_BACK) else None,
        expectation=step.expectation or "the site responds",
        reason=step.label,
        journey_id=journey.id,
        step_label=step.label)


# ══════════════════════════════════════════════════ the brain


class AgentBrain:
    """LLM-backed where a model is available, heuristic where it is not."""

    def __init__(self, provider=None, *, enabled: bool = True,
                 decide_with_model: bool = False,
                 call_timeout: float = 45.0):
        self.provider = provider
        self.enabled = bool(enabled and provider is not None)
        #: Whether the model is consulted for every individual step, or only
        #: for the plan and for recovery. See BehaviourConfig.llm_decides_steps
        #: — the default is off, and the reasoning is worth reading before
        #: turning it on.
        self.decide_with_model = decide_with_model
        #: A deadline on one model call. See BehaviourConfig.
        self.call_timeout = call_timeout
        self.model_calls = 0
        self.model_failures = 0
        self.model_timeouts = 0

    async def _ask(self, system: str, user: str, schema):
        """One model call, under a deadline. Never raises, never blocks a run.

        Returning None is the whole contract: every caller has a deterministic
        answer ready and uses it. A slow model degrades the plan's imagination,
        not the session.
        """
        if not self.enabled:
            return None
        self.model_calls += 1
        try:
            out = await asyncio.wait_for(
                self.provider.complete_structured(system, user, schema),
                timeout=self.call_timeout)
        except asyncio.TimeoutError:
            self.model_timeouts += 1
            self.model_failures += 1
            log.warning("model did not answer within %.0fs; using the "
                        "deterministic answer", self.call_timeout)
            return None
        except asyncio.CancelledError:
            raise
        except Exception as exc:                                # noqa: BLE001
            log.warning("brain call failed: %s", exc)
            self.model_failures += 1
            return None
        if out is None:
            self.model_failures += 1
        return out

    # ── 1. understand ────────────────────────────────────────────────────
    async def understand(self, page: PageModel) -> SiteUnderstanding:
        fallback = heuristic_understanding(page)
        user = (f"{render_page(page)}\n\nInteractive elements:\n"
                f"{render_elements(page, 34)}")
        out: _Understanding | None = await self._ask(
            UNDERSTAND_SYSTEM, user, _Understanding)
        if out is None:
            return fallback
        try:
            kind = SiteKind(out.kind.strip().lower())
        except ValueError:
            kind = fallback.kind
        return SiteUnderstanding(
            kind=kind,
            confidence=max(0.0, min(1.0, float(out.confidence or 0))),
            primary_goal=out.primary_goal.strip() or fallback.primary_goal,
            secondary_goals=[s for s in out.secondary_goals if s][:4],
            audience=out.audience.strip(),
            # The model may name affordances; the observed ones are the truth,
            # so the two are merged with the observation kept.
            key_affordances=sorted(set(fallback.key_affordances)
                                   | {a.lower() for a in out.key_affordances if a}),
            rationale=out.rationale.strip() or fallback.rationale,
            derived_by="llm")

    # ── 2. plan ──────────────────────────────────────────────────────────
    async def plan_journeys(self, u: SiteUnderstanding,
                            page: PageModel) -> list[Journey]:
        fallback = heuristic_journeys(u, page)
        user = (f"Site kind: {u.kind.value} (confidence {u.confidence})\n"
                f"Visitor's goal: {u.primary_goal}\n"
                f"Observed affordances: {', '.join(u.key_affordances) or 'none'}\n\n"
                f"{render_page(page)}\n\nInteractive elements:\n"
                f"{render_elements(page, 40)}")
        out: _Journeys | None = await self._ask(JOURNEYS_SYSTEM, user, _Journeys)
        if out is None or not out.journeys:
            return fallback

        valid = {k.value for k in ActionKind}
        journeys: list[Journey] = []
        for i, j in enumerate(out.journeys[:4]):
            steps = [
                JourneyStep(
                    label=s.label.strip() or f"step {n + 1}",
                    action=s.action.strip().lower()
                    if s.action.strip().lower() in valid else "read",
                    target_hint=s.target_hint.strip(),
                    expectation=s.expectation.strip(),
                    optional=bool(s.optional))
                for n, s in enumerate(j.steps[:8])]
            if not steps:
                continue
            journeys.append(Journey(
                id=f"j-{i + 1}", name=j.name.strip() or f"Journey {i + 1}",
                goal=j.goal.strip(), priority=max(1, int(j.priority or 1)),
                steps=steps, derived_by="llm"))
        if not journeys:
            return fallback
        # The orientation journey is always kept: it is the only one certain
        # to be executable, and its scroll measurements feed the scroll score.
        if not any(s.action in ("scroll", "scroll_back")
                   for j in journeys for s in j.steps):
            journeys.append(fallback[0])
        journeys.sort(key=lambda j: j.priority)
        return journeys

    # ── 3. decide ────────────────────────────────────────────────────────
    async def decide(self, page: PageModel, journey: Journey, step_index: int,
                     memory: AgentMemory, understanding: SiteUnderstanding,
                     recent: list[ActionRecord]) -> ActionIntent:
        fallback = heuristic_decision(page, journey, step_index, memory,
                                      understanding)
        if (not self.enabled or not self.decide_with_model
                or step_index >= len(journey.steps)):
            # The plan already came from the model. Walking it is resolution,
            # not judgement: match the step against the elements observed on
            # this page. One round trip per click buys very little and costs
            # the whole session.
            return fallback

        step = journey.steps[step_index]
        history = "\n".join(
            f"- {r.intent.kind.value} {r.element_label!r} -> {r.outcome.value}: "
            f"{r.observed[:90]}" for r in recent[-4:]) or "(nothing yet)"

        user = (
            f"Journey: {journey.name} — goal: {journey.goal}\n"
            f"Current step {step_index + 1}/{len(journey.steps)}: {step.label}\n"
            f"The step expects: {step.expectation or 'a visible response'}\n\n"
            f"What the agent knows so far:\n{memory.brief()}\n\n"
            f"The last few actions:\n{history}\n\n"
            f"{render_page(page)}\n\nElements on this page:\n"
            f"{render_elements(page)}")

        out: _Decision | None = await self._ask(DECIDE_SYSTEM, user, _Decision)
        intent = self._to_intent(out, page, journey, step, fallback)
        if intent.kind is ActionKind.TYPE and not intent.value:
            intent.value = search_query(page, understanding)
        return intent

    def _to_intent(self, out, page: PageModel, journey: Journey,
                   step: JourneyStep, fallback: ActionIntent) -> ActionIntent:
        """Validate a model decision against the page. Reject, never repair.

        A ref the observer did not emit, or an element the classifier marked
        FORBIDDEN, means the model has left the inventory. There is no attempt
        to guess what it meant — the deterministic decision is used instead,
        and the substitution is invisible downstream because both are the same
        kind of object.
        """
        if out is None:
            return fallback
        try:
            kind = ActionKind(out.action.strip().lower())
        except ValueError:
            return fallback

        el = page.by_ref(out.element_ref) if out.element_ref else None
        if out.element_ref and el is None:
            log.debug("brain named ref %s which is not on the page; "
                      "falling back", out.element_ref)
            return fallback
        if el is not None and el.risk is Risk.FORBIDDEN:
            log.info("brain chose a forbidden control (%s); falling back",
                     el.label)
            return fallback
        needs_element = kind in (
            ActionKind.CLICK, ActionKind.HOVER, ActionKind.TYPE,
            ActionKind.SUBMIT_SEARCH, ActionKind.SELECT_OPTION,
            ActionKind.CHECK, ActionKind.PLAY_MEDIA, ActionKind.PAUSE_MEDIA)
        if needs_element and el is None:
            return fallback

        return ActionIntent(
            kind=kind,
            element_ref=el.ref if el else None,
            value=(out.value or None),
            amount=(float(out.amount) if out.amount else None),
            expectation=out.expectation.strip() or step.expectation,
            reason=out.reason.strip() or step.label,
            journey_id=journey.id,
            step_label=step.label)

    # ── 4. adapt ─────────────────────────────────────────────────────────
    async def adapt(self, page: PageModel, journey: Journey, step_index: int,
                    failed: ActionRecord, memory: AgentMemory,
                    understanding: SiteUnderstanding
                    ) -> tuple[str, str, ActionIntent | None]:
        """(diagnosis, recovery, next intent or None to abandon)."""
        diagnosis, recovery, intent = self._heuristic_adapt(
            page, journey, step_index, failed, memory, understanding)
        if not self.enabled:
            return diagnosis, recovery, intent

        step = journey.steps[step_index] if step_index < len(journey.steps) else None
        user = (
            f"Journey: {journey.name}\n"
            f"Step: {step.label if step else '(past the last step)'}\n"
            f"Action attempted: {failed.intent.kind.value} on "
            f"{failed.element_label or '(no element)'}\n"
            f"Expected: {failed.expectation or 'a visible response'}\n"
            f"Observed: {failed.observed}\n"
            f"Outcome: {failed.outcome.value}\n\n"
            f"{render_page(page)}\n\nElements now on the page:\n"
            f"{render_elements(page)}")

        out: _Adaptation | None = await self._ask(ADAPT_SYSTEM, user, _Adaptation)
        if out is None:
            return diagnosis, recovery, intent
        if out.recovery.strip().lower() == "abandon":
            return (out.diagnosis.strip() or diagnosis, "abandon", None)

        chosen = self._to_intent(
            _Decision(action=out.action, element_ref=out.element_ref,
                      value=out.value, expectation="the recovery works",
                      reason=out.reason or "recovering from a failed action"),
            page, journey,
            step or JourneyStep(label="recovery", action="read"),
            intent or ActionIntent(kind=ActionKind.READ,
                                   reason="waiting before trying again"))
        return (out.diagnosis.strip() or diagnosis,
                out.recovery.strip().lower() or recovery, chosen)

    def _heuristic_adapt(self, page: PageModel, journey: Journey,
                         step_index: int, failed: ActionRecord,
                         memory: AgentMemory, understanding: SiteUnderstanding
                         ) -> tuple[str, str, ActionIntent | None]:
        """§22, without a model. The order of these checks is the diagnosis."""
        # An overlay is the single most common reason a click does nothing.
        overlay = _match(page.actionable, "accept close dismiss got it agree ok",
                         (ElementKind.MODAL_CLOSE,))
        if page.has_modal or overlay is not None:
            if overlay is not None:
                return ("something is covering the page",
                        "dismiss_overlay",
                        ActionIntent(kind=ActionKind.CLICK,
                                     element_ref=overlay.ref,
                                     expectation="the overlay closes",
                                     reason="clearing what is in the way",
                                     journey_id=journey.id))

        if failed.outcome.value == "NO_RESPONSE":
            return ("the control did not respond at all",
                    "alternate_route",
                    heuristic_decision(page, journey, step_index + 1, memory,
                                       understanding))

        if failed.url_changed:
            # Landed somewhere unplanned. Continue from where it actually is.
            return (f"the site went to {failed.new_url} instead",
                    "alternate_route",
                    heuristic_decision(page, journey, step_index + 1, memory,
                                       understanding))

        if failed.outcome.value == "ERROR":
            return ("the action could not be dispatched — the element moved "
                    "or something is over it",
                    "wait",
                    ActionIntent(kind=ActionKind.READ,
                                 expectation="the page settles",
                                 reason="waiting for the page to settle",
                                 journey_id=journey.id))

        return ("the response was not what a visitor would expect",
                "alternate_route",
                heuristic_decision(page, journey, step_index + 1, memory,
                                   understanding))

    # ── 5. prose ─────────────────────────────────────────────────────────
    async def summarise(self, facts: str, deterministic: str) -> str:
        """One call. It cannot alter a measurement, a finding or a score."""
        out: _Summary | None = await self._ask(SUMMARY_SYSTEM, facts, _Summary)
        text = (out.summary.strip() if out and out.summary else "")
        return text or deterministic
