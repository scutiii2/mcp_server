from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from src.app import create_app
from src.config import SecuritySettings, Settings, UsageSettings
from src.services.agent_gateway import AgentCallError, Caller
from src.services.email_service import EmailDeliveryError
from src.services.server_tools import ServerUnavailable, WatcherReport

ADMIN_USERNAME = "root"
ADMIN_PASSWORD = "correct horse battery"


@dataclass
class FakeEmailSender:
    """Records what would have been emailed; `fail` simulates SMTP being down."""

    sent: list[tuple[str, str, str]] = field(default_factory=list)  # (kind, to, code)
    fail: bool = False

    async def send_invite(self, to: str, code: str, expires_at: datetime) -> None:
        self._record("invite", to, code)

    async def send_email_verification(self, to: str, code: str, expires_at: datetime) -> None:
        self._record("verify", to, code)

    def _record(self, kind: str, to: str, code: str) -> None:
        if self.fail:
            raise EmailDeliveryError("SMTP is down (fake)")
        self.sent.append((kind, to, code))

    def last_code(self, kind: str) -> str:
        return next(code for k, _to, code in reversed(self.sent) if k == kind)


AGENTS = [
    {"id": "claude-agent", "label": "Claude Agent", "url": "http://agent-a.internal/mcp"},
    {"id": "openai-agent", "label": "OpenAI Agent", "url": "http://agent-b.internal/mcp"},
]
MCP_SERVER_URL = "http://mcp-server.internal/mcp"


@dataclass
class FakeUpstream:
    """Stands in for ai_agent/mcp_server behind the proxy. Records every
    request it gets; `handler` decides the response (default: an empty
    JSON-RPC result carrying a session id)."""

    requests: list[httpx.Request] = field(default_factory=list)
    handler: Callable[[httpx.Request], httpx.Response] | None = None
    unreachable: bool = False

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        await request.aread()
        self.requests.append(request)
        if self.unreachable:
            raise httpx.ConnectError("connection refused (fake)", request=request)
        if self.handler:
            return self.handler(request)
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": 1, "result": {}}, headers={"mcp-session-id": "sess-1"}
        )


@dataclass
class FakeAgent:
    """Stands in for ai_agent behind ember_api's own MCP client (the
    AgentGateway). By default ask() streams two tokens and answers "Hello!";
    tests change `answer`, `events`, `fail`, or set `hold` to keep a turn
    running until release() (or a cancel) lets it finish."""

    answer: str = "Hello!"
    events: list[dict] = field(
        default_factory=lambda: [{"type": "token", "text": "Hel"}, {"type": "token", "text": "lo!"}]
    )
    result_extra: dict = field(default_factory=dict)
    fail: str | None = None
    hold: bool = False
    summary: str = "SUMMARY"
    asks: list[dict] = field(default_factory=list)
    interprets: list[str] = field(default_factory=list)
    cancels: list[str] = field(default_factory=list)
    gate: Any = None

    loop: Any = None

    def release(self) -> None:
        """Safe from the test thread: the gate lives on the app's loop."""
        if self.gate is not None:
            self.loop.call_soon_threadsafe(self.gate.set)

    async def ask(self, url, caller: Caller, *, question, history, request_id, caveman, enabled_extensions, on_event):
        self.asks.append(
            {
                "url": url,
                "caller": caller,
                "question": question,
                "history": history,
                "request_id": request_id,
                "caveman": caveman,
                "enabled_extensions": enabled_extensions,
            }
        )
        for event in self.events:
            await on_event(event)
        if self.hold:
            self.loop = asyncio.get_running_loop()
            self.gate = asyncio.Event()
            await self.gate.wait()
        if self.fail:
            raise AgentCallError(self.fail)
        cancelled = request_id in self.cancels
        return {
            "response": "Cancelled." if cancelled else self.answer,
            "cancelled": cancelled,
            "provider_id": "claude",
            "model": "claude-test",
            "total_tokens": 100,
            "input_tokens": 70,
            "output_tokens": 30,
            "context_tokens": 1000,
            "context_window": 200000,
            "agent_usage": [
                {"provider_id": "claude", "model": "claude-test", "input_tokens": 70, "output_tokens": 30, "total_tokens": 100}
            ],
            **self.result_extra,
        }

    async def interpret(self, url, caller, text):
        self.interprets.append(text)
        if self.fail:
            raise AgentCallError(self.fail)
        return {"response": self.summary, "provider_id": "claude", "model": "claude-test", "total_tokens": 10}

    async def cancel(self, url, caller, request_id):
        self.cancels.append(request_id)
        self.release()
        return True


