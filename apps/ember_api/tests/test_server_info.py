from __future__ import annotations

import json
import uuid

import httpx
from fastapi.testclient import TestClient

from tests.conftest import FakeEmailSender, FakeUpstream
from tests.test_admin import login, make_member, role_by_name
from tests.test_registration import as_admin

COMMANDS = [{"capability": "srv", "name": "list", "description": "List apps", "tool_name": "tool_srv_listApps"}]
CAPABILITIES = [
    {"name": "server_manager", "enabled": True, "label": "Server Manager", "tools": ["tool_srv_listApps"], "resources": [],
     "has_gui": True, "load_error": None, "missing": False, "loaded": True}
]
GUI_PAGE = {"version": 1, "title": "Server", "description": "", "sections": [{"id": "list", "title": "Apps", "tool": "tool_srv_listApps"}]}
EXTENSIONS = [
    {"id": "notes", "label": "Notes", "description": "", "status": "connected", "error": None, "tools": ["notes__add"],
     "web_url": "http://127.0.0.1:5174"}
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
    if path == "/capabilities/refresh" and request.method == "POST":
        return httpx.Response(200, json=[
            *CAPABILITIES,
            {"name": "fresh", "enabled": False, "label": "Fresh", "tools": [], "resources": [], "has_gui": False,
             "load_error": None, "missing": False, "loaded": False},
        ])
    if path == "/capabilities/server_manager/gui":
        return httpx.Response(200, json=GUI_PAGE)
    if path.startswith("/capabilities/") and path.endswith("/gui"):
        return httpx.Response(404, json={"error": "Capability 'nope' has no page"})
    if path == "/capabilities/server_manager" and request.method == "PATCH":
        return httpx.Response(200, json={**CAPABILITIES[0], "enabled": json.loads(request.content)["enabled"]})
    if path == "/extensions" and request.method == "GET":
        return httpx.Response(200, json=EXTENSIONS)
    if path == "/extensions" and request.method == "POST":
        body = json.loads(request.content)
        created = {"id": "wiki", "label": body["label"], "description": body["description"], "status": "error",
                   "error": "connection refused", "tools": []}
        return httpx.Response(201, json=created)
    if path == "/extensions/notes" and request.method == "DELETE":
        return httpx.Response(204)
    if path.startswith("/extensions/") and request.method == "DELETE":
        return httpx.Response(404, json={"error": "Unknown extension 'gone'"})
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


def test_capability_page_is_passed_through(client: TestClient, upstream: FakeUpstream) -> None:
    upstream.handler = mcp_server
    as_admin(client)

    assert client.get("/api/capabilities/server_manager/gui").json() == GUI_PAGE
    missing = client.get("/api/capabilities/nope/gui")
    assert (missing.status_code, missing.json()["detail"]) == (404, "Capability 'nope' has no page")
    assert upstream.requests[0].headers["x-requester-username"] == "root"


def test_capability_page_needs_tools_use(client_factory, email: FakeEmailSender, upstream: FakeUpstream) -> None:
    upstream.handler = mcp_server
    member = client_factory()
    make_member(member, email)  # verified, so only the permission can refuse
    admin = as_admin(client_factory())
    role = role_by_name(admin, "Member")
    assert admin.delete(f"/api/admin/roles/{role['id']}/permissions/tools.use").status_code == 200
    login(member, "alice")

    refused = member.get("/api/capabilities/server_manager/gui")

    assert (refused.status_code, refused.json()["detail"]) == (403, "Missing permission: tools.use")
    assert len(upstream.requests) == 0


def test_capability_page_reports_an_unreachable_mcp_server(client: TestClient, upstream: FakeUpstream) -> None:
    as_admin(client)
    upstream.unreachable = True

    assert client.get("/api/capabilities/server_manager/gui").status_code == 502


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


def test_extensions_listed_for_chat_users_and_managed_by_admins(
    client_factory, email: FakeEmailSender, upstream: FakeUpstream
) -> None:
    upstream.handler = mcp_server
    member = client_factory()
    make_member(member, email)
    login(member, "alice")
    assert member.get("/api/extensions").json() == EXTENSIONS
    new = {"label": "Wiki", "url": "http://wiki.internal/mcp"}
    assert member.post("/api/extensions", json=new).status_code == 403
    assert member.delete("/api/extensions/notes").status_code == 403

    admin = as_admin(client_factory())
    added = admin.post("/api/extensions", json={**new, "description": "  team wiki "})
    assert added.status_code == 201, added.text
    assert (added.json()["id"], added.json()["status"]) == ("wiki", "error")
    assert json.loads(upstream.requests[-1].content) == {
        "label": "Wiki", "url": "http://wiki.internal/mcp", "description": "team wiki"
    }
    assert admin.post("/api/extensions", json={"label": "X", "url": "file:///etc/passwd"}).status_code == 422
    assert admin.delete("/api/extensions/notes").status_code == 204
    gone = admin.delete("/api/extensions/gone")
    assert (gone.status_code, gone.json()["detail"]) == (404, "Unknown extension 'gone'")
    assert admin.delete("/api/extensions/Bad-Id").status_code == 422

    root = admin.get("/api/auth/me").json()["id"]
    logged = [e["message"] for e in admin.get("/api/logs/action", params={"actor": root}).json()]
    assert logged[:2] == ["Removed extension 'notes'", "Added extension 'wiki' (http://wiki.internal/mcp)"]


def test_extension_manager_can_add_remove_and_log_without_admin_access(
    client_factory, email: FakeEmailSender, upstream: FakeUpstream
) -> None:
    upstream.handler = mcp_server
    member = client_factory()
    member_id = make_member(member, email)
    admin = as_admin(client_factory())
    role = role_by_name(admin, "Member")
    assert admin.delete(f"/api/admin/roles/{role['id']}/permissions/tools.use").status_code == 200
    assert admin.put(f"/api/admin/roles/{role['id']}/permissions/extensions.manage").status_code == 200
    login(member, "alice")
    assert member.get("/api/auth/me").json()["permissions"] == ["chat.use", "extensions.manage"]

    assert member.post("/api/extensions", json={"label": "Wiki", "url": "http://wiki.internal/mcp"}).status_code == 201
    assert member.delete("/api/extensions/notes").status_code == 204
    logged = admin.get("/api/logs/action", params={"actor": member_id}).json()
    assert [entry["message"] for entry in logged[:2]] == [
        "Removed extension 'notes'", "Added extension 'wiki' (http://wiki.internal/mcp)"
    ]
    assert member.patch("/api/capabilities/server_manager", json={"enabled": True}).status_code == 403
    assert member.get("/api/admin/accounts").status_code == 403


def test_admin_manage_without_extensions_manage_cannot_add_or_remove(
    client_factory, email: FakeEmailSender, upstream: FakeUpstream
) -> None:
    upstream.handler = mcp_server
    member = client_factory()
    make_member(member, email)
    admin = as_admin(client_factory())
    role = role_by_name(admin, "Member")
    assert admin.put(f"/api/admin/roles/{role['id']}/permissions/admin.manage").status_code == 200
    login(member, "alice")

    assert member.post("/api/extensions", json={"label": "Wiki", "url": "http://wiki.internal/mcp"}).status_code == 403
    assert member.delete("/api/extensions/notes").status_code == 403
    assert upstream.requests == []


def test_capabilities_refresh_is_admin_only_and_logged(client_factory, email: FakeEmailSender, upstream: FakeUpstream) -> None:
    upstream.handler = mcp_server
    admin = as_admin(client_factory())

    refreshed = admin.post("/api/capabilities/refresh", json={})

    assert refreshed.status_code == 200, refreshed.text
    assert [c["name"] for c in refreshed.json()] == ["server_manager", "fresh"]
    assert refreshed.json()[1]["loaded"] is False
    assert upstream.requests[-1].method == "POST" and upstream.requests[-1].url.path == "/capabilities/refresh"
    root = admin.get("/api/auth/me").json()["id"]
    messages = [entry["message"] for entry in admin.get("/api/logs/action", params={"actor": root}).json()]
    assert "Refreshed capabilities" in messages

    member = client_factory()
    make_member(member, email)
    login(member, "alice")
    assert member.post("/api/capabilities/refresh", json={}).status_code == 403


def test_capability_status_carries_the_load_error(client_factory, upstream: FakeUpstream) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/capabilities":
            return httpx.Response(200, json=[{**CAPABILITIES[0], "enabled": False, "load_error": "boom", "loaded": False}])
        return mcp_server(request)

    upstream.handler = handler
    admin = as_admin(client_factory())

    entry = admin.get("/api/capabilities").json()[0]

    assert (entry["load_error"], entry["loaded"], entry["missing"]) == ("boom", False, False)


def test_load_error_is_shown_only_to_admins(client_factory, email: FakeEmailSender, upstream: FakeUpstream) -> None:
    broken = {**CAPABILITIES[0], "enabled": False, "load_error": "boom", "loaded": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/capabilities":
            return httpx.Response(200, json=[broken])
        return mcp_server(request)

    upstream.handler = handler
    admin = as_admin(client_factory())
    member = client_factory()
    make_member(member, email)
    login(member, "alice")

    admin_entry = admin.get("/api/capabilities").json()[0]
    member_entry = member.get("/api/capabilities").json()[0]

    assert admin_entry["load_error"] == "boom"
    assert member_entry["load_error"] is None
    assert {k: v for k, v in admin_entry.items() if k != "load_error"} == {k: v for k, v in member_entry.items() if k != "load_error"}
