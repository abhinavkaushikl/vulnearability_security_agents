"""RuleLoaderTool — parses the Markdown rule pack into SecurityRule objects.

The `Rules/` directory is the source of truth. This module contains NO
knowledge of any individual control: no `if control_id == "WEB-01"`. It parses
GFM tables and maps columns to fields. Dropping in `Rules/21_new_family.md`
with the same table shape adds those controls with zero code change.

File shape it expects (every family file follows it):

    # Network, DNS, TLS & Edge Security
    > Rule pack version: `2026-08-28`
    > Control family: `NET`
    > Purpose: DNS, TLS, HTTPS, HSTS, ...
    ## Control rules
    | ID | Control / Rule | Test method | PASS criteria | Evidence | Auto? | Severity |
    |---|---|---|---|---|:---:|---|
    | NET-01 | Redirect HTTP... | HTTP request comparison. | ... | ... | P | High |

Meta files (00, 18, 19, 20) carry no `Control family:` marker and are skipped.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from app.models.rules import (Automation, RuleFamily, SecurityRule, Severity,
                              TestLayer)

log = logging.getLogger(__name__)

_FAMILY_RE = re.compile(r"^>\s*Control family:\s*`([A-Z0-9]+)`", re.M)
_VERSION_RE = re.compile(r"^>\s*Rule pack version:\s*`([^`]+)`", re.M)
_PURPOSE_RE = re.compile(r"^>\s*Purpose:\s*(.+)$", re.M)
_ROW_RE = re.compile(r"^\|\s*([A-Z][A-Z0-9]*-\d+)\s*\|(.+?)\|?\s*$", re.M)
_SEPARATOR_RE = re.compile(r"^\|[\s:|-]+\|$")

#: Column order of the family tables. Positional by design — the pack is
#: consistent across all 17 files, and a header-name lookup would silently
#: mis-map if a file abbreviated a heading.
_COLUMNS = ("control", "test_method", "pass_criteria", "evidence",
            "automation", "severity")


class RuleParseError(Exception):
    """Raised only for a malformed *file*. A malformed row is skipped, logged."""


def resolve_rules_dir(root: Path, configured: str) -> Path:
    """Find the rules directory case-insensitively.

    The repository ships `Rules/` with a capital R. macOS resolves either
    spelling; Linux CI does not. Resolving by comparison rather than by
    literal path keeps the same code working on both.
    """
    # Scan FIRST, so we always return the real on-disk name. On macOS the
    # literal path `root/"rules"` resolves even though the directory is
    # `Rules/`, which would otherwise make source_file paths differ between
    # macOS and Linux for the same repository.
    want = configured.lower()
    try:
        for child in sorted(root.iterdir()):
            if child.is_dir() and child.name.lower() == want:
                return child
    except OSError as exc:
        raise RuleParseError(f"cannot read {root}: {exc}") from exc

    exact = root / configured
    if exact.is_dir():          # nested path such as "docs/Rules"
        return exact
    raise RuleParseError(
        f"rules directory {configured!r} not found under {root} "
        f"(looked case-insensitively)")


def _split_row(body: str) -> list[str]:
    """Split a table row body into trimmed cells."""
    return [c.strip() for c in body.split("|")]


def _control_domain(filename: str) -> str:
    """`02_network_dns_tls_edge.md` -> `network_dns_tls_edge`.

    Matches the `control_domain` example in Rules/18_rule_object_schema.md.
    """
    stem = Path(filename).stem
    return re.sub(r"^\d+_", "", stem)


def parse_markdown_rule(path: Path, root: Path | None = None) -> RuleFamily | None:
    """Parse one family file. Returns None for meta files (no family marker)."""
    text = path.read_text(encoding="utf-8")

    fam_match = _FAMILY_RE.search(text)
    if not fam_match:
        log.debug("skipping %s: no 'Control family:' marker (meta file)", path.name)
        return None
    family = fam_match.group(1)

    version = m.group(1) if (m := _VERSION_RE.search(text)) else ""
    purpose = m.group(1).strip() if (m := _PURPOSE_RE.search(text)) else ""
    title = text.lstrip().splitlines()[0].lstrip("# ").strip()
    rel = str(path.relative_to(root)) if root else str(path)

    fam = RuleFamily(
        family=family, title=title, purpose=purpose,
        control_domain=_control_domain(path.name),
        source_file=rel, pack_version=version,
    )

    lines = text.splitlines()
    for idx, line in enumerate(lines, start=1):
        m = _ROW_RE.match(line)
        if not m:
            continue
        control_id, body = m.group(1), m.group(2)
        cells = _split_row(body)

        if len(cells) < len(_COLUMNS):
            log.warning("%s:%d malformed row %s (%d cells, need %d) — skipped",
                        rel, idx, control_id, len(cells), len(_COLUMNS))
            continue

        values = dict(zip(_COLUMNS, cells))
        try:
            automation = Automation(values["automation"])
        except ValueError:
            log.warning("%s:%d %s: unknown Auto? value %r — treating as manual",
                        rel, idx, control_id, values["automation"])
            automation = Automation.MANUAL
        try:
            severity = Severity(values["severity"])
        except ValueError:
            log.warning("%s:%d %s: unknown severity %r — treating as Medium",
                        rel, idx, control_id, values["severity"])
            severity = Severity.MEDIUM

        fam.rules.append(SecurityRule(
            control_id=control_id,
            control=values["control"],
            test_method=values["test_method"],
            pass_criteria=values["pass_criteria"],
            evidence=values["evidence"],
            automation=automation,
            severity=severity,
            family=family,
            control_domain=fam.control_domain,
            family_purpose=purpose,
            source_file=rel,
            source_line=idx,
            pack_version=version,
            test_layer=TestLayer.from_automation(automation),
            # Every control above L1 needs written authorization (GOV-02).
            requires_authorization=not automation.is_fully_passive,
        ))

    if not fam.rules:
        log.warning("%s declares family %s but contains no control rows",
                    rel, family)
    return fam


def discover_rules(root: Path, directory: str = "Rules") -> list[Path]:
    """All .md files under the rules directory, recursively, in stable order."""
    rules_dir = resolve_rules_dir(root, directory)
    return sorted(rules_dir.rglob("*.md"))


def load_rules(
    root: Path | str = ".",
    directory: str = "Rules",
) -> tuple[list[RuleFamily], list[SecurityRule]]:
    """Load every control from every family file.

    Returns (families, flat_rules). Meta files are skipped automatically by
    virtue of carrying no `Control family:` marker — no filename allowlist is
    needed, so a renamed meta file still behaves correctly.
    """
    root = Path(root).resolve()
    families: list[RuleFamily] = []
    flat: list[SecurityRule] = []

    for path in discover_rules(root, directory):
        try:
            fam = parse_markdown_rule(path, root=root)
        except Exception as exc:                      # noqa: BLE001
            # A malformed file must not abort the assessment.
            log.error("failed to parse %s: %s", path.name, exc)
            continue
        if fam is None:
            continue
        families.append(fam)
        flat.extend(fam.rules)

    log.info("loaded %d controls from %d families", len(flat), len(families))
    return families, flat


def validate_rule(rule: SecurityRule) -> list[str]:
    """Return a list of problems with a parsed rule. Empty means well-formed."""
    problems = []
    if not rule.control.strip():
        problems.append("empty control text")
    if not rule.pass_criteria.strip():
        problems.append("empty PASS criteria")
    if not rule.evidence.strip():
        problems.append("empty evidence requirement")
    if not re.match(r"^[A-Z][A-Z0-9]*-\d+$", rule.control_id):
        problems.append(f"malformed control_id {rule.control_id!r}")
    return problems
