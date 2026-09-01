"""Agent memory — what stops the loop becoming a random walk."""
from __future__ import annotations

from app.behaviour.memory import AgentMemory, normalise_url
from app.behaviour.models import (ActionIntent, ActionKind, ActionRecord,
                                  Outcome, PageModel)


def page(url: str, fingerprint: str = "abc123") -> PageModel:
    return PageModel(url=url, fingerprint=fingerprint)


def record(kind: ActionKind, outcome: Outcome, label: str) -> ActionRecord:
    return ActionRecord(seq=1, intent=ActionIntent(kind=kind, reason="x"),
                        element_label=label, outcome=outcome)


# ── URL identity ─────────────────────────────────────────────────────────

def test_a_fragment_is_the_same_page_and_a_query_is_not():
    assert normalise_url("https://x.test/a#top") == normalise_url("https://x.test/a")
    assert normalise_url("https://x.test/a/") == normalise_url("https://x.test/a")
    assert normalise_url("https://x.test/a?p=2") != normalise_url("https://x.test/a")


# ── places ───────────────────────────────────────────────────────────────

def test_a_page_is_only_new_once():
    m = AgentMemory()
    assert m.record_visit(page("https://x.test/")) is True
    assert m.record_visit(page("https://x.test/")) is False
    assert m.pages_explored == 1
    assert m.visit_count("https://x.test/") == 2


def test_pages_of_the_same_shape_are_recognised_as_one_kind_of_place():
    """Ten product pages that differ only by SKU teach the agent nothing new
    after the first. This is what stops it grinding the catalogue."""
    m = AgentMemory()
    m.record_visit(page("https://x.test/p/1", "shape-a"))
    assert m.seen_shape(page("https://x.test/p/2", "shape-a")) is True
    assert m.seen_shape(page("https://x.test/about", "shape-b")) is False


# ── actions ──────────────────────────────────────────────────────────────

def test_a_pressed_control_that_did_nothing_is_remembered_as_dead():
    m = AgentMemory()
    p = page("https://x.test/")
    m.record_visit(p)
    m.record_action(m.place(p),
                    record(ActionKind.CLICK, Outcome.NO_RESPONSE, "Subscribe"))
    assert m.is_dead(m.place(p), "Subscribe")


def test_a_hover_that_opened_nothing_does_not_condemn_the_control():
    """Most menus open on click. Marking the button dead after a hover makes
    the agent refuse to click a perfectly good control for the rest of the
    session — which is exactly what happened before this rule existed."""
    m = AgentMemory()
    p = page("https://x.test/")
    m.record_visit(p)
    m.record_action(m.place(p),
                    record(ActionKind.HOVER, Outcome.NO_RESPONSE, "Menu"))
    assert m.has_tried(m.place(p), "Menu")
    assert not m.is_dead(m.place(p), "Menu")


def test_a_working_control_is_tried_but_never_dead():
    m = AgentMemory()
    p = page("https://x.test/")
    m.record_visit(p)
    m.record_action(m.place(p),
                    record(ActionKind.CLICK, Outcome.SUCCESS, "Products"))
    assert m.has_tried(m.place(p), "Products")
    assert not m.is_dead(m.place(p), "Products")


def test_the_same_control_on_a_different_page_is_a_different_control():
    m = AgentMemory()
    a, b = page("https://x.test/a", "s1"), page("https://x.test/b", "s2")
    m.record_visit(a)
    m.record_visit(b)
    m.record_action(m.place(a),
                    record(ActionKind.CLICK, Outcome.NO_RESPONSE, "Next"))
    assert m.is_dead(m.place(a), "Next")
    assert not m.is_dead(m.place(b), "Next")


# ── knowledge ────────────────────────────────────────────────────────────

def test_completing_a_step_removes_it_from_pending():
    m = AgentMemory()
    m.defer("Add to cart")
    assert "Add to cart" in m.pending
    m.complete("Add to cart")
    assert "Add to cart" in m.completed and "Add to cart" not in m.pending
    m.defer("Add to cart")
    assert "Add to cart" not in m.pending, "a completed step is not re-queued"


def test_the_brief_stays_short_enough_to_prompt_with():
    m = AgentMemory()
    for i in range(60):
        m.record_visit(page(f"https://x.test/p{i}", f"s{i}"))
        m.complete(f"step {i}")
    brief = m.brief()
    assert len(brief) < 700, "a fifty-URL recollection crowds out the page"
    assert brief.count("\n") <= 6


def test_an_empty_memory_says_so_rather_than_returning_nothing():
    assert "first page" in AgentMemory().brief()
