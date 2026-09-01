"""Agent Memory — §21.

Without this the agent is a random walk: it re-clicks the same nav link,
re-reads the same page, and reports six copies of one finding. Memory is what
turns the loop into exploration.

Three things are remembered and each prevents a specific failure:

  * where it has BEEN, keyed on the structural fingerprint as well as the
    URL — so ten product pages that differ only by SKU are recognised as one
    kind of place, and the agent moves on instead of grinding the catalogue.
  * what it has TRIED, keyed on (place, element label) — so a control that
    did nothing is not pressed again, and a menu is not opened twice.
  * what it has LEARNED — the affordances it can name, which is what lets a
    later journey say "search exists" without re-discovering it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse, urlunparse

from app.behaviour.models import (ActionKind, ActionRecord, Outcome, PageModel,
                                  PageVisit)

#: Actions that COMMIT to something. Only these can mark a control dead: a
#: hover that opens no menu says nothing about whether clicking it works, and
#: recording it as dead makes the agent refuse to click a perfectly good
#: navigation button for the rest of the session.
_PRESSING = {ActionKind.CLICK, ActionKind.SUBMIT_SEARCH,
             ActionKind.SELECT_OPTION, ActionKind.CHECK,
             ActionKind.PLAY_MEDIA, ActionKind.PAUSE_MEDIA,
             ActionKind.PRESS_KEY, ActionKind.TYPE}


def normalise_url(url: str) -> str:
    """Drop the fragment and trailing slash; keep the query.

    A fragment is the same document. A query is usually not — `?page=2` and
    `?colour=blue` are different places to a user, and treating them as one
    would make the agent think it had already been somewhere it had not.
    """
    try:
        p = urlparse(url)
    except ValueError:
        return url
    path = p.path.rstrip("/") or "/"
    return urlunparse((p.scheme, p.netloc, path, "", p.query, ""))


@dataclass
class AgentMemory:
    """Session memory. Pure Python; nothing here is model-generated."""

    visits: dict[str, PageVisit] = field(default_factory=dict)
    #: Structural fingerprint -> how many distinct URLs shared it.
    shapes: dict[str, set[str]] = field(default_factory=dict)
    #: (place key, element label) already acted on.
    tried: set[tuple[str, str]] = field(default_factory=set)
    #: Actions that produced nothing — never repeated, always reported.
    dead: set[tuple[str, str]] = field(default_factory=set)
    known: dict[str, str] = field(default_factory=dict)
    completed: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    #: Every URL the agent chose to navigate to, in order.
    trail: list[str] = field(default_factory=list)

    # ── places ───────────────────────────────────────────────────────────
    def place(self, page: PageModel) -> str:
        """The key the agent thinks in: a shape at a location."""
        return f"{normalise_url(page.url)}#{page.fingerprint[:8]}"

    def record_visit(self, page: PageModel) -> bool:
        """Register a page. Returns True the first time this URL is seen."""
        key = normalise_url(page.url)
        first = key not in self.visits
        if first:
            self.visits[key] = PageVisit(url=key, title=page.title,
                                         vitals=page.vitals)
        else:
            v = self.visits[key]
            v.visits += 1
            if page.vitals.load_ms is not None and v.vitals.load_ms is None:
                v.vitals = page.vitals
        if page.fingerprint:
            self.shapes.setdefault(page.fingerprint, set()).add(key)
        if key not in self.trail:
            self.trail.append(key)
        return first

    def seen_shape(self, page: PageModel) -> bool:
        """True when a page of this SHAPE has been explored before.

        The second product page teaches the agent almost nothing the first
        did not. This is the check that stops it finding out fifty times.
        """
        urls = self.shapes.get(page.fingerprint)
        return bool(urls) and normalise_url(page.url) not in urls

    def visit_count(self, url: str) -> int:
        v = self.visits.get(normalise_url(url))
        return v.visits if v else 0

    # ── actions ──────────────────────────────────────────────────────────
    def mark_tried(self, place: str, label: str) -> None:
        self.tried.add((place, label))

    def has_tried(self, place: str, label: str) -> bool:
        return (place, label) in self.tried

    def is_dead(self, place: str, label: str) -> bool:
        return (place, label) in self.dead

    def record_action(self, place: str, record: ActionRecord) -> None:
        label = record.element_label or record.intent.kind.value
        self.mark_tried(place, label)
        if (record.outcome in (Outcome.NO_RESPONSE, Outcome.ERROR)
                and record.intent.kind in _PRESSING):
            self.dead.add((place, label))
        url = normalise_url(record.page_url or "")
        if url in self.visits:
            self.visits[url].interactions += 1
            if record.console_errors:
                self.visits[url].errors += len(record.console_errors)

    # ── knowledge ────────────────────────────────────────────────────────
    def learn(self, fact: str, detail: str = "") -> None:
        self.known.setdefault(fact, detail)

    def complete(self, step: str) -> None:
        if step not in self.completed:
            self.completed.append(step)
        if step in self.pending:
            self.pending.remove(step)

    def defer(self, step: str) -> None:
        if step not in self.pending and step not in self.completed:
            self.pending.append(step)

    # ── the view the brain gets ──────────────────────────────────────────
    def brief(self) -> str:
        """A compact recollection for the planning prompt.

        Deliberately short. A model given fifty visited URLs starts planning
        around the list instead of around the page in front of it.
        """
        lines = []
        if self.trail:
            recent = [u.split("/", 3)[-1] or "/" for u in self.trail[-6:]]
            lines.append("visited: " + ", ".join(recent))
        if self.known:
            lines.append("known: " + ", ".join(list(self.known)[:8]))
        if self.completed:
            lines.append("completed: " + ", ".join(self.completed[-6:]))
        if self.pending:
            lines.append("pending: " + ", ".join(self.pending[:4]))
        if self.dead:
            lines.append("no response from: " +
                         ", ".join(sorted({lbl for _, lbl in self.dead})[:4]))
        return "\n".join(lines) or "nothing yet — this is the first page."

    @property
    def pages_explored(self) -> int:
        return len(self.visits)
