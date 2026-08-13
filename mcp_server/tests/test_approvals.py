"""Tests for the human-approval gate.

The property under test is narrow and important: requesting an action
must not perform it, and performing it must happen at most once. Email
sending and the registry are patched; the SQLite store is real, since
"survives a restart" is the reason it exists.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from mcp_server.infra import approvals, pending_requests
from mcp_server.infra.app_config import EmailConfig


EMAIL = EmailConfig(
    smtp_server="smtp.example.com",
    smtp_port=587,
    from_address="notifications@example.com",
    password="pw",
    to=["team@example.com"],
    approver_emails=["boss@example.com"],
)


@pytest.fixture
def registry():
    """Isolate the module-level registry so tests can't leak into each other."""
    with patch.dict(approvals._REGISTRY, {}, clear=True):
        yield approvals._REGISTRY


@pytest.fixture
def ran():
    """Records whether the irreversible work actually happened."""
    return []


@pytest.fixture
def capability(registry, ran):
    approvals.register(
        approvals.GatedCapability(
            name="restart_service",
            summarize=lambda p: f"Restart {p['service']} on {p['host']}",
            execute=lambda p: ran.append(p) or f"restarted {p['service']}",
        )
    )
    return approvals.get("restart_service")


def _request(tmp_path: Path, payload=None):
    with patch("mcp_server.infra.approvals.load_email_config", return_value=EMAIL), \
         patch("mcp_server.infra.approvals.send_email") as mock_send:
        message = approvals.request_approval(
            "restart_service",
            payload or {"service": "nginx", "host": "web-1"},
            requested_by="a chat session",
            db_path=tmp_path / "pending.db",
            base_url="https://tools.example",
        )
    return message, mock_send


def _token_of(mock_send) -> str:
    body = mock_send.call_args.kwargs["body_html"]
    return body.split("/approvals/")[1].split('"')[0]


# --- requesting must not execute ---------------------------------------


def test_requesting_does_not_execute(tmp_path: Path, capability, ran):
    """The whole point. A model that decides to call this tool - including
    one talked into it by injected text - gets a pending request, not a
    restarted service."""
    _request(tmp_path)

    assert ran == []


def test_request_stores_a_pending_row_with_the_payload(tmp_path: Path, capability):
    _, mock_send = _request(tmp_path)
    record = pending_requests.get(tmp_path / "pending.db", _token_of(mock_send))

    assert record.status == "pending"
    assert record.capability == "restart_service"
    assert record.payload == {"service": "nginx", "host": "web-1"}


def test_request_emails_the_approvers_not_the_general_list(tmp_path: Path, capability):
    """approver_emails is a standing authorization list; `to` is general
    notifications. Sending approval links to the latter would hand the
    authority to everyone on it."""
    _, mock_send = _request(tmp_path)

    assert mock_send.call_args.kwargs["to"] == ["boss@example.com"]


def test_request_message_says_nothing_has_happened(tmp_path: Path, capability):
    message, _ = _request(tmp_path)

    assert "nothing has happened yet" in message.lower()
    assert "Restart nginx on web-1" in message


def test_unregistered_capability_fails_before_storing_anything(tmp_path: Path, registry):
    with pytest.raises(KeyError, match="No gated capability"):
        approvals.request_approval("not_registered", {}, db_path=tmp_path / "pending.db")


# --- approving executes, exactly once ----------------------------------


def test_approving_executes(tmp_path: Path, capability, ran):
    _, mock_send = _request(tmp_path)

    result = approvals.approve(
        _token_of(mock_send), approved_by="alice", db_path=tmp_path / "pending.db"
    )

    assert ran == [{"service": "nginx", "host": "web-1"}]
    assert result == "restarted nginx"


def test_second_approval_does_not_run_it_again(tmp_path: Path, capability, ran):
    """A double-clicked link, or a mail client that fetches twice, must not
    mean two restarts."""
    _, mock_send = _request(tmp_path)
    token = _token_of(mock_send)
    approvals.approve(token, approved_by="alice", db_path=tmp_path / "pending.db")

    with pytest.raises(LookupError, match="already handled"):
        approvals.approve(token, approved_by="alice", db_path=tmp_path / "pending.db")

    assert len(ran) == 1


def test_unknown_token_is_refused(tmp_path: Path, capability, ran):
    with pytest.raises(LookupError, match="not valid"):
        approvals.approve("made-up", approved_by="alice", db_path=tmp_path / "pending.db")

    assert ran == []


def test_expired_request_is_refused(tmp_path: Path, capability, ran):
    db = tmp_path / "pending.db"
    token = pending_requests.create(db, "restart_service", {"service": "nginx", "host": "web-1"}, ttl_hours=-1)

    with pytest.raises(LookupError, match="expired"):
        approvals.approve(token, approved_by="alice", db_path=db)

    assert ran == []


def test_approver_name_is_recorded(tmp_path: Path, capability):
    _, mock_send = _request(tmp_path)
    token = _token_of(mock_send)

    approvals.approve(token, approved_by="alice", db_path=tmp_path / "pending.db")

    assert pending_requests.get(tmp_path / "pending.db", token).approved_by == "alice"


def test_approval_uses_the_stored_payload(tmp_path: Path, capability, ran):
    """Execution takes the payload recorded at request time. Nothing the
    approver supplies reaches it, so an approval can't be edited into a
    different action on its way through."""
    _, mock_send = _request(tmp_path, payload={"service": "postgres", "host": "db-1"})

    approvals.approve(_token_of(mock_send), approved_by="alice", db_path=tmp_path / "pending.db")

    assert ran == [{"service": "postgres", "host": "db-1"}]


# --- the approval link -------------------------------------------------


def test_email_links_to_the_public_base_url(tmp_path: Path, capability):
    """A bind address is meaningless from an inbox; this has to be an
    address that resolves for the approver."""
    _, mock_send = _request(tmp_path)

    assert "https://tools.example/approvals/" in mock_send.call_args.kwargs["body_html"]


def test_summary_is_html_escaped_in_the_email(tmp_path: Path, registry, ran):
    """The summary is built from the payload, which came from the model,
    which may be repeating text it read somewhere hostile."""
    approvals.register(
        approvals.GatedCapability(
            name="restart_service",
            summarize=lambda p: f"Restart {p['service']}",
            execute=lambda p: "ok",
        )
    )
    _, mock_send = _request(tmp_path, payload={"service": "<script>alert(1)</script>"})

    body = mock_send.call_args.kwargs["body_html"]
    assert "<script>" not in body
    assert "&lt;script&gt;" in body
