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

CALLER = Caller(username="alice", email="alice@example.com", uid="uid-alice")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _build_agent(approvals: bool = True, private: bool | None = None) -> FastMCP:
    """`approvals` False: an agent from before tool approval existed - its
    status says nothing about it and its ask() has no such options."""
    private = approvals if private is None else private
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
        disabled_tools: list[str] | None = None,
        ask_user: bool = False,
        private_extensions: list[dict] | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        headers = ctx.request_context.request.headers
        seen["username"] = headers.get("x-requester-username")
        seen["uid"] = headers.get("x-requester-uid")
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
            "disabled": disabled_tools,
            "ask_user": ask_user,
            "private": private_extensions,
        }

    @mcp.tool()
    def status() -> dict[str, Any]:
        flags = {"tool_approval": True, "tool_filter": True, "user_questions": True} if approvals else {}
        return {"available": True, **flags, **({"private_extensions": True} if private else {})}

    @mcp.tool()
    def probe_extension(url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
        if url.endswith("/down"):
            return {"status": "error", "error": "Timed out", "tools": []}
        return {"status": "connected", "error": None, "tools": ["add", "search"], "seen": [url, headers]}

    @mcp.tool()
    def decide(request_id: str, step_id: str, decision: str) -> dict[str, Any]:
        return {"decided": (request_id, step_id) == ("r1", "s1") and decision in ("allow", "always", "deny")}

    @mcp.tool()
    def answer_question(
        request_id: str, step_id: str, answers: list[dict] | None = None, skipped: bool = False
    ) -> dict[str, Any]:
        return {"answered": (request_id, step_id) == ("r1", "s1"), "echo": {"answers": answers, "skipped": skipped}}

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
    assert result["seen"] == {"username": "alice", "uid": "uid-alice", "token": "s3cret"}
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


def test_ask_sends_the_switched_off_tools(agent_url: str) -> None:
    result = _ask(McpAgentGateway(None), agent_url, disabled_tools=["tool_pdf_merge", "tool_pdf_split"])

    assert result["disabled"] == ["tool_pdf_merge", "tool_pdf_split"]


def test_ask_leaves_the_option_out_when_nothing_is_switched_off(agent_url: str) -> None:
    assert _ask(McpAgentGateway(None), agent_url)["disabled"] is None
    assert _ask(McpAgentGateway(None), agent_url, disabled_tools=[])["disabled"] is None


def test_switched_off_tools_refuse_an_agent_that_would_offer_them_anyway(old_agent_url: str) -> None:
    gateway = McpAgentGateway(None)
    before = _asks_made(gateway, old_agent_url)

    with pytest.raises(AgentCallError, match="cannot leave out the tools"):
        _ask(gateway, old_agent_url, disabled_tools=["tool_pdf_merge"])

    assert _asks_made(gateway, old_agent_url) == before  # ask() never ran


# --- clickable questions -----------------------------------------------------------------


def test_ask_sends_ask_user_when_the_agent_understands_it(agent_url: str) -> None:
    result = _ask(McpAgentGateway(None), agent_url, ask_user=True)

    assert result["ask_user"] is True


def test_ask_leaves_ask_user_out_by_default(agent_url: str) -> None:
    assert _ask(McpAgentGateway(None), agent_url)["ask_user"] is False


def test_an_agent_that_does_not_know_ask_user_just_does_not_get_it(old_agent_url: str) -> None:
    result = _ask(McpAgentGateway(None), old_agent_url, ask_user=True)

    assert result["ask_user"] is False  # the question tool is simply not offered; the turn still runs


def test_answer_reports_whether_the_question_was_waiting(agent_url: str) -> None:
    gateway = McpAgentGateway(None)
    answers = [{"selected": ["CSV"], "other": None}]

    assert asyncio.run(gateway.answer_question(agent_url, CALLER, "r1", "s1", answers, False)) is True
    assert asyncio.run(gateway.answer_question(agent_url, CALLER, "r1", "nope", [], True)) is False


# --- private extensions ---------------------------------------------------------------------


RAW_PRIVATE = [{"id": "notes", "label": "Notes", "url": "https://notes.example.com/mcp", "headers": {"X-Key": "s3cret"}}]


def test_ask_sends_private_extensions(agent_url: str) -> None:
    result = _ask(McpAgentGateway(None), agent_url, private_extensions=RAW_PRIVATE)

    assert result["private"] == RAW_PRIVATE


def test_ask_leaves_the_argument_out_when_there_are_none(agent_url: str) -> None:
    assert _ask(McpAgentGateway(None), agent_url)["private"] is None
    assert _ask(McpAgentGateway(None), agent_url, private_extensions=[])["private"] is None


def test_private_extensions_refuse_an_agent_that_would_ignore_them(old_agent_url: str) -> None:
    gateway = McpAgentGateway(None)
    before = _asks_made(gateway, old_agent_url)

    with pytest.raises(AgentCallError, match="cannot use your private extensions"):
        _ask(gateway, old_agent_url, private_extensions=RAW_PRIVATE)

    assert _asks_made(gateway, old_agent_url) == before  # ask() never ran


def test_probe_extension_returns_status_error_and_tools(agent_url: str) -> None:
    gateway = McpAgentGateway(None)

    ok = asyncio.run(gateway.probe_extension(agent_url, CALLER, extension_url="https://x.example.com/mcp", headers={"A": "b"}))
    down = asyncio.run(gateway.probe_extension(agent_url, CALLER, extension_url="https://x.example.com/down", headers=None))

    assert ok == {"status": "connected", "error": None, "tools": ["add", "search"]}
    assert down == {"status": "error", "error": "Timed out", "tools": []}


def test_probe_extension_of_an_unreachable_agent_raises_agent_call_error() -> None:
    gateway = McpAgentGateway(None)

    with pytest.raises(AgentCallError, match="Could not reach the agent"):
        asyncio.run(
            gateway.probe_extension(
                f"http://127.0.0.1:{_free_port()}/mcp", CALLER, extension_url="https://x.example.com/mcp", headers=None
            )
        )
