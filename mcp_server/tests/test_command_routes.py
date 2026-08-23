"""Tests for GET /commands - same Starlette TestClient pattern as
test_extension_routes.py. Uses monkeypatch to swap in an isolated
registry per test, same reasoning as test_commands.py."""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from mcp_server import commands
from mcp_server.command_routes import install_command_routes


@pytest.fixture
def client():
    app = Starlette()
    install_command_routes(app)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch):
    monkeypatch.setattr(commands, "_COMMANDS", {})


def test_list_commands_returns_every_registered_command(client):
    def fn():
        ...

    fn.__module__ = "mcp_server.capabilities.otp.tool"
    commands.command(name="get_otp", description="generate otp")(fn)

    response = client.get("/commands")

    assert response.status_code == 200
    assert response.json() == [
        {"capability": "otp", "name": "get_otp", "description": "generate otp", "tool_name": "fn"}
    ]


def test_list_commands_returns_empty_list_when_none_registered(client):
    response = client.get("/commands")

    assert response.status_code == 200
    assert response.json() == []
