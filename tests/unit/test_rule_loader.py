"""Rule loader: the pack is data, and it must parse exactly."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app.models.rules import Automation, Severity
from app.models.rules import TestLayer as Layer
from app.tools.rules import (RuleParseError, discover_rules, load_rules,
                             parse_markdown_rule, resolve_rules_dir,
                             validate_rule)

ROOT = Path(__file__).resolve().parents[2]


def test_loads_exactly_144_controls_from_17_families():
    """The pack's own README claims 17 families / 144 controls."""
    families, rules = load_rules(ROOT, "Rules")
    assert len(families) == 17
    assert len(rules) == 144


def test_meta_files_contribute_no_controls():
    """00, 18, 19, 20 carry no 'Control family:' marker."""
    for name in ("00_README.md", "18_rule_object_schema.md",
                 "19_test_modes_safety.md", "20_framework_mapping.md"):
        assert parse_markdown_rule(ROOT / "Rules" / name, root=ROOT) is None


def test_all_21_markdown_files_are_discovered():
    assert len(discover_rules(ROOT, "Rules")) == 21


def test_automation_tier_distribution_matches_the_pack():
    _, rules = load_rules(ROOT, "Rules")
    counts: dict[str, int] = {}
    for r in rules:
        counts[r.automation.value] = counts.get(r.automation.value, 0) + 1
    assert counts == {"P": 25, "P/M": 14, "M/P": 3, "M": 96, "No": 6}


def test_every_rule_is_well_formed():
    _, rules = load_rules(ROOT, "Rules")
    problems = {r.control_id: validate_rule(r) for r in rules}
    assert not {k: v for k, v in problems.items() if v}


def test_control_ids_are_unique():
    _, rules = load_rules(ROOT, "Rules")
    ids = [r.control_id for r in rules]
    assert len(ids) == len(set(ids))


def test_test_layer_is_derived_from_automation_tier():
    assert Layer.from_automation(Automation.PASSIVE) is Layer.L1
    assert Layer.from_automation(Automation.HYBRID) is Layer.L2
    assert Layer.from_automation(Automation.HYBRID_M) is Layer.L2
    assert Layer.from_automation(Automation.MANUAL) is Layer.L3
    assert Layer.from_automation(Automation.NOT_PROVABLE) is Layer.L4


def test_only_fully_passive_rules_skip_authorization():
    _, rules = load_rules(ROOT, "Rules")
    for r in rules:
        assert r.requires_authorization == (not r.automation.is_fully_passive)


def test_source_line_points_at_the_real_row():
    """IN-07 requires evidence traceable to the tested asset/version."""
    _, rules = load_rules(ROOT, "Rules")
    web05 = next(r for r in rules if r.control_id == "WEB-05")
    line = (ROOT / web05.source_file).read_text().splitlines()[web05.source_line - 1]
    assert line.startswith("| WEB-05 |")


def test_content_hash_tracks_text_not_location():
    _, rules = load_rules(ROOT, "Rules")
    a = next(r for r in rules if r.control_id == "NET-01")
    b = a.model_copy(deep=True)
    assert a.content_hash == b.content_hash
    b.source_file = "somewhere/else.md"
    assert a.content_hash == b.content_hash        # location is irrelevant
    b.pass_criteria = "something different"
    assert a.content_hash != b.content_hash        # wording is not


# --- extensibility: a new family file needs no code change ---------------

NEW_FAMILY = textwrap.dedent("""\
    # Experimental Controls

    > Rule pack version: `2026-08-28`
    > Control family: `EXP`
    > Purpose: Demonstrates that adding a family file requires no code change.

    ## Control rules

    | ID | Control / Rule | Test method | PASS criteria | Evidence | Auto? | Severity |
    |---|---|---|---|---|:---:|---|
    | EXP-01 | A brand new control. | Inspect response header. | Header present. | Headers | P | High |
    | EXP-02 | A second new control. | Manual review. | Documented. | Policy | No | Low |
    """)


def test_a_new_family_file_is_picked_up_with_zero_code_changes(tmp_path):
    rules_dir = tmp_path / "Rules"
    rules_dir.mkdir()
    (rules_dir / "21_experimental.md").write_text(NEW_FAMILY)

    families, rules = load_rules(tmp_path, "Rules")
    assert len(families) == 1
    assert [r.control_id for r in rules] == ["EXP-01", "EXP-02"]
    assert rules[0].automation is Automation.PASSIVE
    assert rules[0].severity is Severity.HIGH
    assert rules[0].test_layer is Layer.L1
    assert rules[1].test_layer is Layer.L4
    assert rules[0].control_domain == "experimental"


def test_malformed_row_is_skipped_not_fatal(tmp_path):
    """One bad row must not lose the rest of the file."""
    rules_dir = tmp_path / "Rules"
    rules_dir.mkdir()
    (rules_dir / "01_broken.md").write_text(
        NEW_FAMILY + "| EXP-03 | too | few | cells |\n")
    _, rules = load_rules(tmp_path, "Rules")
    assert [r.control_id for r in rules] == ["EXP-01", "EXP-02"]


def test_unknown_automation_value_degrades_to_manual(tmp_path):
    rules_dir = tmp_path / "Rules"
    rules_dir.mkdir()
    (rules_dir / "01_odd.md").write_text(
        NEW_FAMILY.replace("| P | High |", "| WAT | High |"))
    _, rules = load_rules(tmp_path, "Rules")
    assert rules[0].automation is Automation.MANUAL


# --- the Rules/ vs rules/ case problem -----------------------------------

def test_rules_directory_resolves_case_insensitively(tmp_path):
    """The repo ships `Rules/`; a hardcoded lowercase path breaks Linux CI."""
    (tmp_path / "Rules").mkdir()
    assert resolve_rules_dir(tmp_path, "rules").name == "Rules"
    assert resolve_rules_dir(tmp_path, "Rules").name == "Rules"
    assert resolve_rules_dir(tmp_path, "RULES").name == "Rules"


def test_missing_rules_directory_raises_clearly(tmp_path):
    with pytest.raises(RuleParseError, match="not found"):
        resolve_rules_dir(tmp_path, "NoSuchDir")
