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
