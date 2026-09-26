"""ember_api's own MCP client for ai_agent: the chat turns it runs itself
(ask, interpret, cancel), port of chat_app/src/services/ai_agent_client.py.

One MCP connection per call, like chat_app. Every call carries the
requesting account's identity (and the internal token, if configured), the
same headers the browser proxy adds.

The Protocol is what the rest of ember_api depends on, so tests swap in a
fake agent without a network.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

logger = logging.getLogger(__name__)

# A turn with many tool rounds can stream for a long time; connecting and
# sending must still fail fast.
_TIMEOUT = httpx.Timeout(30.0, read=3600.0)

EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class AgentCallError(Exception):
    """The agent couldn't be reached, or reported the call as failed."""


@dataclass(frozen=True)
class Caller:
    """Who a call is made for; sent as the proxy's identity headers."""

    username: str
    email: str


class AgentGateway(Protocol):
    async def ask(
        self,
        url: str,
        caller: Caller,
        *,
        question: str,
        history: list[dict[str, str]],
        request_id: str,
        caveman: bool,
        on_event: EventHandler,
    ) -> dict[str, Any]: ...

    async def interpret(self, url: str, caller: Caller, text: str) -> dict[str, Any]: ...

    async def cancel(self, url: str, caller: Caller, request_id: str) -> bool: ...


class McpAgentGateway:
    def __init__(self, internal_token: str | None) -> None:
        self._internal_token = internal_token

    def _headers(self, caller: Caller) -> dict[str, str]:
        headers = {"X-Requester-Username": caller.username, "X-Requester-Email": caller.email}
        if self._internal_token:
            headers["X-Internal-Token"] = self._internal_token
        return headers

    async def _call(
        self,
        url: str,
        caller: Caller,
        tool: str,
        arguments: dict[str, Any],
        on_event: EventHandler | None = None,
    ) -> dict[str, Any]:
        async def on_progress(_progress: float, _total: float | None, message: str | None) -> None:
            if on_event is None or not message:
                return
            try:
                event = json.loads(message)
            except ValueError:
                return
            if isinstance(event, dict):
                await on_event(event)

        # isError is checked only after both context managers have exited:
        # raising inside them would surface as an ExceptionGroup from their
        # task groups (the same trap chat_app's client documents).
        try:
            async with (
                create_mcp_http_client(headers=self._headers(caller), timeout=_TIMEOUT) as http_client,
                streamable_http_client(url, http_client=http_client) as (read, write, _),
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        tool, arguments, progress_callback=on_progress if on_event else None
                    )
        except Exception as error:  # noqa: BLE001 - any transport failure is one "unreachable" outcome
            logger.warning("ai_agent %s %s failed: %s", url, tool, error)
            raise AgentCallError(f"Could not reach the agent: {_root_cause(error)}") from error

        if result.isError:
            parts = [getattr(block, "text", str(block)) for block in result.content]
            raise AgentCallError("\n".join(parts) if parts else f"{tool} failed")
        return result.structuredContent or {}

    async def ask(self, url, caller, *, question, history, request_id, caveman, on_event):
        return await self._call(
            url,
            caller,
            "ask",
            {"question": question, "history": history, "request_id": request_id, "caveman": caveman},
            on_event,
        )

    async def interpret(self, url, caller, text):
        return await self._call(url, caller, "interpret", {"text": text})

    async def cancel(self, url, caller, request_id):
        result = await self._call(url, caller, "cancel", {"request_id": request_id})
        return bool(result.get("cancelled"))


def _root_cause(error: BaseException) -> str:
    """The first real error inside anyio's ExceptionGroup wrappers."""
    while isinstance(error, BaseExceptionGroup) and error.exceptions:
        error = error.exceptions[0]
    return str(error) or type(error).__name__
