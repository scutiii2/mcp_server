"""Traffic counters: bands, the recorder's memory and flush, the middleware,
and the upstream timing around the proxy, the agent gateway and the server tools."""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp.server.fastmcp import FastMCP
from pydantic import Field
from sqlalchemy import select

from src.db import Database
from src.models import TrafficBucket
from src.services.agent_gateway import AgentCallError, Caller, McpAgentGateway
from src.services.mcp_server_info import McpServerInfo, McpServerUnavailable, _traffic_name
from src.services.server_tools import McpServerTools, ServerUnavailable
from src.services.traffic import (
    LATENCY_BANDS_MS,
    RETENTION_DAYS,
    TrafficMiddleware,
    TrafficRecorder,
    latency_band,
    status_class,
)
from tests.conftest import FakeUpstream
from tests.test_agent_gateway import CALLER, agent_url  # noqa: F401 - a real fake agent server
from tests.test_mcp_proxy import AGENT_PATH, SERVER_PATH, post, rpc
from tests.test_registration import as_admin

HOUR = datetime(2026, 10, 5, 14, 0)
NOW = datetime(2026, 10, 5, 14, 37, 12, 345)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def server_url() -> Iterator[str]:
    mcp = FastMCP("fake-mcp-server")

    @mcp.tool()
    def tool_deploy_start(app: Annotated[str, Field(json_schema_extra={"options_url": "/options/apps"})] = "") -> str:
        return "started"

    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(mcp.streamable_http_app(), host="127.0.0.1", port=port, log_level="warning")
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


def recorder(database: Database | None = None, now: datetime = NOW) -> TrafficRecorder:
    return TrafficRecorder(database, clock=lambda: now)


async def saved(database: Database) -> list[TrafficBucket]:
    async with database.sessions() as session:
        return list((await session.execute(select(TrafficBucket).order_by(TrafficBucket.name))).scalars())


@pytest.fixture
def database(tmp_path: Path) -> Database:
    db = Database(f"sqlite+aiosqlite:///{(tmp_path / 'traffic.db').as_posix()}")
    asyncio.run(db.create_tables())
    yield db
    asyncio.run(db.dispose())


def seen(counter: TrafficRecorder, kind: str) -> dict[tuple[str, str, int], tuple[int, int]]:
    return {(name, status, band): cell for (k, name, status, band), cell in counter.pending().items() if k == kind}


# --- bands -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ms", "band"),
    [(0, 0), (50, 0), (50.1, 1), (100, 1), (250, 2), (500, 3), (1000, 4), (2500, 5), (5000, 6), (5000.1, 7), (90_000, 7)],
)
def test_latency_bands(ms: float, band: int) -> None:
    assert latency_band(ms) == band
    assert LATENCY_BANDS_MS[-1] is None  # the last band has no bound


def test_status_classes() -> None:
    assert [status_class(code) for code in (200, 304, 404, 500, 503)] == ["2xx", "3xx", "4xx", "5xx", "5xx"]


# --- the recorder's memory ---------------------------------------------------------


def test_counts_add_up_per_name_status_and_band() -> None:
    counter = recorder()

    counter.record_http("GET", "/api/chats", 200, 20)
    counter.record_http("GET", "/api/chats", 200, 30)
    counter.record_http("GET", "/api/chats", 500, 30)
    counter.record_http("GET", "/api/chats", 200, 300)

    assert seen(counter, "http") == {
        ("GET /api/chats", "2xx", 0): (2, 50),
        ("GET /api/chats", "5xx", 0): (1, 30),
        ("GET /api/chats", "2xx", 3): (1, 300),
    }


def test_hours_are_kept_apart() -> None:
    times = iter([NOW, NOW + timedelta(hours=1)])
    counter = TrafficRecorder(clock=lambda: next(times))

    counter.record("http", "GET /x", "2xx", 1)
    counter.record("http", "GET /x", "2xx", 1)

    assert sorted(hour for hour, *_ in counter._counts) == [HOUR, HOUR + timedelta(hours=1)]


def test_a_long_name_is_cut_to_the_column() -> None:
    counter = recorder()

    counter.record("http", "GET /" + "x" * 500, "2xx", 1)

    assert all(len(name) == 200 for _kind, name, _status, _band in counter.pending())


def test_timed_counts_ok_and_failed_calls() -> None:
    counter = recorder()

    with counter.timed("ai_agent", "ask"):
        pass
    with pytest.raises(RuntimeError), counter.timed("ai_agent", "ask"):
        raise RuntimeError("boom")

    names = {(name, status) for name, status, _band in seen(counter, "upstream")}
    assert names == {("ai_agent ask", "ok"), ("ai_agent ask", "failed")}


def test_timed_keeps_a_refusal_as_ok() -> None:
    counter = recorder()

    with pytest.raises(ValueError), counter.timed("mcp_server", "GET /x") as timing:
        timing.ok = True
        raise ValueError("a 4xx the server answered")

    assert {status for _name, status, _band in seen(counter, "upstream")} == {"ok"}


