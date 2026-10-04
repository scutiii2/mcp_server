"""Tests for InternalTokenMiddleware (the /mcp token check) and the
_meta.requester fallback in identity_context."""

from __future__ import annotations

import asyncio
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.fastmcp import FastMCP
from mcp.server.lowlevel.server import request_ctx
from mcp.shared.context import RequestContext
from mcp.types import RequestParams
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.testclient import TestClient

from src.services import identity_context
from src.services.identity_context import IdentityContextMiddleware
from src.services.internal_token import InternalTokenMiddleware


def _client(token: str) -> TestClient:
    app = Starlette()
    app.add_route("/mcp", lambda request: PlainTextResponse("mcp"), methods=["POST"])
    app.add_route("/commands", lambda request: PlainTextResponse("commands"), methods=["GET"])
    app.add_middleware(InternalTokenMiddleware, token=token)
    return TestClient(app)


def test_mcp_without_token_is_a_401_when_configured():
    response = _client("shared-secret").post("/mcp")

    assert response.status_code == 401
    assert response.json() == {"error": "Invalid or missing internal API token"}


def test_mcp_with_wrong_token_is_a_401():
    response = _client("shared-secret").post("/mcp", headers={"X-Internal-Token": "guess"})

    assert response.status_code == 401


def test_mcp_with_right_token_passes():
    response = _client("shared-secret").post("/mcp", headers={"X-Internal-Token": "shared-secret"})

    assert response.status_code == 200
    assert response.text == "mcp"


def test_other_paths_are_not_checked():
    assert _client("shared-secret").get("/commands").status_code == 200


def test_no_token_configured_leaves_mcp_open():
    assert _client("").post("/mcp").status_code == 200


@pytest.fixture
def mcp_request_meta():
    """Bind a fake MCP request context whose _meta is the given dict."""
    tokens = []

    def bind(meta: dict | None) -> None:
        context = RequestContext(
            request_id=1,
            meta=RequestParams.Meta(**meta) if meta is not None else None,
            session=None,
            lifespan_context=None,
        )
        tokens.append(request_ctx.set(context))

    yield bind
    for token in reversed(tokens):
        request_ctx.reset(token)


def test_identity_falls_back_to_request_meta(mcp_request_meta):
    mcp_request_meta({"requester": {"username": "alice", "email": "alice@example.com"}})

    assert identity_context.current_username() == "alice"
    assert identity_context.current_email() == "alice@example.com"


def test_identity_is_empty_without_meta_or_request(mcp_request_meta):
    assert identity_context.current_username() == ""
    mcp_request_meta(None)
    assert identity_context.current_username() == ""
    mcp_request_meta({"requester": "not-a-dict"})
    assert identity_context.current_email() == ""


def test_identity_header_wins_over_meta(mcp_request_meta):
    mcp_request_meta({"requester": {"username": "from-meta"}})
    token = identity_context._username.set("from-header")
    try:
        assert identity_context.current_username() == "from-header"
    finally:
        identity_context._username.reset(token)


# --- end to end: a real streamable-HTTP server behind both middlewares ---


@pytest.fixture(scope="module")
def live_url():
    mcp = FastMCP("token-test")

    @mcp.tool()
    def whoami() -> str:
        return f"{identity_context.current_username()}|{identity_context.current_email()}"

    app = mcp.streamable_http_app()
    app.add_middleware(IdentityContextMiddleware)
    app.add_middleware(InternalTokenMiddleware, token="shared-secret")

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "test server didn't start"
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    thread.join(timeout=5)


async def _whoami(url: str, headers: dict[str, str], meta: dict | None = None) -> str:
    async with streamablehttp_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("whoami", {}, meta=meta)
    return result.content[0].text


def test_live_mcp_rejects_a_missing_token(live_url):
    response = httpx.post(live_url, json={}, headers={"Accept": "application/json, text/event-stream"})

    assert response.status_code == 401


def test_live_identity_from_headers(live_url):
    headers = {"X-Internal-Token": "shared-secret", "X-Requester-Username": "carol", "X-Requester-Email": "c@x.io"}

    assert asyncio.run(_whoami(live_url, headers)) == "carol|c@x.io"


def test_live_identity_from_call_meta(live_url):
    """ai_agent's shared session: no identity headers, the user rides in _meta."""
    meta = {"requester": {"username": "alice", "email": "alice@example.com"}}

    assert asyncio.run(_whoami(live_url, {"X-Internal-Token": "shared-secret"}, meta)) == "alice|alice@example.com"
