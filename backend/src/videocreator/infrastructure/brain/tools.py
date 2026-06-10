"""Tool registry for the Brain agent.

A Tool is a name + JSON schema + async callable. Internal capabilities
(analyze_video, search_trends, format library search) register here; external
MCP servers can be wrapped into the same shape later.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

ToolFn = Callable[..., Awaitable[Any]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    json_schema: dict[str, Any]
    fn: ToolFn


class ToolRegistry:
    """Named collection of tools exposed to the agent."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    @property
    def schemas(self) -> list[dict[str, Any]]:
        """Tool declarations in the function-calling format LLMs expect."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.json_schema,
            }
            for t in self._tools.values()
        ]

    @property
    def names(self) -> list[str]:
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)


__all__ = ["Tool", "ToolFn", "ToolRegistry"]
