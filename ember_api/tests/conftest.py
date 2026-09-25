from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from src.app import create_app
from src.config import Settings
from src.services.email_service import EmailDeliveryError

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


def make_settings(
    tmp_path: Path,
    *,
    admin_password: str = ADMIN_PASSWORD,
    session_hours: int = 12,
    internal_token: str = "",
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
    )


@pytest.fixture
def email() -> FakeEmailSender:
    return FakeEmailSender()


@pytest.fixture
def upstream() -> FakeUpstream:
    return FakeUpstream()


@pytest.fixture
def client_factory(
    tmp_path: Path, email: FakeEmailSender, upstream: FakeUpstream
) -> Iterator[Callable[..., TestClient]]:
    """Builds a started app (lifespan run) per call; all are closed at the end."""
    opened: list[TestClient] = []

    def factory(**kwargs) -> TestClient:
        client = TestClient(
            create_app(
                make_settings(tmp_path, **kwargs),
                email_sender=email,
                upstream_transport=httpx.MockTransport(upstream),
            )
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
