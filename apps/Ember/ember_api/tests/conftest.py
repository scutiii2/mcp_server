from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from src.app import create_app
from src.config import BackupSettings, SecuritySettings, Settings, UsageSettings
from src.services import otp_service
from src.services.agent_gateway import AgentCallError, Caller
from src.services.email_service import EmailDeliveryError
from src.services.ascension_gateway import AscensionRefused, AscensionUnavailable
from src.services.server_tools import ServerUnavailable
from src.services.traffic import TrafficRecorder

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
    # Tools this fake "wants to run" during a turn. With approval_mode "ask"
    # it raises an approval_request for each (unless allowed already), waits
    # for decide(), and runs or refuses it, like the real agent.
    tool_calls: list[str] = field(default_factory=list)
    decisions: list[tuple[str, str, str]] = field(default_factory=list)
    decide_result: bool | None = None  # force decide()'s answer
    decide_error: str | None = None
    # A question this fake "asks" during a turn (the questions list of an ask_user call).
    questions: list[dict] = field(default_factory=list)
    answers: list[tuple] = field(default_factory=list)  # (request_id, step_id, answers, skipped)
    answer_result: bool | None = None  # force answer_question()'s result
    answer_error: str | None = None
    _asking: dict = field(default_factory=dict)
    ran: list[str] = field(default_factory=list)  # tools that actually ran
    # Private extensions: what probe_extension() was asked, what it answers per URL
    # (default: connected with two tools), and a forced failure.
    probes: list = field(default_factory=list)
    probe_results: dict = field(default_factory=dict)
    probe_fail: str | None = None
    _waiting: dict = field(default_factory=dict)

    loop: Any = None

    def release(self) -> None:
        """Safe from the test thread: the gate lives on the app's loop."""
        if self.gate is not None:
            self.loop.call_soon_threadsafe(self.gate.set)

    async def ask(
        self,
        url,
        caller: Caller,
        *,
        question,
        history,
        request_id,
        caveman,
        enabled_extensions,
        on_event,
        approval_mode="off",
        allowed_tools=None,
        disabled_tools=None,
        ask_user=False,
        private_extensions=None,
    ):
        self.asks.append(
            {
                "url": url,
                "caller": caller,
                "question": question,
                "history": history,
                "request_id": request_id,
                "caveman": caveman,
                "enabled_extensions": enabled_extensions,
                "approval_mode": approval_mode,
                "allowed_tools": allowed_tools,
                "disabled_tools": disabled_tools,
                "ask_user": ask_user,
                "private_extensions": private_extensions,
            }
        )
        for event in self.events:
            await on_event(event)
        for index, tool in enumerate(self.tool_calls):
            await self._run_tool(f"step{index}", tool, request_id, approval_mode, allowed_tools or [], on_event)
        if self.questions:
            await self._ask_user("q1", request_id, on_event)
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

    async def _run_tool(self, step_id, tool, request_id, approval_mode, allowed_tools, on_event):
        await on_event({"type": "step_start", "id": step_id, "tool": tool, "label": tool.upper(), "arguments": {"a": 1}})
        approved = True
        # Like the real agent: a private tool (u_...) asks even when approvals are off.
        if (approval_mode == "ask" or tool.startswith("u_")) and tool not in allowed_tools:
            waiting = asyncio.get_running_loop().create_future()
            self._waiting[(request_id, step_id)] = waiting
            await on_event(
                {"type": "approval_request", "id": step_id, "tool": tool, "label": tool.upper(), "arguments": {"a": 1}}
            )
            decision = await waiting
            del self._waiting[(request_id, step_id)]
            await on_event({"type": "approval_resolved", "id": step_id, "outcome": decision})
            approved = decision in ("allow", "always")
        if approved:
            self.ran.append(tool)
        await on_event(
            {"type": "step_end", "id": step_id, "ok": approved, "result": "done" if approved else "The user declined."}
        )

    async def decide(self, url, caller, request_id, step_id, decision):
        if self.decide_error:
            raise AgentCallError(self.decide_error)
        self.decisions.append((request_id, step_id, decision))
        waiting = self._waiting.get((request_id, step_id))
        if self.decide_result is not None:
            answered = self.decide_result
        else:
            answered = waiting is not None and not waiting.done()
        if answered and waiting is not None and not waiting.done():
            waiting.set_result(decision)
        return answered

    async def _ask_user(self, step_id, request_id, on_event):
        self.loop = asyncio.get_running_loop()
        await on_event(
            {"type": "step_start", "id": step_id, "tool": "ask_user", "label": None, "arguments": {"questions": self.questions}}
        )
        waiting = asyncio.get_running_loop().create_future()
        self._asking[(request_id, step_id)] = waiting
        await on_event({"type": "question_request", "id": step_id, "questions": self.questions})
        outcome = await waiting
        del self._asking[(request_id, step_id)]
        await on_event({"type": "question_resolved", "id": step_id, "outcome": outcome})
        await on_event({"type": "step_end", "id": step_id, "ok": outcome != "cancelled", "result": f"outcome: {outcome}"})

    async def answer_question(self, url, caller, request_id, step_id, answers, skipped):
        if self.answer_error:
            raise AgentCallError(self.answer_error)
        self.answers.append((request_id, step_id, answers, skipped))
        waiting = self._asking.get((request_id, step_id))
        known = waiting is not None and not waiting.done()
        if self.answer_result is not None:
            known = self.answer_result
        if known and waiting is not None and not waiting.done():
            waiting.set_result("skipped" if skipped else "answered")
        return known

    async def probe_extension(self, url, caller, *, extension_url, headers):
        self.probes.append({"url": url, "caller": caller, "extension_url": extension_url, "headers": headers})
        if self.probe_fail:
            raise AgentCallError(self.probe_fail)
        return self.probe_results.get(
            extension_url, {"status": "connected", "error": None, "tools": ["add", "search"]}
        )

    async def interpret(self, url, caller, text):
        self.interprets.append(text)
        if self.fail:
            raise AgentCallError(self.fail)
        return {"response": self.summary, "provider_id": "claude", "model": "claude-test", "total_tokens": 10}

    async def cancel(self, url, caller, request_id):
        self.cancels.append(request_id)
        self.release()
        # A tool waiting for the user's answer ends as it does in the real agent.
        for (waiting_request, _step), waiting in list(self._waiting.items()):
            if waiting_request == request_id and not waiting.done():
                waiting.set_result("cancelled")
        for (waiting_request, _step), waiting in list(self._asking.items()):
            if waiting_request == request_id and not waiting.done():
                waiting.set_result("cancelled")
        return True


