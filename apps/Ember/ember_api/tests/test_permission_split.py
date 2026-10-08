"""Independent responsibilities and delegation boundaries for Ember RBAC."""

import pytest

from tests.test_admin import login, make_member, role_by_name
from tests.test_registration import as_admin


def limited_account(client, email, *permissions):
    account_id = make_member(client, email)
    as_admin(client)
    role = client.post("/api/admin/roles", json={"name": "Limited"}).json()
    for permission in permissions:
        response = client.put(f"/api/admin/roles/{role['id']}/permissions/{permission}")
        assert response.status_code == 200, response.text
    assert client.put(f"/api/admin/accounts/{account_id}/roles/{role['id']}").status_code == 200
    member = role_by_name(client, "Member")
    assert client.delete(f"/api/admin/accounts/{account_id}/roles/{member['id']}").status_code == 200
    client.post("/api/auth/logout", json={})
    login(client, "alice")
    return account_id, role["id"]


@pytest.mark.parametrize("permission,allowed,denied", [
    ("accounts.view", "/api/admin/accounts", "/api/admin/roles"),
    ("roles.view", "/api/admin/roles", "/api/admin/accounts"),
    ("invites.manage", "/api/admin/invites", "/api/admin/accounts"),
    ("usage.all.view", "/api/admin/usage", "/api/admin/accounts"),
])
def test_read_responsibilities_are_independent(client, email, permission, allowed, denied):
    limited_account(client, email, permission)
    assert client.get(allowed).status_code == 200
    assert client.get(denied).status_code == 403


def test_accounts_view_does_not_allow_mutations(client, email):
    account_id, _ = limited_account(client, email, "accounts.view")
    assert client.patch(f"/api/admin/accounts/{account_id}", json={"username": "changed"}).status_code == 403
    assert client.delete(f"/api/admin/accounts/{account_id}").status_code == 403


def test_overview_does_not_disclose_unrelated_counts(client, email):
    limited_account(client, email, "roles.view")
    summary = client.get("/api/admin/summary")
    assert summary.status_code == 200
    assert summary.json()["roles"] is not None
    assert all(summary.json()[name] is None for name in ("accounts", "unverified", "disabled", "open_invites"))


def test_role_assignment_cannot_grant_stronger_role(client, email):
    as_admin(client)
    administrator = role_by_name(client, "Administrator")["id"]
    account_id, _ = limited_account(client, email, "roles.assign")
    assert client.put(f"/api/admin/accounts/{account_id}/roles/{administrator}").status_code == 403


def test_role_manager_cannot_grant_permission_they_lack(client, email):
    _, role_id = limited_account(client, email, "roles.manage")
    assert client.put(f"/api/admin/roles/{role_id}/permissions/accounts.delete").status_code == 403
    assert client.delete(f"/api/admin/roles/{role_id}/permissions/roles.manage").status_code == 409


def test_inviter_cannot_delegate_stronger_default_role(client, email):
    limited_account(client, email, "invites.manage")
    assert client.post("/api/admin/invites", json={}).status_code == 403


def test_tool_view_allows_discovery_but_refuses_calls_and_batches(client, email, upstream):
    limited_account(client, email, "tools.view")
    assert client.post("/api/mcp/server", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code == 200
    seen = len(upstream.requests)
    call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "anything"}}
    assert client.post("/api/mcp/server", json=call).status_code == 403
    assert client.post("/api/mcp/server", json=[{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, call]).status_code == 403
    assert len(upstream.requests) == seen


def test_chat_alone_cannot_share_connect_servers_or_upload(client, email):
    limited_account(client, email, "chat.use")
    assert client.post("/api/chats/chat-1234/shares", json={}).status_code == 403
    assert client.post("/api/user-extensions", json={"label": "Notes", "url": "https://example.com/mcp"}).status_code == 403
    assert client.patch("/api/user-extensions/notes", json={"enabled": False}).status_code == 403
    assert client.delete("/api/user-extensions/notes").status_code == 403
    assert client.post("/api/attachments/text", json={"filename": "a.txt", "data": "eA=="}).status_code == 403
    assert client.post("/api/uploads", json={"filename": "a.txt", "data": "eA=="}).status_code == 403
    assert client.get("/api/server/download", params={"path": "/tmp/result.txt"}).status_code == 403


def test_upload_permission_does_not_require_tool_execution(client, email):
    limited_account(client, email, "files.upload")
    assert client.post("/api/attachments/text", json={"filename": "a.txt", "data": "eA=="}).status_code == 200
    assert client.post("/api/mcp/server", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "anything"}}).status_code == 403


def test_chat_without_execution_blocks_every_agent_tool(client, email, agent):
    limited_account(client, email, "chat.use")
    response = client.post("/api/chats/chat-1234/turns", json={"question": "hello", "allowed_tools": ["tool_pdf_merge"]})
    assert response.status_code == 202, response.text
    client.get("/api/chats/chat-1234/events")
    assert agent.asks[-1]["disabled_tools"] == ["*"]


def test_gateway_refuses_older_agent_before_asking():
    import asyncio
    from unittest.mock import AsyncMock

    from src.services.agent_gateway import AgentCallError, Caller, McpAgentGateway

    gateway = McpAgentGateway(None)
    gateway._call = AsyncMock(return_value={"tool_filter": True})
    with pytest.raises(AgentCallError):
        asyncio.run(gateway.ask(
            "http://unused/mcp", Caller(username="alice", email="a@example.com"),
            question="hello", history=[], request_id="turn", caveman=False,
            enabled_extensions=[], on_event=None, disabled_tools=["*"],
        ))
    assert gateway._call.await_count == 1
    assert gateway._call.call_args.args[2] == "status"
