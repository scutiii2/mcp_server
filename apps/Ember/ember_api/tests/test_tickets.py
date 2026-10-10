"""Ticket routes and gateway: ember_api only proxies to mcp_server and decides who may call what."""

from __future__ import annotations

import asyncio
import json
import re

import httpx
import pytest

from src.models import Account
from src.services.mcp_server_info import McpServerInfo
from src.services.ticket_gateway import TicketGateway
from tests.conftest import FakeUpstream
from tests.test_admin import login, make_member, role_by_name
from tests.test_permission_split import limited_account
from tests.test_registration import as_admin

TICKET = {
    "id": 7, "group_id": 3, "type": "bug", "title": "Email fails", "description": "It does not send",
    "status": "open", "priority": "normal", "effective_priority": "normal", "assignee": None, "reporter": "alice",
    "source": "user", "tags": ["email"], "context": {}, "possible_group_id": None,
    "created_at": "2026-10-10T10:00:00+00:00", "updated_at": "2026-10-10T10:00:00+00:00", "closed_at": None,
}
GROUP = {"id": 3, "title": "Email fails", "priority": "normal", "priority_pinned": False, "ticket_count": 1,
         "recent_count": 1, "open_count": 1, "tags": ["email"]}


def body_of(request: httpx.Request):
    return json.loads(request.content) if request.content else None


def tickets_server(request: httpx.Request) -> httpx.Response:
    """mcp_server's ticket routes with canned answers; tests read upstream.requests."""
    path, method = request.url.path, request.method
    if path == "/tickets" and method == "POST":
        title = body_of(request)["title"]
        if title == "bad":
            return httpx.Response(400, json={"error": "The title is not acceptable."})
        if title == "dup":
            return httpx.Response(200, json={"ticket": TICKET, "duplicate": True, "group_size": 1})
        return httpx.Response(201, json={"ticket": TICKET, "duplicate": False, "group_size": 1})
    if path == "/tickets" and method == "GET":
        return httpx.Response(200, json={"tickets": [TICKET]})
    if path == "/ticket-admin/tickets" and method == "GET":
        return httpx.Response(200, json={"tickets": [TICKET]})
    if path == "/ticket-admin/groups" and method == "GET":
        return httpx.Response(200, json={"groups": [GROUP]})
    if path == "/ticket-admin/stats":
        return httpx.Response(200, json={"open": 1, "urgent": 0, "groups": 1})
    match = re.fullmatch(r"/(ticket-admin/)?tickets/(\d+)(?:/(comments|close|move))?", path)
    if match:
        ticket_id, action = int(match.group(2)), match.group(3)
        if ticket_id == 404:
            return httpx.Response(404, json={"error": "No ticket 404."})
        return httpx.Response(200, json={"ticket": {**TICKET, "id": ticket_id, "comments": []}})
    match = re.fullmatch(r"/ticket-admin/groups/(\d+)", path)
    if match and method == "PATCH":
        return httpx.Response(200, json={"group": {**GROUP, **body_of(request)}})
    return httpx.Response(404, json={"error": "no route"})


def test_gateway_drops_empty_filters_and_flags_possible(upstream: FakeUpstream) -> None:
    upstream.handler = tickets_server
    account = Account(id=1, username="root", email="root@example.com")
    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    gateway = TicketGateway(McpServerInfo(client, "http://mcp-server.internal/mcp", "tok", None))

    result = asyncio.run(gateway.list_all(account, {"status": "open", "tag": None, "possible": True, "group_id": 3}))

    assert result == {"tickets": [TICKET]}
    request = upstream.requests[-1]
    assert dict(request.url.params) == {"status": "open", "possible": "1", "group_id": "3"}
    assert request.headers["x-requester-username"] == "root"
    assert request.headers["x-internal-token"] == "tok"


# ---- reporter routes -------------------------------------------------------

def member_client(client_factory, email, upstream):
    upstream.handler = tickets_server
    member = client_factory()
    member_id = make_member(member, email)
    login(member, "alice")
    return member, member_id


