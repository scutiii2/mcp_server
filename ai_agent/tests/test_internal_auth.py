"""internal_auth.py tests: the /mcp token check, and the asking user
travelling from ask()'s request headers to mcp_server tool calls (_meta)
and delegated peers (headers)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.testclient import TestClient

from src import server

from src.agents import delegation

from src.core import internal_auth

from src.mcp_client import mcp_upstream
from src.core.internal_auth import InternalTokenMiddleware, Requester
from src.llm.base_provider import ChatResult
from src.mcp_client.registry import McpClientRegistry


def _client(token: str) -> TestClient:
    app = Starlette()
    app.add_route("/mcp", lambda request: PlainTextResponse("mcp"), methods=["POST"])
    app.add_route("/health", lambda request: PlainTextResponse("ok"), methods=["GET"])
    app.add_middleware(InternalTokenMiddleware, token=token)
    return TestClient(app)


def test_mcp_requires_the_token_when_configured():
    client = _client("shared-secret")

    assert client.post("/mcp").status_code == 401
    assert client.post("/mcp", headers={"X-Internal-Token": "guess"}).status_code == 401
    assert client.post("/mcp", headers={"X-Internal-Token": "shared-secret"}).text == "mcp"
    assert client.get("/health").status_code == 200


def test_mcp_is_open_without_a_configured_token():
    assert _client("").post("/mcp").status_code == 200


def test_requester_meta_and_headers_follow_the_bound_user(monkeypatch):
    monkeypatch.setattr(internal_auth, "TOKEN", "shared-secret")
    assert internal_auth.requester_meta() is None
    assert internal_auth.outbound_headers() == {"X-Internal-Token": "shared-secret"}

    token = internal_auth.bind_requester(Requester("alice", "alice@example.com"))
    try:
        assert internal_auth.requester_meta() == {"requester": {"username": "alice", "email": "alice@example.com"}}
        assert internal_auth.outbound_headers() == {
            "X-Internal-Token": "shared-secret",
            "X-Requester-Username": "alice",
            "X-Requester-Email": "alice@example.com",
        }
    finally:
        internal_auth.reset_requester(token)
    assert internal_auth.current_requester() == Requester()


def test_requester_from_headers_ignores_non_strings():
    assert Requester.from_headers(None) == Requester()
    assert Requester.from_headers(MagicMock()) == Requester()
    assert Requester.from_headers({"X-Requester-Username": "bob"}) == Requester("bob", "")


def test_ask_binds_the_requester_from_the_request_headers():
    seen: list[Requester] = []

    async def fake_run_chat(question, history, enabled_extensions, request_id, depth, on_event=None, caveman=False, approval_mode="off", allowed_tools=None):
        seen.append(internal_auth.current_requester())
        return ChatResult(response="done")

    ctx = MagicMock()
    ctx.report_progress = AsyncMock()
    ctx.request_context.request.headers = {"X-Requester-Username": "alice", "X-Requester-Email": "a@example.com"}

    with patch("src.server.agent_config.run_chat", new=fake_run_chat), \
         patch("src.server.agent_config.status", return_value={"model": "m", "context_window": 1}):
        asyncio.run(server.ask("q", ctx=ctx))

    assert seen == [Requester("alice", "a@example.com")]
    assert internal_auth.current_requester() == Requester()  # reset afterwards


def test_mcp_upstream_call_tool_sends_the_requester_as_meta():
    fake_result = type("R", (), {"content": [type("B", (), {"text": "ok"})()]})()
    with patch.object(mcp_upstream.client, "call_tool", return_value=fake_result) as call_tool:
        token = internal_auth.bind_requester(Requester("alice", ""))
        try:
            mcp_upstream.call_tool("main__t", {})
        finally:
            internal_auth.reset_requester(token)

    call_tool.assert_called_once_with("main__t", {}, meta={"requester": {"username": "alice", "email": ""}})


def test_registry_call_tool_forwards_meta_to_the_session():
    registry = McpClientRegistry()
    session = AsyncMock()
    registry._sessions["main"] = session

    asyncio.run(registry.call_tool("main__t", {"a": 1}, meta={"requester": {"username": "alice"}}))

    assert session.call_tool.await_args.kwargs["meta"] == {"requester": {"username": "alice"}}


def test_delegation_sends_token_and_requester_to_the_peer(monkeypatch):
    monkeypatch.setattr(internal_auth, "TOKEN", "shared-secret")
    opened: dict = {}

    class FakeTransport:
        def __init__(self, url, headers=None):
            opened["headers"] = headers

        async def __aenter__(self):
            raise ConnectionError("stop here")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(delegation, "streamablehttp_client", FakeTransport)
    token = internal_auth.bind_requester(Requester("alice", "a@example.com"))
    try:
        try:
            asyncio.run(delegation._call_tool("http://peer/mcp", "ask", {}))
        except ConnectionError:
            pass
    finally:
        internal_auth.reset_requester(token)

    assert opened["headers"] == {
        "X-Internal-Token": "shared-secret",
        "X-Requester-Username": "alice",
        "X-Requester-Email": "a@example.com",
    }


def test_registry_requires_the_token_like_mcp():
    app = Starlette()
    app.add_route("/registry", lambda request: PlainTextResponse("agents"), methods=["GET"])
    app.add_middleware(InternalTokenMiddleware, token="shared-secret")
    client = TestClient(app)

    assert client.get("/registry").status_code == 401
    assert client.get("/registry", headers={"X-Internal-Token": "guess"}).status_code == 401
    assert client.get("/registry", headers={"X-Internal-Token": "shared-secret"}).text == "agents"
