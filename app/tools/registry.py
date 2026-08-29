"""Tool Registry — the extension point for agentic tool calling.

Every capability the system has is registered here with a name, description,
category, and callable. The orchestrator agent discovers tools from this
registry and decides which to call based on the target and the rules.

Adding a new tool:
    from app.tools.registry import registry, ToolCategory

    @registry.tool(
        name="my_new_check",
        category=ToolCategory.COLLECTOR,
        description="Checks something new on the target",
        tags=["security", "headers"],
    )
    async def my_new_check(url: str) -> dict:
        ...
        return {"found": True, "detail": "..."}
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

log = logging.getLogger(__name__)


class ToolCategory(str, Enum):
    """What kind of tool is this?"""

    COLLECTOR = "collector"          # gathers raw evidence from the target
    ANALYZER = "analyzer"            # derives insights from collected evidence
    EVALUATOR = "evaluator"          # evaluates a rule against evidence
    REPORTER = "reporter"            # generates output artifacts
    NETWORK = "network"              # out-of-band network checks (TLS, DNS)
    BROWSER = "browser"              # in-browser inspection
    PERFORMANCE = "performance"      # performance measurement
    UTILITY = "utility"              # helper tools (screenshots, statistics)


@dataclass
class ToolSpec:
    """One registered tool."""

    name: str
    description: str
    category: ToolCategory
    fn: Callable[..., Any]
    parameters: dict[str, str] = field(default_factory=dict)
    requires_browser: bool = False
    requires_network: bool = False
    collector_code: str | None = None
    tags: list[str] = field(default_factory=list)
    enabled: bool = True

    def describe_for_llm(self) -> str:
        """One-line description the orchestrator LLM sees."""
        params = ", ".join(f"{k}" for k in self.parameters) if self.parameters else "none"
        flags = []
        if self.requires_browser:
            flags.append("needs-browser")
        if self.requires_network:
            flags.append("needs-network")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        return f"{self.name} ({self.category.value}{flag_str}) — {self.description}  params: ({params})"


class ToolRegistry:
    """Central registry of all capabilities.

    The orchestrator discovers tools from here. New tools register via the
    `@registry.tool(...)` decorator or by calling `registry.register(spec)`.
    """

    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}

    # -- registration ------------------------------------------------------

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            log.warning("overwriting tool %r", spec.name)
        self._tools[spec.name] = spec
        log.debug("registered tool %s [%s]", spec.name, spec.category.value)

    def tool(
        self,
        name: str,
        *,
        category: ToolCategory,
        description: str,
        parameters: dict[str, str] | None = None,
        requires_browser: bool = False,
        requires_network: bool = False,
        collector_code: str | None = None,
        tags: list[str] | None = None,
    ):
        """Decorator for registering a function as a tool."""
        def decorator(fn):
            self.register(ToolSpec(
                name=name,
                description=description,
                category=category,
                fn=fn,
                parameters=parameters or {},
                requires_browser=requires_browser,
                requires_network=requires_network,
                collector_code=collector_code,
                tags=tags or [],
            ))
            return fn
        return decorator

    # -- discovery ---------------------------------------------------------

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def list_all(self) -> list[ToolSpec]:
        return [t for t in self._tools.values() if t.enabled]

    def list_by_category(self, category: ToolCategory) -> list[ToolSpec]:
        return [t for t in self._tools.values() if t.category == category and t.enabled]

    def list_by_tag(self, tag: str) -> list[ToolSpec]:
        return [t for t in self._tools.values() if tag in t.tags and t.enabled]

    def list_names(self) -> list[str]:
        return [t.name for t in self._tools.values() if t.enabled]

    def describe_all_for_llm(self) -> str:
        """Full tool listing formatted for the orchestrator prompt."""
        lines: list[str] = []
        by_cat: dict[ToolCategory, list[ToolSpec]] = {}
        for t in self._tools.values():
            if t.enabled:
                by_cat.setdefault(t.category, []).append(t)
        for cat in ToolCategory:
            tools = by_cat.get(cat, [])
            if not tools:
                continue
            lines.append(f"\n{cat.value.upper()} TOOLS:")
            for t in sorted(tools, key=lambda x: x.name):
                lines.append(f"  - {t.describe_for_llm()}")
        return "\n".join(lines)

    def describe_category_for_llm(self, category: ToolCategory) -> str:
        tools = self.list_by_category(category)
        return "\n".join(f"  - {t.describe_for_llm()}" for t in tools)

    # -- execution ---------------------------------------------------------

    async def call(self, name: str, **kwargs) -> Any:
        """Call a tool by name. The orchestrator dispatches through here."""
        spec = self._tools.get(name)
        if not spec:
            raise ToolNotFound(f"no tool named {name!r}; available: {self.list_names()}")
        if not spec.enabled:
            raise ToolDisabled(f"tool {name!r} is disabled")
        log.info("tool_call: %s(%s)", name,
                 ", ".join(f"{k}=..." for k in kwargs))
        return await spec.fn(**kwargs)

    def disable(self, name: str) -> None:
        if spec := self._tools.get(name):
            spec.enabled = False

    def enable(self, name: str) -> None:
        if spec := self._tools.get(name):
            spec.enabled = True

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools


class ToolNotFound(Exception):
    pass


class ToolDisabled(Exception):
    pass


# ---------------------------------------------------------------------------
# Global registry — import this everywhere
# ---------------------------------------------------------------------------
registry = ToolRegistry()