def test_member_files_and_follows_own_tickets(client_factory, email, upstream) -> None:
    member, member_id = member_client(client_factory, email, upstream)

    created = member.post("/api/tickets", json={"type": "bug", "title": "Email fails", "description": "It does not send"})
    assert created.status_code == 201, created.text
    assert created.json() == {"ticket": TICKET, "duplicate": False, "group_size": 1}
    sent = upstream.requests[-1]
    assert (sent.method, sent.url.path) == ("POST", "/tickets")
    assert sent.headers["x-requester-username"] == "alice"
    assert body_of(sent) == {
        "type": "bug", "title": "Email fails", "description": "It does not send", "source": "user",
        "verified_context": {"via": "ember_api", "account_id": str(member_id)},
    }

    assert member.get("/api/tickets", params={"status": "open"}).json() == {"tickets": [TICKET]}
    assert dict(upstream.requests[-1].url.params) == {"status": "open"}
    assert member.get("/api/tickets/7").json()["ticket"]["id"] == 7
    assert member.post("/api/tickets/7/comments", json={"body": "log attached"}).status_code == 200
    assert body_of(upstream.requests[-1]) == {"body": "log attached"}
    assert member.post("/api/tickets/7/close", json={}).status_code == 200
    assert upstream.requests[-1].url.path == "/tickets/7/close"


def test_a_repeated_report_answers_200(client_factory, email, upstream) -> None:
    member, _ = member_client(client_factory, email, upstream)

    response = member.post("/api/tickets", json={"type": "bug", "title": "dup", "description": "again"})

    assert response.status_code == 200 and response.json()["duplicate"] is True


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "bug", "title": "t", "description": "d", "reporter": "mallory"},
        {"type": "bug", "title": "t", "description": "d", "tags": ["email"]},
        {"type": "bug", "title": "t", "description": "d", "source": "ai_auto"},
        {"type": "complaint", "title": "t", "description": "d"},
        {"type": "bug", "title": "", "description": "d"},
        {"type": "bug", "title": "x" * 121, "description": "d"},
        {"type": "bug", "title": "t", "description": "x" * 4001},
        {"type": "bug", "title": "t"},
    ],
)
def test_invalid_reports_never_reach_mcp_server(client_factory, email, upstream, payload) -> None:
    member, _ = member_client(client_factory, email, upstream)

    assert member.post("/api/tickets", json=payload).status_code == 422
    assert len(upstream.requests) == 0


def test_comment_and_id_validation(client_factory, email, upstream) -> None:
    member, _ = member_client(client_factory, email, upstream)

    assert member.post("/api/tickets/7/comments", json={"body": ""}).status_code == 422
    assert member.post("/api/tickets/7/comments", json={"body": "x" * 2001}).status_code == 422
    assert member.post("/api/tickets/7/comments", json={"body": "hi", "role": "staff"}).status_code == 422
    assert member.get("/api/tickets/abc").status_code == 422
    assert member.get("/api/tickets/0").status_code == 422
    assert member.get("/api/tickets", params={"status": "done"}).status_code == 422
    assert len(upstream.requests) == 0


def test_ticket_routes_need_tickets_create(client_factory, email, upstream) -> None:
    upstream.handler = tickets_server
    member = client_factory()
    make_member(member, email)
    admin = as_admin(client_factory())
    role = role_by_name(admin, "Member")
    assert admin.delete(f"/api/admin/roles/{role['id']}/permissions/tickets.create").status_code == 200
    login(member, "alice")

    refused = member.get("/api/tickets")

    assert (refused.status_code, refused.json()["detail"]) == (403, "Missing permission: tickets.create")
    assert member.post("/api/tickets", json={"type": "bug", "title": "t", "description": "d"}).status_code == 403
    assert len(upstream.requests) == 0


def test_logged_out_visitors_get_401(client, upstream) -> None:
    upstream.handler = tickets_server
    assert client.get("/api/tickets").status_code == 401
    assert client.post("/api/tickets", json={"type": "bug", "title": "t", "description": "d"}).status_code == 401
    assert len(upstream.requests) == 0


def test_mcp_server_answers_map_to_http_errors(client_factory, email, upstream) -> None:
    member, _ = member_client(client_factory, email, upstream)

    refused = member.post("/api/tickets", json={"type": "bug", "title": "bad", "description": "d"})
    assert (refused.status_code, refused.json()["detail"]) == (400, "The title is not acceptable.")
    missing = member.get("/api/tickets/404")
    assert (missing.status_code, missing.json()["detail"]) == (404, "No ticket 404.")

    upstream.unreachable = True
    down = member.get("/api/tickets")
    assert (down.status_code, down.json()["detail"]) == (502, "mcp_server is unreachable")
