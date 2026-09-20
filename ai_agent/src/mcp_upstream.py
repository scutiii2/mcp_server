"""ai_agent's connection to mcp_server - a thin, sync-friendly wrapper
around src/sync_wrapper.py's SyncMcpClient, giving the provider files
(src/llm/anthropic_provider.py, src/llm/openai_provider.py) the same
call_tool(name, args) -> str / list_tools(enabled_extensions) -> list
shape chat_app's own services/mcp_client.py gives them today.

Connected once at process startup (see server.py's main()) and reused
for every request via SyncMcpClient's own persistent background
connection - not reconnected per call, unlike chat_app's mcp_client.py.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from src import tool_progress
from src.sync_wrapper import SyncMcpClient

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "configs" / "config_servers.json"

# The single upstream server id configured in configs/config_servers.json.
# Every tool list_tools() returns is namespaced "main__<tool name>" by
# SyncMcpClient's underlying McpClientRegistry (see registry.py's
# NAMESPACE_SEPARATOR) even though there's only one upstream server today.
_SERVER_ID = "main"
_PREFIX = f"{_SERVER_ID}__"

client = SyncMcpClient()

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
    client.connect_all(_CONFIG_PATH, url_overrides)


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
    tool is only kept when its extension id is in enabled_extensions."""
    tools = client.list_tools()
    enabled = set(enabled_extensions or [])
    result = []
    for tool in tools:
        if not tool.name.startswith(_PREFIX):
            continue
        unprefixed = tool.name[len(_PREFIX):]
        if not _tool_is_enabled(unprefixed, enabled):
            continue
        result.append(tool)
    return result


def call_tool(name: str, arguments: dict[str, Any]) -> str:
    on_progress = tool_progress.current()
    # Only passed when a provider is streaming, so the no-progress call
    # keeps its original shape.
    result = client.call_tool(name, arguments, **({"on_progress": on_progress} if on_progress else {}))
    parts = [getattr(block, "text", str(block)) for block in result.content]
    return "\n".join(parts) if parts else "(no output)"


def close() -> None:
    client.close()
