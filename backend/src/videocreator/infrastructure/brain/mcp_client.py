"""MCP bridge — plug external MCP servers into the Brain agent (§12.4).

Trend sources churn like video models; MCP makes them pluggable: a new
platform ships an MCP server → the brain sees it without touching the core.
The `mcp` package is a lazy optional dep: without it the bridge reports
unavailable and the agent runs on internal tools only (local-first).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from videocreator.infrastructure.brain.tools import Tool, ToolRegistry
from videocreator.shared.logging import get_logger

log = get_logger(__name__)


def mcp_available() -> bool:
    try:
        import mcp  # noqa: F401
    except ImportError:
        return False
    return True


@dataclass(frozen=True)
class McpServerSpec:
    """How to launch one stdio MCP server."""

    name: str
    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] | None = None


class McpToolBridge:
    """Wraps an MCP session's tools as Brain `Tool`s.

    The session object is injectable for tests; production uses
    `connect_stdio()` to spawn the server process.
    """

    def __init__(self, server_name: str, session: Any) -> None:
        self._server = server_name
        self._session = session

    async def load_tools(self, registry: ToolRegistry) -> int:
        """Register every tool the server exposes. Returns count registered."""
        try:
            listing = await self._session.list_tools()
        except Exception as e:
            log.warning("mcp.list_tools_failed", server=self._server, error=str(e))
            return 0

        count = 0
        for t in getattr(listing, "tools", []) or []:
            name = f"{self._server}.{t.name}"
            schema = getattr(t, "inputSchema", None) or {"type": "object"}
            registry.register(Tool(
                name=name,
                description=getattr(t, "description", "") or "",
                json_schema=schema,
                fn=self._make_caller(t.name),
            ))
            count += 1
        log.info("mcp.tools_loaded", server=self._server, count=count)
        return count

    def _make_caller(self, tool_name: str) -> Any:
        async def call(**kwargs: Any) -> Any:
            result = await self._session.call_tool(tool_name, arguments=kwargs)
            # MCP results carry a content list; flatten text blocks.
            content = getattr(result, "content", result)
            if isinstance(content, list):
                texts = [getattr(c, "text", str(c)) for c in content]
                return "\n".join(texts)
            return content
        return call


async def connect_stdio(spec: McpServerSpec) -> McpToolBridge | None:
    """Spawn a stdio MCP server and return a connected bridge.

    Returns None (logged, never raises) when `mcp` is missing or the server
    fails to start — the brain degrades to internal tools.
    """
    try:
        from mcp import ClientSession, StdioServerParameters  # type: ignore[import-untyped]
        from mcp.client.stdio import stdio_client  # type: ignore[import-untyped]
    except ImportError:
        log.info("mcp.disabled", reason="mcp package not installed")
        return None
    try:
        params = StdioServerParameters(
            command=spec.command, args=list(spec.args), env=spec.env,
        )
        read, write = await stdio_client(params).__aenter__()
        session = ClientSession(read, write)
        await session.initialize()
        return McpToolBridge(spec.name, session)
    except Exception as e:
        log.warning("mcp.connect_failed", server=spec.name, error=str(e))
        return None


__all__ = ["McpServerSpec", "McpToolBridge", "connect_stdio", "mcp_available"]