def test_timed_does_not_count_a_cancelled_call() -> None:
    counter = recorder()

    async def stopped() -> None:
        with counter.timed("ai_agent", "ask"):
            await asyncio.sleep(60)

    async def run() -> None:
        task = asyncio.create_task(stopped())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())

    assert counter.pending() == {}


# --- saving ------------------------------------------------------------------------


def test_flush_saves_and_a_second_flush_adds_to_the_same_rows(database: Database) -> None:
    counter = recorder(database)
    counter.record_http("GET", "/api/chats", 200, 20)
    counter.record_http("GET", "/api/chats", 200, 30)

    asyncio.run(counter.flush())
    counter.record_http("GET", "/api/chats", 200, 40)
    asyncio.run(counter.flush())

    rows = asyncio.run(saved(database))
    assert [(r.hour, r.kind, r.name, r.status, r.band, r.count, r.total_ms) for r in rows] == [
        (HOUR, "http", "GET /api/chats", "2xx", 0, 3, 90)
    ]
    assert counter.pending() == {}


def test_flush_with_nothing_counted_writes_nothing(database: Database) -> None:
    asyncio.run(recorder(database).flush())

    assert asyncio.run(saved(database)) == []


def test_a_failed_flush_keeps_the_counts_for_the_next_one(database: Database) -> None:
    counter = recorder(database)
    counter.record_http("GET", "/api/chats", 200, 20)
    asyncio.run(database.dispose())
    # A database that cannot be written to: the table is gone.
    async def drop() -> None:
        async with database.engine.begin() as conn:
            await conn.exec_driver_sql("DROP TABLE traffic_buckets")

    asyncio.run(drop())

    asyncio.run(counter.flush())  # logs the failure, raises nothing

    assert seen(counter, "http") == {("GET /api/chats", "2xx", 0): (1, 20)}
    asyncio.run(database.create_tables())
    asyncio.run(counter.flush())
    assert [r.count for r in asyncio.run(saved(database))] == [1]


def test_purge_old_deletes_only_buckets_past_retention(database: Database) -> None:
    old = NOW - timedelta(days=RETENTION_DAYS + 1)
    old_counter, fresh_counter = recorder(database, old), recorder(database, NOW)
    old_counter.record("http", "GET /old", "2xx", 1)
    fresh_counter.record("http", "GET /fresh", "2xx", 1)
    asyncio.run(old_counter.flush())
    asyncio.run(fresh_counter.flush())

    assert asyncio.run(fresh_counter.purge_old()) == 1

    assert [r.name for r in asyncio.run(saved(database))] == ["GET /fresh"]


def test_the_background_task_flushes_and_stop_saves_the_rest(database: Database) -> None:
    async def run() -> None:
        ticks = asyncio.Queue[None]()

        async def sleep(_seconds: float) -> None:
            await ticks.get()

        counter = TrafficRecorder(database, clock=lambda: NOW, sleep=sleep)
        counter.start()
        counter.record("http", "GET /a", "2xx", 1)
        ticks.put_nowait(None)
        for _ in range(50):  # let the task run its flush
            await asyncio.sleep(0.01)
            if await saved(database):
                break
        assert [r.name for r in await saved(database)] == ["GET /a"]

        counter.record("http", "GET /b", "2xx", 1)
        await counter.stop()
        assert [r.name for r in await saved(database)] == ["GET /a", "GET /b"]

    asyncio.run(run())


# --- the middleware ----------------------------------------------------------------


def test_requests_are_counted_by_route_template_not_by_path(client: TestClient, traffic: TrafficRecorder) -> None:
    as_admin(client)
    traffic._counts.clear()

    client.get("/api/chats/does-not-exist")
    client.get("/api/chats/another-one?secret=1")

    names = {(name, status) for name, status, _band in seen(traffic, "http")}
    assert names == {("GET /api/chats/{chat_id}", "4xx")}
    assert sum(count for count, _ms in seen(traffic, "http").values()) == 2


def test_routes_that_do_not_exist_share_one_name(client: TestClient, traffic: TrafficRecorder) -> None:
    client.get("/wp-login.php")
    client.get("/.env")

    assert {(name, status) for name, status, _band in seen(traffic, "http")} == {("ANY unmatched", "4xx")}


def test_the_health_check_is_not_counted(client: TestClient, traffic: TrafficRecorder) -> None:
    assert client.get("/api/health").status_code == 200

    assert traffic.pending() == {}


def test_nothing_personal_is_kept(client: TestClient, traffic: TrafficRecorder) -> None:
    as_admin(client)
    client.get("/api/auth/me?token=abc123")

    text = repr(traffic._counts)
    for private in ("abc123", "root", "testclient", "correct horse"):
        assert private not in text


def test_an_unhandled_error_is_counted_as_5xx() -> None:
    counter = recorder()
    app = FastAPI()
    app.state.traffic = counter

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("boom")

    app.add_middleware(TrafficMiddleware)

    with pytest.raises(RuntimeError), TestClient(app) as test_client:
        test_client.get("/boom")

    assert {(name, status) for name, status, _band in seen(counter, "http")} == {("GET /boom", "5xx")}


