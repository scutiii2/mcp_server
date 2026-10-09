"""MCP-backed account emails preserve templates and sanitize upstream failures."""

from __future__ import annotations

import asyncio
from datetime import datetime
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from src.services import email_service
from src.services.email_service import EmailDeliveryError, render_template
from src.services.traffic import TrafficRecorder

EXPIRES = datetime(2026, 10, 5, 12, 30)


@pytest.fixture
def transport(monkeypatch):
    calls = []
    setup = []
    state = {"result": SimpleNamespace(isError=False,
        structuredContent={"message_id": "<sent@example.com>", "message": "accepted"}, content=[])}

    class Session:
        async def call_tool(self, name, arguments):
            calls.append((name, arguments))
            if "error" in state:
                raise state["error"]
            return state["result"]

    @asynccontextmanager
    async def session(url, headers, timeout):
        setup.append((url, headers))
        yield Session()

    monkeypatch.setattr(email_service, "mcp_session", session)
    return calls, setup, state


def test_invite_uses_template_and_mcp_config(transport) -> None:
    sender = email_service.McpEmailSender("http://mcp.test/mcp", "internal-secret")
    asyncio.run(sender.send_invite("a@x.com", "ABC123", EXPIRES))
    calls, setup, _ = transport
    name, args = calls[0]
    body = args["body_text"]
    assert "Invite code: ABC123" in body
    assert "2026-10-05 12:30 UTC" in body
    assert "Do not reply" not in body  # The common MCP transport adds the notice once.
    assert name == "tool_email_sendEmail"
    assert args["to"] == "a@x.com" and args["subject"] == "Your Ember invite code"
    assert args["prefix_subject"] is False and args["capability_alias"] == "ember"
    assert setup == [("http://mcp.test/mcp", {"X-Requester-Username": "ember", "X-Requester-Email": "", "X-Internal-Token": "internal-secret"})]


def test_verification_preserves_subject_and_code(transport) -> None:
    asyncio.run(email_service.McpEmailSender("http://mcp.test/mcp", None).send_email_verification("a@x.com", "999", EXPIRES))
    calls, setup, _ = transport
    assert "Your verification code: 999" in calls[0][1]["body_text"]
    assert calls[0][1]["subject"] == "Verify your Ember email"
    assert "X-Internal-Token" not in setup[0][1]


def test_missing_placeholder_raises() -> None:
    with pytest.raises(KeyError):
        render_template("invite", code="x")


@pytest.mark.parametrize("result", [
    SimpleNamespace(isError=True, structuredContent=None, content=[SimpleNamespace(text="private ABC123")]),
    SimpleNamespace(isError=False, structuredContent=None, content=[SimpleNamespace(text="not JSON ABC123")]),
    SimpleNamespace(isError=False, structuredContent=[], content=[]),
    SimpleNamespace(isError=False, structuredContent={"message_id": None}, content=[]),
    SimpleNamespace(isError=False, structuredContent={"message_id": "wrong"}, content=[]),
    SimpleNamespace(isError=False, structuredContent={"message_id": "<bad@example.com>\nprivate"}, content=[]),
    SimpleNamespace(isError=False, structuredContent={"message_id": "<bad\x00@example.com>"}, content=[]),
])
def test_failed_or_malformed_result_is_not_success(transport, result, caplog):
    calls, _, state = transport
    state["result"] = result
    traffic = TrafficRecorder()
    sender = email_service.McpEmailSender("http://mcp.test/mcp", None, traffic)
    with pytest.raises(EmailDeliveryError) as error:
        asyncio.run(sender.send_invite("a@x.com", "ABC123", EXPIRES))
    assert "ABC123" not in str(error.value) + caplog.text
    assert len(calls) == 1
    assert any(key[2] == "failed" for key in traffic.pending())


def test_transport_failure_is_sanitized_without_retry(transport, caplog):
    calls, _, state = transport
    state["error"] = OSError("private ABC123 internal-secret")
    with pytest.raises(EmailDeliveryError) as error:
        asyncio.run(email_service.McpEmailSender("http://mcp.test/mcp", None).send_invite("a@x.com", "ABC123", EXPIRES))
    assert "ABC123" not in str(error.value) + caplog.text
    assert len(calls) == 1


def test_json_content_fallback_and_traffic_do_not_store_body(transport, caplog):
    _, _, state = transport
    state["result"] = SimpleNamespace(isError=False, structuredContent=None,
        content=[SimpleNamespace(text='{"message_id": "<sent@example.com>"}')])
    traffic = TrafficRecorder()
    asyncio.run(email_service.McpEmailSender("http://mcp.test/mcp", None, traffic).send_invite("a@x.com", "ABC123", EXPIRES))
    assert traffic.pending()
    assert "ABC123" not in str(traffic.pending()) + caplog.text


def test_cancellation_propagates(transport):
    _, _, state = transport
    state["error"] = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(email_service.McpEmailSender("http://mcp.test/mcp", None).send_invite("a@x.com", "ABC123", EXPIRES))
