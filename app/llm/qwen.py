"""Qwen3-Coder provider, over an Ollama-compatible local inference server.

Reliability notes — this is sized for a local 7B model, not a frontier one:

  * Structured output is enforced twice: Ollama `format: json`, then Pydantic.
  * Two failed parses returns None. The caller emits UNKNOWN. It never guesses.
  * Temperature 0, so results are stable run to run.
  * Prompts are small by construction (see evidence projection) — a typical
    evaluation is a few hundred tokens, not a whole evidence bundle.
"""
from __future__ import annotations

import logging
from typing import TypeVar

import httpx
from pydantic import BaseModel

from app.config.settings import LLMConfig
from app.llm.base import LLMUnavailable, parse_into

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class Qwen3CoderProvider:
    """LLMProvider implementation for Ollama's /api/chat."""

    def __init__(self, config: LLMConfig):
        self.config = config
        self.model = config.model
        self.endpoint = config.endpoint.rstrip("/")
        self._resolved = False

    # -- availability ------------------------------------------------------
    async def list_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.get(f"{self.endpoint}/api/tags")
                r.raise_for_status()
                return [m["name"] for m in r.json().get("models", [])]
        except Exception as exc:                                # noqa: BLE001
            raise LLMUnavailable(
                f"cannot reach inference server at {self.endpoint}: {exc}") from exc

    async def health_check(self) -> tuple[bool, str]:
        """Resolve the model, falling back if the configured one is absent.

        The repo's Ollama carries qwen2.5-coder:7b, not qwen3-coder. Rather
        than failing at the first evaluation, we report what is available and
        fall back — and the substitution is recorded in the assessment
        metadata, because GOV-05 and IN-07 both require the report to state
        which tools produced it.
        """
        try:
            available = await self.list_models()
        except LLMUnavailable as exc:
            return False, str(exc)

        def matches(name: str, want: str) -> bool:
            return name == want or name.split(":")[0] == want.split(":")[0]

        for candidate in [self.config.model, *self.config.fallback_models]:
            for name in available:
                if matches(name, candidate):
                    if name != self.config.model:
                        log.warning(
                            "configured model %r not present; using %r instead",
                            self.config.model, name)
                    self.model = name
                    self._resolved = True
                    return True, f"using model {name}"
        return False, (f"none of {[self.config.model, *self.config.fallback_models]} "
                       f"available; server has {available}")

    # -- completion --------------------------------------------------------
    async def complete(self, system: str, user: str, *,
                       json_mode: bool = False) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "stream": False,
            "options": {"temperature": self.config.temperature},
        }
        if json_mode:
            payload["format"] = "json"
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as c:
                r = await c.post(f"{self.endpoint}/api/chat", json=payload)
                r.raise_for_status()
                return r.json().get("message", {}).get("content", "")
        except Exception as exc:                                # noqa: BLE001
            raise LLMUnavailable(f"completion failed: {exc}") from exc

    async def complete_structured(self, system: str, user: str,
                                  schema: type[T], retries: int | None = None
                                  ) -> T | None:
        """Return a validated object, or None. Never a guess."""
        attempts = (self.config.max_retries if retries is None else retries) + 1
        for attempt in range(1, attempts + 1):
            try:
                raw = await self.complete(system, user, json_mode=True)
            except LLMUnavailable as exc:
                log.warning("attempt %d/%d: %s", attempt, attempts, exc)
                continue
            if (obj := parse_into(raw, schema)) is not None:
                return obj
            log.debug("attempt %d/%d: response did not validate against %s",
                      attempt, attempts, schema.__name__)
        return None


def build_provider(config: LLMConfig):
    """Factory. Add future providers here; callers stay unchanged."""
    if config.provider in ("qwen", "ollama"):
        return Qwen3CoderProvider(config)
    raise ValueError(f"unknown LLM provider: {config.provider!r}")
