"""MCP client wrapper - the only place this process talks to the MCP server.

Provider-agnostic on purpose: every LLM provider (openai_provider.py,
claude_provider.py, ...) reshapes this same live catalog into its own
wire format. This file only knows the generic MCP shape.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from chat_app.config import settings


async def _list_tools_async() -> list[Any]:
    async with streamablehttp_client(settings.mcp_server_url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            return result.tools


async def _call_tool_async(name: str, arguments: dict[str, Any]) -> str:
    async with streamablehttp_client(settings.mcp_server_url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments)
            parts = [getattr(block, "text", str(block)) for block in result.content]
            return "\n".join(parts) if parts else "(no output)"


def _tool_is_enabled(name: str, enabled: set[str]) -> bool:
    """Extension tools are namespaced ``{ext_id}__original_name`` (double
    underscore) by mcp_server; this server's own built-in tools
    (``request_otp_tool`` etc) have no such prefix and are never subject
    to the toggle. An extension tool is only kept when its extension id
    is in ``enabled`` - an empty set (the default) drops every extension
    tool, which is the deliberate safe default: an unconfigured/newly
    added extension must never be silently in scope."""
    ext_id, sep, _ = name.partition("__")
    if not sep:
        return True
    return ext_id in enabled


def list_tools(enabled_extensions: list[str] | None = None) -> list[Any]:
    """Live tool catalog from the MCP server - never a hardcoded list.

    ``enabled_extensions`` filters out extension-namespaced tools whose
    extension id isn't in the list - see ``_tool_is_enabled`` above.
    Omitted or empty means no extension tools are offered.
    """
    tools = asyncio.run(_list_tools_async())
    enabled = set(enabled_extensions or [])
    return [tool for tool in tools if _tool_is_enabled(tool.name, enabled)]


def call_tool(name: str, arguments: dict[str, Any]) -> str:
    return asyncio.run(_call_tool_async(name, arguments))


async def _list_resource_templates_async() -> list[Any]:
    async with streamablehttp_client(settings.mcp_server_url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_resource_templates()
            # Verified against the pinned mcp==1.28.0: the field is
            # ``resourceTemplates``, camelCase, with no snake_case alias -
            # the SDK keeps the wire name here rather than converting it.
            # The snake_case fallback stays as cheap insurance in case a
            # later version normalizes it.
            return getattr(result, "resourceTemplates", getattr(result, "resource_templates", []))


async def _read_resource_async(uri: str) -> str:
    async with streamablehttp_client(settings.mcp_server_url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.read_resource(uri)
            parts = [getattr(block, "text", str(block)) for block in result.contents]
            return "\n".join(parts) if parts else "(empty)"


def list_resource_templates() -> list[Any]:
    """Live resource-template catalog - the MCP equivalent of list_tools()
    for browsable, URI-addressed read-only data instead of actions."""
    return asyncio.run(_list_resource_templates_async())


def read_resource(uri: str) -> str:
    return asyncio.run(_read_resource_async(uri))


def _extensions_url() -> str:
    """mcp_server's ``/extensions`` endpoint is plain JSON HTTP, not part
    of the MCP protocol - a sibling of ``settings.mcp_server_url`` (the
    ``/mcp`` path) on the same origin, not a route under it. Rebuild just
    the scheme+netloc rather than reusing the ``/mcp`` path itself."""
    split = urlsplit(settings.mcp_server_url)
    return f"{split.scheme}://{split.netloc}/extensions"


def fetch_extensions() -> list[dict[str, Any]]:
    """The extension catalog from mcp_server's plain-HTTP endpoint - not
    reachable through the ClientSession helpers above, so this uses
    stdlib urllib for one GET rather than adding an HTTP client
    dependency for it (same reasoning as infra/email.py's smtplib).
    Raises on any failure (connection refused, timeout, non-2xx, bad
    JSON); the caller (the /api/extensions route) decides how to surface
    that to the browser rather than crashing the page.
    """
    with urlopen(_extensions_url(), timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def add_extension(label: str, url: str, description: str = "") -> dict[str, Any]:
    """POST a new extension to mcp_server's ``/extensions`` (see
    ``fetch_extensions`` above for why this is stdlib urllib rather than a
    real HTTP client dependency). Returns the created status dict
    (``{"id","label","description","status","error","tools"}``) on a 2xx
    response - a connect failure on mcp_server's side still comes back 201
    with ``status:"error"``, same as an unreachable extension already
    configured in config.json.

    Raises ``urllib.error.HTTPError`` (carries ``.code`` and a
    ``.read()``-able body) on a 4xx/5xx response - notably 400 for a
    missing/invalid label or url - and any other urllib/network exception
    on connection failure. Left to propagate rather than swallowed here:
    the caller (the ``/api/extensions`` POST route) needs ``.code`` to
    forward mcp_server's own status instead of collapsing everything to a
    generic error.
    """
    payload = json.dumps({"label": label, "url": url, "description": description}).encode("utf-8")
    request = Request(
        _extensions_url(),
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def remove_extension(extension_id: str) -> None:
    """DELETE one extension from mcp_server. Raises the same way as
    ``add_extension`` on failure, including a 404 ``HTTPError`` for an
    unknown id."""
    request = Request(f"{_extensions_url()}/{extension_id}", method="DELETE")
    with urlopen(request, timeout=10):
        return None
