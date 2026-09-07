"""MCP client for chat_app's configured ai_agent(s) - the LLM Q&A path
only. Slash commands and admin/extension/capability management still go
through services/mcp_client.py directly to mcp_server, unchanged; this
module is used only by chat_api()'s non-command branch, cancel_chat_api(),
and providers_api()'s live status poll.

One connection per call, like services/mcp_client.py today - not a
persistent connection, matching this project's per-request Flask model.
"""

from __future__ import annotations

import asyncio
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


class AgentToolError(Exception):
    """Raised when the agent itself reports a tool-call error (isError on
    the MCP result) - e.g. its pinned provider is rate-limited. Distinct
    from a bare connection/transport failure, which propagates as
    whatever exception the mcp SDK itself raises."""


async def _call_tool(url: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    # Deliberately does NOT raise AgentToolError from inside either async
    # with block below - streamablehttp_client/ClientSession both run an
    # anyio task group internally, and an exception raised while one is
    # still open gets wrapped in a BaseExceptionGroup on unwind (confirmed
    # live: chat_api()'s `except AgentToolError` never matched, because
    # what actually propagated was an ExceptionGroup wrapping it). Both
    # blocks must exit cleanly first; only then is the isError check - and
    # any raise - performed, on a already-closed connection.
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments)

    if result.isError:
        parts = [getattr(block, "text", str(block)) for block in result.content]
        raise AgentToolError("\n".join(parts) if parts else f"{name} failed")
    return result.structuredContent or {}


def ask(
    url: str,
    question: str,
    history: list[dict[str, Any]],
    enabled_extensions: list[str],
    request_id: str | None = None,
) -> dict[str, Any]:
    return asyncio.run(
        _call_tool(
            url,
            "ask",
            {
                "question": question,
                "history": history,
                "enabled_extensions": enabled_extensions,
                "request_id": request_id,
            },
        )
    )


def status(url: str) -> dict[str, Any]:
    return asyncio.run(_call_tool(url, "status", {}))


def cancel(url: str, request_id: str) -> dict[str, Any]:
    return asyncio.run(_call_tool(url, "cancel", {"request_id": request_id}))