def test_without_a_recorder_the_middleware_just_passes_through() -> None:
    app = FastAPI()

    @app.get("/ok")
    async def ok() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(TrafficMiddleware)

    assert TestClient(app).get("/ok").json() == {"ok": True}


# --- upstream calls ----------------------------------------------------------------


def upstream_seen(traffic: TrafficRecorder) -> set[tuple[str, str]]:
    return {(name, status) for name, status, _band in seen(traffic, "upstream")}


def test_the_proxy_counts_each_target(client: TestClient, traffic: TrafficRecorder) -> None:
    as_admin(client)

    post(client, AGENT_PATH, rpc("initialize", {}))
    post(client, SERVER_PATH, rpc("tools/list"))

    assert upstream_seen(traffic) == {("ai_agent proxy POST", "ok"), ("mcp_server proxy POST", "ok")}


def test_the_proxy_counts_an_unreachable_upstream_and_a_5xx_as_failed(
    client: TestClient, traffic: TrafficRecorder, upstream: FakeUpstream
) -> None:
    as_admin(client)
    upstream.unreachable = True
    post(client, AGENT_PATH, rpc("initialize", {}))
    upstream.unreachable = False
    upstream.handler = lambda request: httpx.Response(503)
    post(client, SERVER_PATH, rpc("tools/list"))

    assert upstream_seen(traffic) == {("ai_agent proxy POST", "failed"), ("mcp_server proxy POST", "failed")}


def test_a_call_the_policy_refuses_never_reaches_the_upstream_counters(
    client: TestClient, traffic: TrafficRecorder
) -> None:
    as_admin(client)

    post(client, AGENT_PATH, rpc("tools/call", {"name": "ask", "arguments": {}}))

    assert upstream_seen(traffic) == set()


def test_the_real_gateway_counts_a_call(agent_url: str) -> None:  # noqa: F811
    counter = recorder()

    asyncio.run(McpAgentGateway(None, counter).interpret(agent_url, CALLER, "sum"))

    assert upstream_seen(counter) == {("ai_agent interpret", "ok")}


def test_the_real_gateway_counts_an_unreachable_agent_as_failed() -> None:
    counter = recorder()
    gateway = McpAgentGateway(None, counter)

    with pytest.raises(AgentCallError):
        asyncio.run(gateway.cancel(f"http://127.0.0.1:{_free_port()}/mcp", CALLER, "r1"))

    assert upstream_seen(counter) == {("ai_agent cancel", "failed")}


def test_the_real_server_tools_count_a_call(server_url: str) -> None:  # noqa: F811
    counter = recorder()

    templates = asyncio.run(McpServerTools(server_url, None, counter).options_templates(Caller("alice", "a@example.com")))

    assert templates == {"/options/apps"}
    assert upstream_seen(counter) == {("mcp_server options_templates", "ok")}


def test_the_real_server_tools_count_an_unreachable_server_as_failed() -> None:
    counter = recorder()
    tools = McpServerTools(f"http://127.0.0.1:{_free_port()}/mcp", None, counter)

    with pytest.raises(ServerUnavailable):
        asyncio.run(tools.options_templates(Caller("alice", "alice@example.com")))

    assert upstream_seen(counter) == {("mcp_server options_templates", "failed")}


def test_server_info_counts_by_first_path_segment() -> None:
    assert _traffic_name("GET", "/commands/help/deploy?target=x") == "GET /commands"
    assert _traffic_name("PATCH", "/capabilities/mail") == "PATCH /capabilities"
    assert _traffic_name("GET", "/options/apps?q=1") == "GET /options"


def test_server_info_counts_ok_refused_and_failed() -> None:
    from src.models import Account

    counter = recorder()
    account = Account(username="alice", email="alice@example.com")
    answers = iter([httpx.Response(200, json=[]), httpx.Response(403, json={"error": "no"}), httpx.Response(502)])

    async def handler(request: httpx.Request) -> httpx.Response:
        return next(answers)

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            info = McpServerInfo(client, "http://mcp.internal/mcp", None, counter)
            await info.commands(account)
            with pytest.raises(Exception):  # noqa: B017 - McpServerRefused, 403
                await info.capabilities(account)
            with pytest.raises(McpServerUnavailable):
                await info.help_index(account)

    asyncio.run(run())

    assert upstream_seen(counter) == {
        ("mcp_server GET /commands", "ok"),
        ("mcp_server GET /capabilities", "ok"),  # refused: the server answered
        ("mcp_server GET /commands", "failed"),
    }


def test_the_default_recorder_saves_to_the_database_on_shutdown(tmp_path: Path) -> None:
    """create_app without a recorder of its own: counted in memory, saved when the app stops."""
    import sqlite3
    from contextlib import closing

    from src.app import create_app
    from tests.conftest import make_settings

    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as app_client:
        app_client.get("/api/auth/me")

    with closing(sqlite3.connect(settings.database_path)) as conn:
        rows = conn.execute("SELECT kind, name, status, count FROM traffic_buckets").fetchall()
    assert rows == [("http", "GET /api/auth/me", "4xx", 1)]
