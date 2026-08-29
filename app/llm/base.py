"""LLMProvider abstraction.

Nothing outside app/llm/ imports a Qwen symbol. Swapping the model must not
touch the browser tools, the rule engine, the statistics engine or the
repository layer.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.S)


class LLMUnavailable(Exception):
    """The inference server could not be reached or the model is missing."""


class LLMProvider(Protocol):
    """The whole surface the rest of the system may use."""

    model: str

    async def complete(self, system: str, user: str) -> str: ...

    async def complete_structured(self, system: str, user: str,
                                  schema: type[T], retries: int = 2) -> T | None: ...

    async def health_check(self) -> tuple[bool, str]: ...


def extract_json(text: str) -> dict | None:
    """Pull a JSON object out of a model response.

    Small local models wrap JSON in prose or fences even when told not to.
    We try, in order: whole string, fenced block, first balanced {...}.
    Returns None rather than raising — the caller degrades to UNKNOWN.
    """
    if not text:
        return None
    candidates: list[str] = [text.strip()]
    if m := _FENCE_RE.search(text):
        candidates.append(m.group(1))
    start = text.find("{")
    if start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start:i + 1])
                    break
    for c in candidates:
        try:
            parsed = json.loads(c)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def parse_into(text: str, schema: type[T]) -> T | None:
    """Parse a model response into a Pydantic schema, or return None."""
    data = extract_json(text)
    if data is None:
        log.debug("no JSON object found in model response")
        return None
    try:
        return schema(**data)
    except ValidationError as exc:
        log.debug("model response failed schema validation: %s", exc)
        return None
