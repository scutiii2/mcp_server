"""/api/watchers through a fake mcp_server client, then McpServerTools
against a real MCP server (FastMCP over streamable HTTP)."""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
import uvicorn
from fastapi.testclient import TestClient
from mcp.server.fastmcp import FastMCP

from src.services.agent_gateway import Caller
from src.services.server_tools import McpServerTools, ServerUnavailable, WatcherReport
from tests.conftest import FakeEmailSender, FakeServerTools
from tests.test_admin import login, make_member
from tests.test_registration import as_admin

ROW = {"key": "deploy-42", "phase": "running", "started_at": "2026-09-26T10:00:00Z", "recipients": ["ops@x.io"]}


def test_watchers_are_listed_for_watchers_view(
    client: TestClient, email: FakeEmailSender, server_tools: FakeServerTools
) -> None:
    server_tools.report = WatcherReport(watchers=[{**ROW, "capability": "deploy"}], errors=["mail: timed out"])
    make_member(client, email)
    login(client, "alice")
    assert client.get("/api/watchers").status_code == 403  # Member lacks watchers.view
    client.post("/api/auth/logout", json={})

    as_admin(client)
    response = client.get("/api/watchers")
    assert response.status_code == 200, response.text
    assert response.json() == {"watchers": [{**ROW, "capability": "deploy"}], "errors": ["mail: timed out"]}
    assert server_tools.callers[-1].username == "root"


def test_watchers_report_outages(client: TestClient, server_tools: FakeServerTools) -> None:
    as_admin(client)
    server_tools.report = WatcherReport(errors=["deploy: boom"])
    failed = client.get("/api/watchers")
    assert (failed.status_code, failed.json()["detail"]) == (502, "deploy: boom")

    server_tools.unreachable = True
    assert client.get("/api/watchers").status_code == 502

    server_tools.unreachable = False
    server_tools.report = WatcherReport()
    assert client.get("/api/watchers").json() == {"watchers": [], "errors": []}


# --- the real client ------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _build_server() -> FastMCP:
    mcp = FastMCP("fake-mcp-server")

    @mcp.tool()
    def tool_deploy_listWatchers() -> dict[str, Any]:  # noqa: N802 - mcp_server's naming
        return {"watchers": [ROW]}

    @mcp.tool()
    def tool_mail_listWatchers() -> dict[str, Any]:  # noqa: N802
        raise ValueError("mailbox offline")

    @mcp.tool()
    def tool_deploy_start() -> str:
        return "not a watcher list"

    return mcp


@pytest.fixture(scope="module")
def server_url() -> Iterator[str]:
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(_build_server().streamable_http_app(), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "fake mcp_server didn't start"
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    thread.join(timeout=5)


def test_real_client_collects_every_capabilitys_watchers(server_url: str) -> None:
    report = asyncio.run(McpServerTools(server_url, None).watchers(Caller("alice", "alice@example.com")))
    assert report.watchers == [{**ROW, "capability": "deploy"}]
    assert len(report.errors) == 1 and report.errors[0].startswith("mail: ")
    assert "mailbox offline" in report.errors[0]


def test_real_client_unreachable_server() -> None:
    url = f"http://127.0.0.1:{_free_port()}/mcp"
    with pytest.raises(ServerUnavailable):
        asyncio.run(McpServerTools(url, None).watchers(Caller("alice", "alice@example.com")))
