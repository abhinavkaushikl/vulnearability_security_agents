"""Disk cache for rule interpretations.

Interpreting a Markdown control into a collector set is expensive and
perfectly repeatable, so it is done once ever and keyed on the rule's
content_hash. Editing a control's text in Markdown invalidates its entry
automatically; renaming a file does not.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from app.models.rules import RuleInterpretation

log = logging.getLogger(__name__)


class InterpretationCache:
    def __init__(self, directory: str | Path):
        self.dir = Path(directory)
        self.hits = 0
        self.misses = 0

    def _path(self, content_hash: str) -> Path:
        return self.dir / f"{content_hash}.json"

    def get(self, content_hash: str) -> RuleInterpretation | None:
        path = self._path(content_hash)
        if not path.exists():
            self.misses += 1
            return None
        try:
            obj = RuleInterpretation(**json.loads(path.read_text()))
            self.hits += 1
            return obj
        except Exception as exc:                                # noqa: BLE001
            log.debug("discarding corrupt cache entry %s: %s", path.name, exc)
            self.misses += 1
            return None

    def put(self, content_hash: str, interp: RuleInterpretation) -> None:
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            self._path(content_hash).write_text(interp.model_dump_json(indent=1))
        except Exception as exc:                                # noqa: BLE001
            log.debug("could not write cache entry: %s", exc)

    @property
    def stats(self) -> str:
        return f"{self.hits} hits, {self.misses} misses"
