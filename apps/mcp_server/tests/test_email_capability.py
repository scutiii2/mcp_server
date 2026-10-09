from __future__ import annotations

import asyncio
import dataclasses
import json
import socket
import threading
import time
from email import message_from_string
from unittest.mock import MagicMock

import pytest
from mcp.server.fastmcp import FastMCP
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
import httpx
import uvicorn

from src import commands, capability_help
from src.config import settings
from src.services import capability_meta, capability_registry, email_delivery
from src.services.capability_loader import CapabilityLoader
from src.services.identity_context import IdentityContextMiddleware
from src.services.internal_token import InternalTokenMiddleware


@pytest.fixture
def capability(tmp_path, monkeypatch):
    import src.server
    server = FastMCP("email-test")
    monkeypatch.setattr(src.server, "mcp", server)
    monkeypatch.setattr(capability_registry, "_REGISTRY", {})
    monkeypatch.setattr(capability_meta, "_BY_FOLDER", {})
    monkeypatch.setattr(commands, "_COMMANDS", {})
    config = tmp_path / "capabilities.json"
    config.write_text('{}')
    loader = CapabilityLoader(server, "src.capabilities", config)
    loader.scan()
    asyncio.run(loader.set_online("email", True))
    (tmp_path / "config_email.json").write_text(json.dumps({"smtp_server": "smtp.example.com",
        "smtp_port": 587, "from": "sender@example.com"}))
    monkeypatch.setattr(email_delivery, "settings", dataclasses.replace(settings,
        configs_dir=tmp_path, email_audit_path=tmp_path / "audit.db"))
    smtp = MagicMock()
    smtp.return_value.__enter__.return_value.sendmail.return_value = {}
    monkeypatch.setattr("smtplib.SMTP", smtp)
    return server, loader, smtp


def call(server, name, args):
    return asyncio.run(server.call_tool(name, args))


def test_send_reply_and_help_follow_the_real_tool_contract(capability):
    server, _, smtp = capability
    args = {"to": "alice@example.com", "subject": "Update", "body_text": "Private code ABC123"}
    first = call(server, "tool_email_sendEmail", args)
    # FastMCP returns content plus structured content for typed models.
    first_id = first[1]["message_id"]
    assert first_id.startswith("<")
    reply = call(server, "tool_email_replyEmail", {**args, "in_reply_to": first_id})
    assert reply[1]["message_id"] != first_id
    raw = smtp.return_value.__enter__.return_value.sendmail.call_args.args[2]
    message = message_from_string(raw)
    assert message["In-Reply-To"] == first_id and message["References"] == first_id
    help_result = capability_help.build_help("email", target="all")
    assert {row["slash_command"] for row in help_result["commands"]} == {"/email send", "/email reply"}
    tools = asyncio.run(server.list_tools())
    assert all((tool.meta or {}).get("display_label") for tool in tools)
    send_tool = next(tool for tool in tools if tool.name == "tool_email_sendEmail")
    assert send_tool.annotations.readOnlyHint is False


def test_offline_then_reload_preserves_shared_delivery(capability):
    server, loader, _ = capability
    asyncio.run(loader.set_online("email", False))
    assert "tool_email_sendEmail" not in server._tool_manager._tools
    with pytest.raises(email_delivery.EmailUnavailable):
        email_delivery.deliver_email(["alice@example.com"], "Update", "Body")
    asyncio.run(loader.set_online("email", True))
    assert call(server, "tool_email_sendEmail", {"to": "alice@example.com", "subject": "Update", "body_text": "Body"})[1]["message_id"]


def test_invalid_reply_and_recipient_do_not_connect(capability):
    server, _, smtp = capability
    for name, args in [
        ("tool_email_replyEmail", {"to": "alice@example.com", "subject": "Update", "body_text": "Body", "in_reply_to": ""}),
        ("tool_email_sendEmail", {"to": "alice@example.com\nother@example.com", "subject": "Update", "body_text": "Body"}),
    ]:
        with pytest.raises(Exception):
            call(server, name, args)
    smtp.assert_not_called()


def test_authenticated_wire_delivery_and_audit_never_return_content(capability, caplog):
    server, _, smtp = capability
    app = server.streamable_http_app()
    app.add_middleware(IdentityContextMiddleware)
    app.add_middleware(InternalTokenMiddleware, token="test-internal-token")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    host = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=host.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}/mcp"

    async def send_and_audit():
        headers = {"X-Internal-Token": "test-internal-token", "X-Requester-Username": "ember"}
        async with streamable_http_client(url, http_client=httpx.AsyncClient(headers=headers)) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                sent = await session.call_tool("tool_email_sendEmail", {
                    "to": "alice@example.com", "subject": "Verify your Ember email",
                    "body_text": "Your verification code: PRIVATE-CODE-123", "prefix_subject": False,
                })
                audit = await session.call_tool("tool_email_getAuditLog", {})
        return sent, audit

    try:
        deadline = time.monotonic() + 10
        while not host.started:
            assert time.monotonic() < deadline
            time.sleep(0.05)
        assert httpx.post(url, json={}, headers={"Accept": "application/json, text/event-stream"}).status_code == 401
        sent, audit = asyncio.run(send_and_audit())
        assert sent.isError is False and sent.structuredContent["message_id"].startswith("<")
        assert audit.structuredContent["deliveries"][0]["owner"] == "ember"
        assert "PRIVATE-CODE-123" not in str(audit) + str(sent) + caplog.text
        raw = smtp.return_value.__enter__.return_value.sendmail.call_args.args[2]
        message = message_from_string(raw)
        assert message["Subject"] == "Verify your Ember email"
        assert "PRIVATE-CODE-123" in message.get_payload(decode=True).decode()
    finally:
        host.should_exit = True
        thread.join(timeout=5)