@dataclass
class FakeServerTools:
    """Stands in for ember_api's own MCP client to mcp_server."""

    unreachable: bool = False
    callers: list[Caller] = field(default_factory=list)
    # options_url templates the fake's tools declare.
    templates: set[str] = field(default_factory=set)

    async def options_templates(self, caller: Caller) -> set[str]:
        self.callers.append(caller)
        if self.unreachable:
            raise ServerUnavailable("connection refused (fake)")
        return set(self.templates)


@dataclass
class FakeAscension:
    """Stands in for mini_games behind AscensionGateway. Records every call;
    `responses` maps (method, path) to a reply (default {"ok": True});
    `refuse` raises AscensionRefused(status, message) and `unavailable`
    raises AscensionUnavailable."""

    calls: list[dict[str, Any]] = field(default_factory=list)
    responses: dict[tuple[str, str], Any] = field(default_factory=dict)
    refuse: tuple[int, str] | None = None
    unavailable: bool = False

    async def request(self, method, path, account, *, json=None, params=None, idempotency_key=None):
        self.calls.append(
            {"method": method, "path": path, "owner": str(account.id), "json": json, "params": params, "key": idempotency_key}
        )
        if self.unavailable:
            raise AscensionUnavailable("connection refused (fake)")
        if self.refuse is not None:
            raise AscensionRefused(*self.refuse)
        return self.responses.get((method, path), {"ok": True})

    async def reset_profile(self, account, idempotency_key):
        return await self.request("POST", "/ascension/profile/reset", account, json={"confirm": True}, idempotency_key=idempotency_key)


def make_settings(
    tmp_path: Path,
    *,
    admin_password: str = ADMIN_PASSWORD,
    session_hours: int = 12,
    internal_token: str = "",
    security: SecuritySettings | None = None,
    usage: UsageSettings | None = None,
    backup: BackupSettings | None = None,
    require_email_verification: bool = True,
) -> Settings:
    registry = tmp_path / "config_agents.json"
    registry.write_text(json.dumps({"agents": AGENTS}), encoding="utf-8")
    env_path = tmp_path / ".env"
    env_path.write_text(
        f"INTERNAL_API_TOKEN={internal_token}\n"
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
        require_email_verification=require_email_verification,
        env_path=env_path,
        agents_registry_path=registry,
        mcp_server_url=MCP_SERVER_URL,
        security=security or SecuritySettings(),
        usage=usage or UsageSettings(),
        # Off unless a test asks: a background copy of every test's database is noise.
        backup=backup or BackupSettings(enabled=False),
        config_path=tmp_path / "config_app.json",
    )


@pytest.fixture(autouse=True)
def no_verification_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests send verification emails back to back; the cooldown itself is tested in
    test_verification_limits.py, which puts it back."""
    monkeypatch.setattr(otp_service, "VERIFICATION_COOLDOWN", timedelta(0))


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
def ascension() -> FakeAscension:
    return FakeAscension()


@pytest.fixture
def traffic() -> TrafficRecorder:
    """Counts in memory only (no database), so tests read it with pending()."""
    return TrafficRecorder()


@pytest.fixture
def client_factory(
    tmp_path: Path,
    email: FakeEmailSender,
    upstream: FakeUpstream,
    agent: FakeAgent,
    server_tools: FakeServerTools,
    traffic: TrafficRecorder,
    ascension: FakeAscension,
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
                traffic=traffic,
                ascension=ascension,
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
