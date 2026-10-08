"""PrivateSessionPool against a real streamable-HTTP MCP server on loopback.

The other private-extension tests replace the opener with a fake, so none of
them touches the MCP SDK glue (the handshake preflight, the guarded client, the
session). These do. The guard refuses loopback, so each test lets it through.
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from mcp.server.fastmcp import FastMCP

from src.private_extensions import guard
from src.private_extensions.pool import PrivateSessionPool
from src.private_extensions.spec import PrivateSpec

WAIT = 30


def free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class Auth:
    """401 unless the X-Key header is "good"."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and dict(scope["headers"]).get(b"x-key") != b"good":
            await send({"type": "http.response.start", "status": 401, "headers": [(b"content-type", b"text/plain")]})
            await send({"type": "http.response.body", "body": b"nope"})
            return
        await self.app(scope, receive, send)


class Server:
    def __init__(self, port: int):
        self.port = port
        mcp = FastMCP("smoke", port=port)

        @mcp.tool()
        def echo(text: str) -> str:
            """Return text."""
            return text

        config = uvicorn.Config(
            Auth(mcp.streamable_http_app()), host="127.0.0.1", port=port, log_level="warning",
            # Do not wait on a client's open stream when the test ends.
            timeout_graceful_shutdown=1,
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self) -> None:
        self.thread.start()
        deadline = time.time() + 10
        while not self.server.started and time.time() < deadline:
            time.sleep(0.05)
        assert self.server.started

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(10)


@pytest.fixture(autouse=True)
def allow_loopback(monkeypatch):
    monkeypatch.setattr(guard, "is_blocked", lambda address: False)


@pytest.fixture
def server():
    started = Server(free_port())
    started.start()
    yield started
    if started.thread.is_alive():
        started.stop()


def spec_for(port: int, key: str = "good") -> PrivateSpec:
    return PrivateSpec.parse({"id": "smoke", "url": f"http://127.0.0.1:{port}/mcp", "headers": {"X-Key": key}})


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, WAIT))


def test_lists_the_tool_calls_it_and_reuses_the_session(server):
    spec = spec_for(server.port)

    async def go():
        pool = PrivateSessionPool()
        try:
            tools = await pool.tools("a@x", spec)
            first = await pool.call("a@x", spec, "echo", {"text": "hi"})
            second = await pool.call("a@x", spec, "echo", {"text": "again"})
            return [t.name for t in tools], first.content[0].text, second.content[0].text, len(pool._entries)
        finally:
            await pool.aclose()

    assert run(go()) == (["echo"], "hi", "again", 1)


def test_probe_lists_the_tools_and_keeps_nothing(server):
    async def go():
        pool = PrivateSessionPool()
        tools = await pool.probe(spec_for(server.port))
        return [t.name for t in tools], len(pool._entries)

    assert run(go()) == (["echo"], 0)


def test_a_wrong_key_is_an_ordinary_error_and_the_pool_still_works(server):
    async def go():
        pool = PrivateSessionPool()
        try:
            with pytest.raises(ConnectionError) as caught:
                await pool.tools("a@x", spec_for(server.port, key="WRONGSECRET"))
            tools = await pool.tools("a@x", spec_for(server.port))
            return str(caught.value), [t.name for t in tools]
        finally:
            await pool.aclose()

    message, tools = run(go())
    assert "HTTP 401" in message
    assert "WRONGSECRET" not in message
    assert tools == ["echo"]


def test_nothing_listening_is_a_connect_error_and_the_pool_still_works(server):
    dead = PrivateSpec.parse({"id": "dead", "url": f"http://127.0.0.1:{free_port()}/mcp"})

    async def go():
        pool = PrivateSessionPool()
        try:
            with pytest.raises(httpx.ConnectError):
                await pool.tools("a@x", dead)
            return [t.name for t in await pool.tools("a@x", spec_for(server.port))]
        finally:
            await pool.aclose()

    assert run(go()) == ["echo"]


def test_a_restarted_server_is_reconnected_on_the_next_call(server):
    spec = spec_for(server.port)

    async def go():
        pool = PrivateSessionPool()
        try:
            await pool.tools("a@x", spec)
            server.stop()
            restarted = Server(server.port)
            restarted.start()
            try:
                result = await pool.call("a@x", spec, "echo", {"text": "after restart"})
                return result.content[0].text
            finally:
                restarted.stop()
        finally:
            await pool.aclose()

    assert run(go()) == "after restart"


def test_aclose_leaves_nothing(server):
    async def go():
        pool = PrivateSessionPool()
        await pool.tools("a@x", spec_for(server.port))
        await pool.aclose()
        return len(pool._entries)

    assert run(go()) == 0
