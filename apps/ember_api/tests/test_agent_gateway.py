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


def _build_agent(approvals: bool = True) -> FastMCP:
    """`approvals` False: an agent from before tool approval existed - its
    status says nothing about it and its ask() has no such options."""
    mcp = FastMCP("fake-ai-agent")
    seen: dict = {}
    calls = {"asks": 0}

    @mcp.tool()
    async def ask(
        question: str,
        history: list[dict] | None = None,
        request_id: str | None = None,
        caveman: bool = False,
        enabled_extensions: list[str] | None = None,
        approval_mode: str = "off",
        allowed_tools: list[str] | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        headers = ctx.request_context.request.headers
        seen["username"] = headers.get("x-requester-username")
        seen["token"] = headers.get("x-internal-token")
        calls["asks"] += 1
        for text in ("Hel", "lo"):
            await ctx.report_progress(0, None, json.dumps({"type": "token", "text": text}))
        return {
            "response": f"echo: {question} ({len(history or [])} earlier, caveman={caveman}, ext={enabled_extensions})",
            "cancelled": False,
            "total_tokens": 42,
            "seen": dict(seen),
            "approval": {"mode": approval_mode, "allowed": allowed_tools},
        }

    @mcp.tool()
    def status() -> dict[str, Any]:
        return {"available": True, **({"tool_approval": True} if approvals else {})}

    @mcp.tool()
    def decide(request_id: str, step_id: str, decision: str) -> dict[str, Any]:
        return {"decided": (request_id, step_id) == ("r1", "s1") and decision in ("allow", "always", "deny")}

    @mcp.tool()
    def ask_count() -> dict[str, Any]:
        return {"asks": calls["asks"]}

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


def _serve(app) -> Iterator[str]:
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "fake agent didn't start"
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="module")
def agent_url() -> Iterator[str]:
    yield from _serve(_build_agent().streamable_http_app())


@pytest.fixture(scope="module")
def old_agent_url() -> Iterator[str]:
    yield from _serve(_build_agent(approvals=False).streamable_http_app())


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
            enabled_extensions=["notes"],
            on_event=on_event,
        )
    )

    assert result["response"] == "echo: hi (1 earlier, caveman=True, ext=['notes'])"
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


# --- asking before tools run --------------------------------------------------------------


def _ask(gateway: McpAgentGateway, url: str, **extra: Any) -> dict[str, Any]:
    async def on_event(_event: dict) -> None:
        return None

    return asyncio.run(
        gateway.ask(
            url,
            CALLER,
            question="hi",
            history=[],
            request_id="r1",
            caveman=False,
            enabled_extensions=[],
            on_event=on_event,
            **extra,
        )
    )


def _asks_made(gateway: McpAgentGateway, url: str) -> int:
    return int(asyncio.run(gateway._call(url, CALLER, "ask_count", {}))["asks"])


def test_ask_sends_the_approval_options_when_asking_is_on(agent_url: str) -> None:
    result = _ask(McpAgentGateway(None), agent_url, approval_mode="ask", allowed_tools=["tool_a", "tool_b"])

    assert result["approval"] == {"mode": "ask", "allowed": ["tool_a", "tool_b"]}


def test_ask_leaves_the_options_out_when_asking_is_off(agent_url: str) -> None:
    result = _ask(McpAgentGateway(None), agent_url)

    assert result["approval"] == {"mode": "off", "allowed": None}


def test_asking_before_tools_refuses_an_agent_that_would_ignore_it(old_agent_url: str) -> None:
    gateway = McpAgentGateway(None)
    before = _asks_made(gateway, old_agent_url)

    with pytest.raises(AgentCallError, match="cannot ask before running tools"):
        _ask(gateway, old_agent_url, approval_mode="ask", allowed_tools=[])

    assert _asks_made(gateway, old_agent_url) == before  # ask() never ran, so no tool could


def test_an_old_agent_still_answers_when_asking_is_off(old_agent_url: str) -> None:
    result = _ask(McpAgentGateway(None), old_agent_url)

    assert result["response"].startswith("echo: hi")


def test_decide_reports_whether_anything_was_waiting(agent_url: str) -> None:
    gateway = McpAgentGateway(None)

    assert asyncio.run(gateway.decide(agent_url, CALLER, "r1", "s1", "allow")) is True
    assert asyncio.run(gateway.decide(agent_url, CALLER, "r1", "s2", "allow")) is False
    assert asyncio.run(gateway.decide(agent_url, CALLER, "other", "s1", "deny")) is False
