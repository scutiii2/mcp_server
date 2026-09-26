from __future__ import annotations

import json
import uuid

import httpx
from fastapi.testclient import TestClient

from tests.conftest import FakeEmailSender, FakeUpstream
from tests.test_admin import login, make_member
from tests.test_registration import as_admin

COMMANDS = [{"capability": "srv", "name": "list", "description": "List apps", "tool_name": "tool_srv_listApps"}]
CAPABILITIES = [
    {"name": "server_manager", "enabled": True, "label": "Server Manager", "tools": ["tool_srv_listApps"], "resources": []}
]


def mcp_server(request: httpx.Request) -> httpx.Response:
    """mcp_server's plain HTTP routes, as FakeUpstream's handler."""
    path = request.url.path
    if path == "/commands":
        return httpx.Response(200, json=COMMANDS)
    if path == "/commands/help":
        return httpx.Response(200, json={"capabilities": ["srv"]})
    if path == "/commands/help/srv":
        return httpx.Response(200, json={"capability": "srv", **dict(request.url.params)})
    if path.startswith("/commands/help/"):
        return httpx.Response(404, json={"error": "Unknown capability 'nope'"})
    if path == "/capabilities":
        return httpx.Response(200, json=CAPABILITIES)
    if path == "/capabilities/server_manager" and request.method == "PATCH":
        return httpx.Response(200, json={**CAPABILITIES[0], "enabled": json.loads(request.content)["enabled"]})
    return httpx.Response(404, json={"error": "no route"})


def test_commands_and_help_are_passed_through(client: TestClient, upstream: FakeUpstream) -> None:
    upstream.handler = mcp_server
    as_admin(client)

    assert client.get("/api/commands").json() == COMMANDS
    assert client.get("/api/commands/help").json() == {"capabilities": ["srv"]}
    assert client.get("/api/commands/help/srv", params={"target": "tools", "command": "list"}).json() == {
        "capability": "srv",
        "target": "tools",
        "command": "list",
    }
    missing = client.get("/api/commands/help/nope")
    assert (missing.status_code, missing.json()["detail"]) == (404, "Unknown capability 'nope'")
    assert client.get("/api/commands/help/srv", params={"target": "everything"}).status_code == 422

    sent = upstream.requests[0]
    assert str(sent.url) == "http://mcp-server.internal/commands"
    assert sent.headers["x-requester-username"] == "root"


def test_capabilities_list_and_admin_switch(client_factory, email: FakeEmailSender, upstream: FakeUpstream) -> None:
    upstream.handler = mcp_server
    admin = as_admin(client_factory())

    assert admin.get("/api/capabilities").json() == CAPABILITIES
    switched = admin.patch("/api/capabilities/server_manager", json={"enabled": False})
    assert switched.status_code == 200, switched.text
    assert switched.json()["enabled"] is False
    assert json.loads(upstream.requests[-1].content) == {"enabled": False}

    member = client_factory()
    make_member(member, email)
    login(member, "alice")
    assert member.get("/api/capabilities").status_code == 200  # tools.use
    assert member.patch("/api/capabilities/server_manager", json={"enabled": True}).status_code == 403


def test_server_info_needs_tools_use_and_handles_outages(client: TestClient, upstream: FakeUpstream) -> None:
    assert client.get("/api/commands").status_code == 401
    as_admin(client)
    upstream.unreachable = True

    response = client.get("/api/capabilities")

    assert response.status_code == 502
    assert client.get("/api/commands/help/bad name").status_code == 422  # never forwarded


def test_command_results_are_appended_to_a_chat(client: TestClient) -> None:
    as_admin(client)
    chat_id = str(uuid.uuid4())
    call = {"role": "user", "kind": "command", "content": "/srv list"}
    result = {"role": "assistant", "kind": "command", "content": "**Apps** (0)"}

    created = client.post(f"/api/chats/{chat_id}/messages", json={"title": "/srv list", "messages": [call, result]})
    again = client.post(f"/api/chats/{chat_id}/messages", json={"title": "ignored", "messages": [call]})

    assert created.status_code == 200 and created.json()["title"] == "/srv list"
    assert again.json()["message_count"] == 3
    assert client.get(f"/api/chats/{chat_id}").json()["messages"][:2] == [call, result]
    bad = client.post(f"/api/chats/{chat_id}/messages", json={"title": "x", "messages": []})
    assert bad.status_code == 422