@dataclass
class FakeServerTools:
    """Stands in for ember_api's own MCP client to mcp_server."""

    report: WatcherReport = field(default_factory=WatcherReport)
    unreachable: bool = False
    callers: list[Caller] = field(default_factory=list)

    async def watchers(self, caller: Caller) -> WatcherReport:
        self.callers.append(caller)
        if self.unreachable:
            raise ServerUnavailable("connection refused (fake)")
        return self.report


def make_settings(
    tmp_path: Path,
    *,
    admin_password: str = ADMIN_PASSWORD,
    session_hours: int = 12,
    internal_token: str = "",
    security: SecuritySettings | None = None,
    usage: UsageSettings | None = None,
) -> Settings:
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir(exist_ok=True)
    (secrets_dir / "secret_internal_api.env").write_text(f"INTERNAL_API_TOKEN={internal_token}\n", encoding="utf-8")
    registry = tmp_path / "config_agents.json"
    registry.write_text(json.dumps({"agents": AGENTS}), encoding="utf-8")
    (secrets_dir / "secret_bootstrap_admin.env").write_text(
        f"BOOTSTRAP_ADMIN_USERNAME={ADMIN_USERNAME}\n"
        "BOOTSTRAP_ADMIN_EMAIL=root@example.com\n"
        f"BOOTSTRAP_ADMIN_PASSWORD={admin_password}\n",
        encoding="utf-8",
    )
    return Settings(
        host="127.0.0.1",
        port=0,
        database_path=tmp_path / "data" / "test.db",
        session_cookie_name="ember_session",
        session_hours=session_hours,
        cookie_secure=False,  # TestClient talks plain http
        secrets_dir=secrets_dir,
        agents_registry_path=registry,
        mcp_server_url=MCP_SERVER_URL,
        security=security or SecuritySettings(),
        usage=usage or UsageSettings(),
        config_path=tmp_path / "config_app.json",
    )


@pytest.fixture
def email() -> FakeEmailSender:
    return FakeEmailSender()


@pytest.fixture
def upstream() -> FakeUpstream:
    return FakeUpstream()


@pytest.fixture
def agent() -> FakeAgent:
    return FakeAgent()


@pytest.fixture
def server_tools() -> FakeServerTools:
    return FakeServerTools()


@pytest.fixture
def client_factory(
    tmp_path: Path, email: FakeEmailSender, upstream: FakeUpstream, agent: FakeAgent, server_tools: FakeServerTools
) -> Iterator[Callable[..., TestClient]]:
    """Builds a started app (lifespan run) per call; all are closed at the end."""
    opened: list[TestClient] = []

    def factory(address: str = "testclient", **kwargs) -> TestClient:
        """address: the socket peer the app sees (default: Starlette's
        "testclient"), for tests that depend on the client IP."""
        client = TestClient(
            create_app(
                make_settings(tmp_path, **kwargs),
                email_sender=email,
                upstream_transport=httpx.MockTransport(upstream),
                agent_gateway=agent,
                server_tools=server_tools,
            ),
            client=(address, 50000),
        )
        client.__enter__()
        opened.append(client)
        return client

    yield factory
    for client in opened:
        client.__exit__(None, None, None)


@pytest.fixture
def client(client_factory) -> TestClient:
    return client_factory()
