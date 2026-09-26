"""McpAgentGateway against a real MCP server (FastMCP over streamable HTTP,
like ai_agent), so the SDK wiring - headers, progress events, results,
errors - is checked end to end, not only through the fake agent."""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
import uvicorn
from mcp.server.fastmcp import Context, FastMCP

from src.services.agent_gateway import AgentCallError, Caller, McpAgentGateway

CALLER = Caller(username="alice", email="alice@example.com")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _build_agent() -> FastMCP:
    mcp = FastMCP("fake-ai-agent")
    seen: dict = {}

    @mcp.tool()
    async def ask(
        question: str,
        history: list[dict] | None = None,
        request_id: str | None = None,
        caveman: bool = False,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        headers = ctx.request_context.request.headers
        seen["username"] = headers.get("x-requester-username")
        seen["token"] = headers.get("x-internal-token")
        for text in ("Hel", "lo"):
            await ctx.report_progress(0, None, json.dumps({"type": "token", "text": text}))
        return {
            "response": f"echo: {question} ({len(history or [])} earlier, caveman={caveman})",
            "cancelled": False,
            "total_tokens": 42,
            "seen": dict(seen),
        }

    @mcp.tool()
    def interpret(text: str) -> dict[str, Any]:
        return {"response": text.upper(), "total_tokens": 3}

    @mcp.tool()
    def cancel(request_id: str) -> dict[str, Any]:
        return {"cancelled": request_id == "known"}

    @mcp.tool()
    def broken() -> dict[str, Any]:
        raise ValueError("provider rate limited")

    return mcp


@pytest.fixture(scope="module")
def agent_url() -> Iterator[str]:
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(_build_agent().streamable_http_app(), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "fake agent didn't start"
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    thread.join(timeout=5)


def test_ask_streams_events_and_sends_identity(agent_url: str) -> None:
    gateway = McpAgentGateway(internal_token="s3cret")
    events: list[dict] = []

    async def on_event(event: dict) -> None:
        events.append(event)

    result = asyncio.run(
        gateway.ask(
            agent_url,
            CALLER,
            question="hi",
            history=[{"role": "user", "content": "earlier"}],
            request_id="r1",
            caveman=True,
            on_event=on_event,
        )
    )

    assert result["response"] == "echo: hi (1 earlier, caveman=True)"
    assert result["seen"] == {"username": "alice", "token": "s3cret"}
    assert [e["text"] for e in events] == ["Hel", "lo"]


def test_interpret_and_cancel(agent_url: str) -> None:
    gateway = McpAgentGateway(internal_token=None)

    assert asyncio.run(gateway.interpret(agent_url, CALLER, "sum"))["response"] == "SUM"
    assert asyncio.run(gateway.cancel(agent_url, CALLER, "known")) is True
    assert asyncio.run(gateway.cancel(agent_url, CALLER, "other")) is False


def test_tool_error_and_unreachable_agent_raise_agent_call_error(agent_url: str) -> None:
    gateway = McpAgentGateway(internal_token=None)

    with pytest.raises(AgentCallError, match="provider rate limited"):
        asyncio.run(gateway._call(agent_url, CALLER, "broken", {}))
    with pytest.raises(AgentCallError, match="Could not reach the agent"):
        asyncio.run(gateway.interpret(f"http://127.0.0.1:{_free_port()}/mcp", CALLER, "x"))
