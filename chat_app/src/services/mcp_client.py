"""MCP client wrapper - this process's connection to mcp_server for
everything except the LLM Q&A path: slash commands (services/commands.py)
and admin/extension/capability management. The Chat page's "ask the
model" path no longer goes through here - it calls the configured
ai_agent instead (see services/ai_agent_client.py), which holds its own
persistent connection to mcp_server.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

import httpx
from flask import current_app
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from src.services.llm.settings import settings


async def _list_tools_async() -> list[Any]:
    async with streamablehttp_client(settings.mcp_server_url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            return result.tools


async def _call_tool_async(
    name: str,
    arguments: dict[str, Any],
    headers: dict[str, str] | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> str:
    async def progress_callback(progress: float, total: float | None, message: str | None) -> None:
        if message:
            on_progress(message)

    async with streamablehttp_client(settings.mcp_server_url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                name, arguments, progress_callback=progress_callback if on_progress else None
            )
            parts = [getattr(block, "text", str(block)) for block in result.content]
            return "\n".join(parts) if parts else "(no output)"


def _tool_is_enabled(name: str, enabled: set[str]) -> bool:
    """Extension tools are namespaced ``{ext_id}__original_name`` (double
    underscore) by mcp_server; this server's own built-in tools
    (``tool_server_list`` etc) have no such prefix and are never subject
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


