"""ai_agent's connection to mcp_server - a thin, sync-friendly wrapper
around src/mcp_client/sync_wrapper.py's SyncMcpClient, giving the provider files
(src/llm/anthropic_provider.py, src/llm/openai_provider.py) the same
call_tool(name, args) -> str / list_tools(enabled_extensions) -> list
shape chat_app's own services/mcp_client.py gives them today.

Connected once at process startup (see server.py's main()) and reused
for every request via SyncMcpClient's own persistent background
connection - not reconnected per call, unlike chat_app's mcp_client.py.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from src.agents import agent_spec

from src.core import internal_auth, tool_filter

from src.mcp_client import tool_progress
from src.core.config_files import SERVERS_PATH
from src.mcp_client.sync_wrapper import SyncMcpClient

import asyncio

from src.private_extensions import turn as private_turn
from src.private_extensions.pool import PrivateSessionPool
from src.private_extensions.spec import InvalidSpec, PrivateSpec, describe_error

_CONFIG_PATH = SERVERS_PATH

# The single upstream server id configured in configs/config_servers.json.
# Every tool list_tools() returns is namespaced "main__<tool name>" by
# SyncMcpClient's underlying McpClientRegistry (see registry.py's
# NAMESPACE_SEPARATOR) even though there's only one upstream server today.
_SERVER_ID = "main"
_PREFIX = f"{_SERVER_ID}__"

_log = logging.getLogger(__name__)

client = SyncMcpClient()

# Sessions to the users' own MCP servers (see src/private_extensions/); they
# live on the same connection loop as `client`.
private_pool = PrivateSessionPool()

# Appended to the description of any tool whose MCP meta sets
# ai_explain_result - the tool itself stays deterministic and never calls
# an AI; this only tells the assistant that ran it what to do afterward.
_EXPLAIN_RESULT_NOTE = (
    "After this tool returns, explain the result to the user in plain language: what it "
    "means, what (if anything) they should do next, and anything that looks wrong. "
    "Do not just repeat the raw fields."
)


def tool_description(tool: Any) -> str:
    """`tool.description`, plus the explain-the-result note when the tool's
    MCP meta sets ai_explain_result."""
    description = tool.description or ""
    if (getattr(tool, "meta", None) or {}).get("ai_explain_result"):
        return "\n\n".join(part for part in (description, _EXPLAIN_RESULT_NOTE) if part)
    return description


def connect() -> None:
    # MCP_SERVER_URL (set directly, or via --mcp-url - see server.py) repoints
    # the "main" upstream server without editing config_servers.json - same
    # env var chat_app's own services/llm/settings.py reads for its direct
    # connection to mcp_server, so one variable controls both.
    override = os.getenv("MCP_SERVER_URL")
    url_overrides = {_SERVER_ID: override} if override else None
    # mcp_server requires the shared internal token on /mcp once it's configured.
    extra_headers = {internal_auth.INTERNAL_TOKEN_HEADER: internal_auth.TOKEN} if internal_auth.TOKEN else None
    client.connect_all(_CONFIG_PATH, url_overrides, extra_headers)


def _tool_is_enabled(name: str, enabled: set[str]) -> bool:
    """Mirrors chat_app's mcp_client._tool_is_enabled, applied to the
    tool's name AFTER stripping this module's own "main__" registry
    prefix - a proxied extension tool arrives as "main__{ext_id}__{tool}",
    mcp_server's own built-ins as "main__{tool}" with no further "__"."""
    ext_id, sep, _ = name.partition("__")
    if not sep:
        return True
    return ext_id in enabled


def list_tools(enabled_extensions: list[str] | None = None) -> list[Any]:
    """Live tool catalog from mcp_server, filtered the same way
    chat_app's mcp_client.list_tools() filters it today - an extension
    tool is only kept when its extension id is in enabled_extensions - and
    without the tools this turn's user switched off (see core/tool_filter.py)."""
    tools = client.list_tools()
    enabled = set(enabled_extensions or [])
    scope = agent_spec.current().tools
    result = []
    for tool in tools:
        if not tool.name.startswith(_PREFIX):
            continue
        short = unprefixed(tool.name)
        if not _tool_is_enabled(short, enabled):
            continue
        if not scope.allows(short):
            continue
        if tool_filter.is_blocked(short):
            continue
        result.append(tool)
    turn = private_turn.current()
    if turn:
        # Fetched before the provider started (prefetch_private), so this never waits on a network.
        result.extend(tool for tool in turn.tools() if scope.allows(tool.name))
    return result


