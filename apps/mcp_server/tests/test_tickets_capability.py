"""The tickets capability through its real MCP tools."""

from __future__ import annotations

import asyncio

import pytest
from mcp.server.fastmcp import FastMCP

from src import commands
from src.services import capability_meta, capability_registry, identity_context, tickets
from src.services.capability_loader import CapabilityLoader
from src.services.ticket_config import load_ticket_config
from src.services.ticket_store import TicketStore
from src.services.tickets import TicketService


@pytest.fixture
def capability(tmp_path, monkeypatch):
    import src.server

    server = FastMCP("tickets-test")
    monkeypatch.setattr(src.server, "mcp", server)
    monkeypatch.setattr(capability_registry, "_REGISTRY", {})
    monkeypatch.setattr(capability_meta, "_BY_FOLDER", {})
    monkeypatch.setattr(commands, "_COMMANDS", {})
    config = tmp_path / "capabilities.json"
    config.write_text("{}")
    loader = CapabilityLoader(server, "src.capabilities", config)
    loader.scan()
    asyncio.run(loader.set_online("ticket", True))  # the capability id; if the loader wants the folder name here, use "tickets"
    service = TicketService(TicketStore(tmp_path / "t.db"), load_ticket_config(tmp_path / "none.json"))
    monkeypatch.setattr(tickets, "_service", service)
    monkeypatch.setattr(identity_context, "current_username", lambda: "alice")
    monkeypatch.setattr(identity_context, "current_uid", lambda: "uid-alice")
    return server


def call(server, name, args):
    return asyncio.run(server.call_tool(name, args))[1]


def test_create_list_show_and_reply(capability):
    created = call(capability, "tool_ticket_createTicket", {
        "type": "bug", "title": "Email fails", "description": "SMTP is not configured",
        "tags": ["email", "config"], "source": "ai_user_request", "chat_id": "c1", "agent": "ember",
    })
    assert created["id"] == 1 and created["duplicate"] is False and "Ticket 1" in created["message"]

    listed = call(capability, "tool_ticket_listMyTickets", {})
    assert listed["count"] == 1 and "[1]" in listed["message"] and "Email fails" in listed["message"]

    shown = call(capability, "tool_ticket_getTicket", {"ticket_id": 1})
    assert "SMTP is not configured" in shown["message"]
    assert "BEGIN REMOTE OUTPUT" in shown["message"]  # user text is fenced as data

    replied = call(capability, "tool_ticket_addComment", {"ticket_id": 1, "body": "Admin asked for the log"})
    assert "Admin asked for the log" in replied["message"]


def test_slash_form_defaults_to_the_user_source(capability):
    call(capability, "tool_ticket_createTicket", {"type": "feature", "title": "Dark mode", "description": "Please"})
    ticket = asyncio.run(tickets.get_service().get_ticket(1))
    assert ticket["source"] == "user"


def test_auto_duplicate_is_reported_not_refiled(capability):
    args = {"type": "bug", "title": "Tool failed", "description": "boom", "source": "ai_auto",
            "tool_name": "tool_x", "error_text": "boom 1"}
    first = call(capability, "tool_ticket_createTicket", args)
    again = call(capability, "tool_ticket_createTicket", {**args, "error_text": "boom 2"})

    assert again["duplicate"] is True and again["id"] == first["id"]
    assert "already" in again["message"]


def test_tools_refuse_without_an_identity_and_unknown_tickets(capability, monkeypatch):
    missing = call(capability, "tool_ticket_getTicket", {"ticket_id": 99})
    assert "No ticket 99" in missing["message"]

    monkeypatch.setattr(identity_context, "current_uid", lambda: "")
    refused = call(capability, "tool_ticket_createTicket", {"type": "bug", "title": "t", "description": "d"})
    assert refused["id"] == 0 and "signed-in" in refused["message"]


def test_validation_errors_come_back_as_messages(capability):
    result = call(capability, "tool_ticket_createTicket", {"type": "bug", "title": "x" * 200, "description": "d"})
    assert result["id"] == 0 and "title" in result["message"]


def test_ticket_tags_declare_picker_metadata(capability):
    tool = next(tool for tool in asyncio.run(capability.list_tools()) if tool.name == "tool_ticket_createTicket")
    tags = tool.inputSchema["properties"]["tags"]
    assert tags["input"] == "tags"
    assert tags["options_url"] == "/tickets/tags"
    assert tags["maxItems"] == 5


def test_a_renamed_account_keeps_its_tickets_and_a_name_reuser_sees_none(capability, monkeypatch):
    call(capability, "tool_ticket_createTicket", {"type": "bug", "title": "Email fails", "description": "d"})

    monkeypatch.setattr(identity_context, "current_username", lambda: "alice-renamed")
    assert call(capability, "tool_ticket_listMyTickets", {})["count"] == 1

    monkeypatch.setattr(identity_context, "current_username", lambda: "alice")
    monkeypatch.setattr(identity_context, "current_uid", lambda: "uid-someone-else")
    assert call(capability, "tool_ticket_listMyTickets", {})["count"] == 0
    assert "No ticket 1" in call(capability, "tool_ticket_getTicket", {"ticket_id": 1})["message"]


def test_tools_refuse_when_the_server_is_exposed_without_a_token(capability, monkeypatch):
    import dataclasses
    import sys

    domain = sys.modules["src.capabilities.tickets.domain"]
    monkeypatch.setattr(domain, "settings", dataclasses.replace(domain.settings, host="0.0.0.0", internal_api_token=""))

    refused = call(capability, "tool_ticket_createTicket", {"type": "bug", "title": "t", "description": "d"})

    assert refused["id"] == 0 and "INTERNAL_API_TOKEN" in refused["message"]