def call_tool(
    name: str,
    arguments: dict[str, Any],
    headers: dict[str, str] | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> str:
    """``headers`` carries caller-identity out-of-band for the small set of
    tools that need it for an audit trail - see
    services/commands.py's _IDENTITY_INJECTED_TOOLS and mcp_server's
    services/identity_context.py. Never used for the normal tool-call
    path, which passes everything through ``arguments`` instead.

    ``on_progress`` receives each progress message a long-running tool
    reports (see mcp_server's services/progress.py) while the call is still
    in flight; it runs on this call's own event-loop thread."""
    return asyncio.run(_call_tool_async(name, arguments, headers, on_progress))


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


def _commands_url() -> str:
    """mcp_server's /commands endpoint - a sibling of /extensions on the
    same origin, built the same way (see _extensions_url() above)."""
    split = urlsplit(settings.mcp_server_url)
    return f"{split.scheme}://{split.netloc}/commands"


def fetch_commands() -> list[dict[str, Any]]:
    """The built-in chat-command registry from mcp_server's plain-HTTP
    /commands endpoint - see mcp_server/command_routes.py. Same failure
    behavior as fetch_extensions() above: raises on any failure, caller
    decides how to surface it."""
    with urlopen(_commands_url(), timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_options(path: str) -> list[dict[str, str]]:
    """Options for a select param, from a path on mcp_server (a tool's
    ``options_url``): a JSON list of strings, a list of
    ``{"value", "label"}`` objects, or a ``{value: label}`` object -
    always returned as ``[{"value", "label"}, ...]``. Only a plain
    same-origin path is accepted, since the schema (an extension's too)
    is not trusted to name a host."""
    if not path.startswith("/") or path.startswith("//") or "://" in path:
        raise ValueError(f"options_url must be a path on mcp_server, got {path!r}")
    split = urlsplit(settings.mcp_server_url)
    with urlopen(f"{split.scheme}://{split.netloc}{path}", timeout=10) as response:
        data = json.loads(response.read().decode("utf-8"))
    if isinstance(data, dict):
        return [{"value": str(k), "label": str(v)} for k, v in data.items()]
    # A {value, label, ...} object may carry extra fields; the form reads them
    # through a param's `sets`/`shows`.
    return [
        {**{k: str(v) for k, v in o.items()}, "value": str(o["value"]), "label": str(o.get("label", o["value"]))}
        if isinstance(o, dict) else {"value": str(o), "label": str(o)}
        for o in data
    ]


def fetch_help_index() -> dict[str, Any]:
    """The top-level `/help` index from mcp_server's plain-HTTP
    ``/commands/help`` endpoint (no capability path segment) - see
    mcp_server/help_routes.py::get_help_index. One row per enabled
    built-in capability (id, label, summary, its full command list),
    shaped the same way fetch_help() below is so services/commands.py
    runs it through the same format_command_result() with no special
    rendering. Same failure behavior as fetch_help() below.
    """
    split = urlsplit(settings.mcp_server_url)
    url = f"{split.scheme}://{split.netloc}/commands/help"
    with urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_help(capability: str, target: str = "all", command: str | None = None) -> dict[str, Any]:
    """`/<capability> help` data from mcp_server's plain-HTTP
    ``/commands/help/{capability}`` endpoint - see
    mcp_server/help_routes.py. Shaped like a normal tool result
    (``message`` plus ``tools``/``commands``/``workflow`` list[dict]
    fields), so services/commands.py runs it through the same
    ``format_command_result()`` every other command result gets, with no
    special-cased rendering.

    Raises ``urllib.error.HTTPError`` for an unknown capability (404) or
    an unknown target/command name (400) - same as fetch_commands()
    above, left to propagate so the caller can turn its body's
    ``{"error": "..."}`` into a user-facing CommandError message.
    """
    split = urlsplit(settings.mcp_server_url)
    params = {"target": target}
    if command:
        params["command"] = command
    url = f"{split.scheme}://{split.netloc}/commands/help/{capability}?{urlencode(params)}"
    with urlopen(url, timeout=10) as response:
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


def _capabilities_url() -> str:
    """mcp_server's /capabilities endpoint - a sibling of /extensions on
    the same origin, built the same way (see _extensions_url() above)."""
    split = urlsplit(settings.mcp_server_url)
    return f"{split.scheme}://{split.netloc}/capabilities"


def fetch_capabilities() -> list[dict[str, Any]]:
    """Which built-in capabilities mcp_server currently has enabled -
    ``[{"name": "host_health", "enabled": true}, ...]``. Live state, not
    the config file: reflects any PATCH already applied, including one
    from another browser tab or another user. Same failure behavior as
    fetch_extensions()/fetch_commands() - raises on any failure, caller
    decides how to surface it."""
    with urlopen(_capabilities_url(), timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _upload_url() -> str:
    """mcp_server's /upload endpoint - a sibling of /extensions on the same
    origin, built the same way (see _extensions_url() above)."""
    split = urlsplit(settings.mcp_server_url)
    return f"{split.scheme}://{split.netloc}/upload"


def upload_file(filename: str, content: bytes, content_type: str | None) -> dict[str, Any]:
    """POST a file to mcp_server's ``POST /upload`` (see mcp_server's
    upload_routes.py) so a command-form modal's file-format param can be
    filled with a real server-side path. Unlike every other function in
    this module, this one needs a real multipart body - not worth
    hand-building with stdlib urllib, so this is the one call in this
    module that uses ``httpx`` (already an installed dependency of the
    ``mcp``/``anthropic``/``openai`` SDKs this app already depends on)
    instead.

    Authenticated the same way mcp_server authenticates the one call it
    makes back into this app (chat_app's own internal_routes.py) - the
    shared ``INTERNAL_API_TOKEN`` secret, read from Flask's app config
    since this is the first function here that needs a request context to
    run in (it's only ever called from the ``/api/upload`` route handler).

    Raises ``httpx.HTTPStatusError``/``httpx.RequestError`` on any
    failure (mcp_server unreachable, rejected the token, rejected the file
    type) - left to propagate so the route layer decides how to surface
    it, same convention every other function in this module follows for
    ``urllib.error.HTTPError``.
    """
    token = current_app.config.get("INTERNAL_API_TOKEN", "")
    response = httpx.post(
        _upload_url(),
        files={"file": (filename, content, content_type or "application/octet-stream")},
        headers={"X-Internal-Token": token},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def set_capability_enabled(name: str, enabled: bool) -> dict[str, Any]:
    """PATCH one capability's enabled state on mcp_server - takes effect
    immediately on the live server, no restart (see
    capability_registry.py on that side). Returns the updated
    ``{"name", "enabled"}``. Raises ``urllib.error.HTTPError`` for a 404
    (unknown capability) or 400 (malformed body), same as
    add_extension/remove_extension above - left to propagate so the
    route layer can forward mcp_server's own status.
    """
    payload = json.dumps({"enabled": enabled}).encode("utf-8")
    request = Request(
        f"{_capabilities_url()}/{name}",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="PATCH",
    )
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))
