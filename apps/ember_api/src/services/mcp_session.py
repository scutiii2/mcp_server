"""One MCP client session over Streamable HTTP, with ember_api's headers.

Shared by the agent gateway (ai_agent) and the server tools (mcp_server):
both open a session per unit of work, like chat_app, carrying the
requesting account's identity and the internal token if configured.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client


def identity_headers(username: str, email: str, internal_token: str | None) -> dict[str, str]:
    headers = {"X-Requester-Username": username, "X-Requester-Email": email}
    if internal_token:
        headers["X-Internal-Token"] = internal_token
    return headers


@asynccontextmanager
async def mcp_session(url: str, headers: dict[str, str], timeout: httpx.Timeout) -> AsyncIterator[ClientSession]:
    """An initialized session. Raise nothing inside the block that should
    reach the caller as itself: the SDK's task groups wrap it in an
    ExceptionGroup - collect results inside, decide outside."""
    async with (
        create_mcp_http_client(headers=headers, timeout=timeout) as http_client,
        streamable_http_client(url, http_client=http_client) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        yield session


def root_cause(error: BaseException) -> str:
    """The first real error inside anyio's ExceptionGroup wrappers."""
    while isinstance(error, BaseExceptionGroup) and error.exceptions:
        error = error.exceptions[0]
    return str(error) or type(error).__name__
