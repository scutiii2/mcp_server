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

from src.services.mcp_session import identity_headers, mcp_session, root_cause

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
        enabled_extensions: list[str],
        on_event: EventHandler,
    ) -> dict[str, Any]: ...

    async def interpret(self, url: str, caller: Caller, text: str) -> dict[str, Any]: ...

    async def cancel(self, url: str, caller: Caller, request_id: str) -> bool: ...


class McpAgentGateway:
    def __init__(self, internal_token: str | None) -> None:
        self._internal_token = internal_token

    def _headers(self, caller: Caller) -> dict[str, str]:
        return identity_headers(caller.username, caller.email, self._internal_token)

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
            async with mcp_session(url, self._headers(caller), _TIMEOUT) as session:
                result = await session.call_tool(tool, arguments, progress_callback=on_progress if on_event else None)
        except Exception as error:  # noqa: BLE001 - any transport failure is one "unreachable" outcome
            logger.warning("ai_agent %s %s failed: %s", url, tool, error)
            raise AgentCallError(f"Could not reach the agent: {root_cause(error)}") from error

        if result.isError:
            parts = [getattr(block, "text", str(block)) for block in result.content]
            raise AgentCallError("\n".join(parts) if parts else f"{tool} failed")
        return result.structuredContent or {}

    async def ask(self, url, caller, *, question, history, request_id, caveman, enabled_extensions, on_event):
        arguments = {
            "question": question,
            "history": history,
            "request_id": request_id,
            "caveman": caveman,
            # Which extensions' tools the agent may use; none by default.
            "enabled_extensions": enabled_extensions,
        }
        return await self._call(url, caller, "ask", arguments, on_event)

    async def interpret(self, url, caller, text):
        return await self._call(url, caller, "interpret", {"text": text})

    async def cancel(self, url, caller, request_id):
        result = await self._call(url, caller, "cancel", {"request_id": request_id})
        return bool(result.get("cancelled"))