def call_tool(name: str, arguments: dict[str, Any]) -> str:
    if name.startswith(private_turn.TOOL_PREFIX):
        return _call_private(name, arguments)
    if name.startswith(_PREFIX) and not agent_spec.current().tools.allows(unprefixed(name)):
        # The model only sees in-scope tools, but may still name another one.
        raise PermissionError(f"tool {name!r} is not available to this agent")
    if name.startswith(_PREFIX) and tool_filter.is_blocked(unprefixed(name)):
        # Switched off by the user for their own chats; the model may still name it.
        raise PermissionError(f"tool {name!r} is switched off for this user")
    on_progress = tool_progress.current()
    # The asking user rides in the call's _meta: the session is shared by
    # every user, so it can't go in a header (see internal_auth.py).
    meta = internal_auth.requester_meta()
    # Each only passed when set, so the plain call keeps its original shape.
    extra: dict[str, Any] = {}
    if on_progress:
        extra["on_progress"] = on_progress
    if meta:
        extra["meta"] = meta
    result = client.call_tool(name, arguments, **extra)
    parts = [getattr(block, "text", str(block)) for block in result.content]
    return "\n".join(parts) if parts else "(no output)"


def _call_private(name: str, arguments: dict[str, Any]) -> str:
    turn = private_turn.current()
    route = turn.route(name) if turn else None
    if turn is None or route is None or not agent_spec.current().tools.allows(name):
        # The model only sees this turn's tools, but may still name another.
        raise PermissionError(f"tool {name!r} is not available to this agent")
    spec, upstream = route
    try:
        # No identity is sent: the user's own server is not mcp_server.
        result = client.run_coroutine(private_pool.call(turn.account, spec, upstream, arguments))
    except Exception as error:  # noqa: BLE001 - say what happened without a header value or a traceback
        raise RuntimeError(describe_error(error, spec.secrets)) from None
    parts = [getattr(block, "text", str(block)) for block in result.content]
    return "\n".join(parts) if parts else "(no output)"


async def prefetch_private(turn: "private_turn.PrivateTurn") -> None:
    """Connect to the turn's private extensions and list their tools, without
    blocking the caller's event loop."""
    await turn.prefetch(private_pool, lambda coro: asyncio.wrap_future(client.submit(coro)))


async def probe_private(url: str, headers: dict[str, str] | None) -> dict[str, Any]:
    """Connect once to `url` and report what it offers. Never raises."""
    try:
        spec = PrivateSpec.from_probe(url, headers)
    except InvalidSpec as error:
        return {"status": "error", "error": str(error), "tools": []}
    try:
        tools = await asyncio.wrap_future(client.submit(private_pool.probe(spec)))
    except Exception as error:  # noqa: BLE001 - any failure is one "error" outcome
        return {"status": "error", "error": describe_error(error, spec.secrets), "tools": []}
    return {"status": "connected", "error": None, "tools": sorted(tool.name for tool in tools)[: private_turn.MAX_TOOLS]}


def close() -> None:
    client.run_coroutine(private_pool.aclose())
    client.close()


def unprefixed(name: str) -> str:
    """A tool name without this module's "main__" registry prefix - the
    form agents/<id>.json "tools" globs are written against."""
    return name[len(_PREFIX):] if name.startswith(_PREFIX) else name


def warn_unmatched_tool_globs() -> None:
    """One warning per tools.allow/deny glob that matches no mcp_server
    tool - almost always a typo. Called once at startup, after connect()."""
    names = [unprefixed(t.name) for t in client.list_tools() if t.name.startswith(_PREFIX)]
    for glob in agent_spec.current().tools.unmatched(names):
        _log.warning("agent %s: tools glob %r matches no mcp_server tool", agent_spec.current().id, glob)
