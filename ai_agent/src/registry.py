"""McpClientRegistry: connect to every server in config_servers.json,
merge their tools into one namespaced catalog, and dispatch calls to
whichever server owns a given name.

Generalizes mcp_server/src/infra/extensions.py's ExtensionRegistry: that
module treats "this server's own FastMCP tools" and "proxied tools" as
two different things, because it is itself an MCP server with tools of
its own. This registry has no tools of its own - every configured
server, including the main mcp_server, is symmetric: connect, namespace,
merge.
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable

from mcp import types
from mcp.client.session import ClientSession

from src.catalog import catalog
from src.config import ServerConfig, load_servers_config
from src.transports import open_session

# "__" rather than "_": several servers this connects to (mcp_server's own
# tools among them) already use single underscores as ordinary word
# separators, so a single underscore here couldn't be told apart from
# part of the server id or the upstream tool's own name.
NAMESPACE_SEPARATOR = "__"

# How long connecting to one server (open transport + initialize +
# list_tools) may take before it's recorded as failed - bounded so one
# hung server can't stall connect_all() indefinitely. Also set as the
# connected ClientSession's default read_timeout_seconds, which is why
# call_tool() below must override it per-call with CALL_TIMEOUT_SECONDS
# instead of inheriting this connect-phase value.
CONNECT_TIMEOUT_SECONDS = 10.0

# How long a single tool call may run before it's treated as failed.
# Deliberately separate from CONNECT_TIMEOUT_SECONDS: a real tool call
# (e.g. a slow-backend one on the main mcp_server) routinely takes longer
# than a connect handshake should ever take, so reusing that shorter
# budget here would time out legitimate slow tools, not just hung ones.
CALL_TIMEOUT_SECONDS = 120.0


@dataclass
class ServerStatus:
    """What statuses() reports for one configured server."""

    id: str
    label: str
    description: str
    status: str  # "connected" | "error"
    error: str | None = None
    tools: list[str] = field(default_factory=list)


def _namespace(server_id: str, tools: list[types.Tool]) -> list[types.Tool]:
    """Wrap `tools` (as returned by an upstream list_tools()) under their
    namespaced name for this server."""
    return [
        types.Tool(
            name=f"{server_id}{NAMESPACE_SEPARATOR}{tool.name}",
            description=tool.description,
            inputSchema=tool.inputSchema,
            outputSchema=tool.outputSchema,
            _meta=tool.meta,
            annotations=tool.annotations,
            icons=tool.icons,
        )
        for tool in tools
    ]


@catalog
class McpClientRegistry:
    """Owns every live upstream connection for the life of the process.
    Connect once via connect_all(), then call list_tools()/call_tool()
    as needed, and aclose() on shutdown."""

    def __init__(self) -> None:
        # One AsyncExitStack per server - see ExtensionRegistry's __init__
        # in mcp_server/src/infra/extensions.py for why this can't be one
        # shared stack (no way to close a single entry from a shared LIFO
        # stack).
        self._stacks: dict[str, AsyncExitStack] = {}
        self._sessions: dict[str, ClientSession] = {}
        self._last_known_tools: dict[str, list[types.Tool]] = {}
        self._statuses: list[ServerStatus] = []
        self._configs: dict[str, ServerConfig] = {}

    @catalog
    def statuses(self) -> list[ServerStatus]:
        return list(self._statuses)

    @catalog
    async def connect_all(self, config_path: Path, url_overrides: dict[str, str] | None = None) -> list[ServerStatus]:
        """Connect to every server in `config_path`, isolated - one bad
        entry is recorded as an error status and never stops a sibling
        from connecting. `url_overrides` is forwarded to
        load_servers_config() - see its docstring."""
        self._configs = load_servers_config(config_path, url_overrides)
        for server_id, config in self._configs.items():
            await self._connect_one(server_id, config)
        return self.statuses()

    async def _reconnect(self, server_id: str) -> None:
        """Replace one dead upstream session using its startup config."""
        config = self._configs.get(server_id)
        if config is None:
            raise KeyError(f"No configuration for server {server_id!r}")

        stack = self._stacks.pop(server_id, None)
        self._sessions.pop(server_id, None)
        self._last_known_tools.pop(server_id, None)
        if stack is not None:
            await stack.aclose()
        await self._connect_one(server_id, config)

    @catalog
    async def _connect_one(self, server_id: str, config: ServerConfig) -> ServerStatus:
        local_stack = AsyncExitStack()
        try:
            session = await open_session(local_stack, config, CONNECT_TIMEOUT_SECONDS)
            listed = await session.list_tools()
        except Exception as error:  # noqa: BLE001 - one bad server must not block the others
            try:
                await local_stack.aclose()
            except Exception:  # noqa: BLE001 - a messy close must not escape a failed connect
                pass
            status = ServerStatus(
                id=server_id,
                label=config.label,
                description=config.description,
                status="error",
                error=str(error) or type(error).__name__,
            )
            self._statuses.append(status)
            return status

        opened = local_stack.pop_all()
        self._stacks[server_id] = opened
        namespaced_tools = _namespace(server_id, listed.tools)
        self._last_known_tools[server_id] = namespaced_tools
        self._sessions[server_id] = session
        status = ServerStatus(
            id=server_id,
            label=config.label,
            description=config.description,
            status="connected",
            tools=[tool.name for tool in namespaced_tools],
        )
        self._statuses.append(status)
        return status

    @catalog
    async def _live_tools_for(self, server_id: str, session: ClientSession) -> list[types.Tool]:
        try:
            listed = await session.list_tools()
        except Exception:  # noqa: BLE001 - one flaky server must not break the others
            return self._last_known_tools.get(server_id, [])
        namespaced_tools = _namespace(server_id, listed.tools)
        self._last_known_tools[server_id] = namespaced_tools
        return namespaced_tools

    @catalog
    async def list_tools(self) -> list[types.Tool]:
        """The merged catalog, fetched live from every connected server on
        each call - so a server's tools changing at runtime is reflected
        without a restart, the same reasoning as extensions.py's
        merged_list_tools()."""
        results = await asyncio.gather(
            *(self._live_tools_for(server_id, session) for server_id, session in self._sessions.items())
        )
        return [tool for tools in results for tool in tools]

    @catalog
    async def call_tool(
        self, name: str, arguments: dict[str, Any], on_progress: Callable[[str], None] | None = None
    ) -> types.CallToolResult:
        """Route `name` (as returned by list_tools(), e.g. "main__ping")
        to whichever server owns it. Raises KeyError for a name that
        isn't currently connected - callers are expected to only call
        names they just got from list_tools().

        `on_progress` receives each message the tool reports while it runs
        (an MCP progress notification with a message); it is called on this
        registry's own event-loop thread."""
        server_id, separator, upstream_name = name.partition(NAMESPACE_SEPARATOR)
        session = self._sessions.get(server_id) if separator else None
        if session is None:
            raise KeyError(f"No tool named {name!r} on any connected server")

        extra: dict[str, Any] = {}
        if on_progress is not None:

            async def progress_callback(progress: float, total: float | None, message: str | None) -> None:
                if message:
                    on_progress(message)

            extra["progress_callback"] = progress_callback

        try:
            return await session.call_tool(
                upstream_name, arguments, read_timeout_seconds=timedelta(seconds=CALL_TIMEOUT_SECONDS), **extra
            )
        except RuntimeError as error:
            if str(error) != "Session terminated":
                raise
            await self._reconnect(server_id)
            recovered_session = self._sessions.get(server_id)
            if recovered_session is None:
                raise
            return await recovered_session.call_tool(
                upstream_name, arguments, read_timeout_seconds=timedelta(seconds=CALL_TIMEOUT_SECONDS), **extra
            )

    @catalog
    async def aclose(self) -> None:
        """Close every open connection. One server failing to close
        cleanly must not stop the others."""
        for stack in self._stacks.values():
            try:
                await stack.aclose()
            except Exception:  # noqa: BLE001 - a messy shutdown must not block the rest
                pass
        self._stacks.clear()
        self._sessions.clear()
