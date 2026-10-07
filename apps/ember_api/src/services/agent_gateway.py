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
from src.services.traffic import TrafficRecorder

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
        approval_mode: str = "off",
        allowed_tools: list[str] | None = None,
        disabled_tools: list[str] | None = None,
    ) -> dict[str, Any]: ...

    async def interpret(self, url: str, caller: Caller, text: str) -> dict[str, Any]: ...

    async def cancel(self, url: str, caller: Caller, request_id: str) -> bool: ...

    async def decide(self, url: str, caller: Caller, request_id: str, step_id: str, decision: str) -> bool: ...


class McpAgentGateway:
    def __init__(self, internal_token: str | None, traffic: TrafficRecorder | None = None) -> None:
        self._internal_token = internal_token
        self._traffic = traffic or TrafficRecorder()

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
        with self._traffic.timed("ai_agent", tool):
            try:
                async with mcp_session(url, self._headers(caller), _TIMEOUT) as session:
                    result = await session.call_tool(
                        tool, arguments, progress_callback=on_progress if on_event else None
                    )
            except Exception as error:  # noqa: BLE001 - any transport failure is one "unreachable" outcome
                logger.warning("ai_agent %s %s failed: %s", url, tool, error)
                raise AgentCallError(f"Could not reach the agent: {root_cause(error)}") from error

            if result.isError:
                parts = [getattr(block, "text", str(block)) for block in result.content]
                raise AgentCallError("\n".join(parts) if parts else f"{tool} failed")
            return result.structuredContent or {}

    async def ask(
        self,
        url,
        caller,
        *,
        question,
        history,
        request_id,
        caveman,
        enabled_extensions,
        on_event,
        approval_mode="off",
        allowed_tools=None,
        disabled_tools=None,
    ):
        arguments = {
            "question": question,
            "history": history,
            "request_id": request_id,
            "caveman": caveman,
            # Which extensions' tools the agent may use; none by default.
            "enabled_extensions": enabled_extensions,
        }
        if approval_mode != "off":
            # Fail closed: an ai_agent that predates this option would ignore
            # it and run every tool unasked, so it is checked before the turn
            # starts, not discovered after tools have run.
            status = await self._call(url, caller, "status", {})
            if not status.get("tool_approval"):
                raise AgentCallError(
                    "This agent cannot ask before running tools (it needs updating and restarting). "
                    "Turn off \"Ask before running tools\" or restart the agent."
                )
            arguments["approval_mode"] = approval_mode
            arguments["allowed_tools"] = allowed_tools or []
        if disabled_tools:
            # Fail closed, like approvals: an ai_agent that predates this option
            # would offer every tool, including the ones the user switched off.
            status = await self._call(url, caller, "status", {})
            if not status.get("tool_filter"):
                raise AgentCallError(
                    "This agent cannot leave out the tools you switched off (it needs updating and restarting). "
                    "Switch those capabilities back on or restart the agent."
                )
            arguments["disabled_tools"] = disabled_tools
        return await self._call(url, caller, "ask", arguments, on_event)

    async def interpret(self, url, caller, text):
        return await self._call(url, caller, "interpret", {"text": text})

    async def cancel(self, url, caller, request_id):
        result = await self._call(url, caller, "cancel", {"request_id": request_id})
        return bool(result.get("cancelled"))

    async def decide(self, url, caller, request_id, step_id, decision):
        """Answers a tool-approval request the agent raised for this turn.
        False when nothing was waiting (already answered, or the turn ended)."""
        result = await self._call(url, caller, "decide", {"request_id": request_id, "step_id": step_id, "decision": decision})
        return bool(result.get("decided"))

