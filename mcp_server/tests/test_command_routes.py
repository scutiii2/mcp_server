"""Tests for GET /commands - same Starlette TestClient pattern as
test_extension_routes.py. Uses monkeypatch to swap in an isolated
registry per test, same reasoning as test_commands.py."""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from src import commands
from src.command_routes import install_command_routes
from src.infra import capability_registry


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

    fn.__module__ = "src.capabilities.otp.tool"
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


def test_list_commands_omits_a_disabled_capabilitys_commands(client, monkeypatch):
    def fn():
        ...

    fn.__module__ = "src.capabilities.otp.tool"
    commands.command(name="get_otp", description="generate otp")(fn)

    monkeypatch.setattr(capability_registry, "_REGISTRY", {})
    from mcp.server.fastmcp import FastMCP

    fake_mcp = FastMCP(name="test")
    with capability_registry.capturing(fake_mcp, "otp"):
        pass
    capability_registry.set_enabled(fake_mcp, "otp", False)

    response = client.get("/commands")

    assert response.status_code == 200
    assert response.json() == []


def test_list_commands_includes_a_command_whose_capability_the_registry_never_heard_of(client, monkeypatch):
    """Fails open: a command isn't hidden just because nothing called
    capturing() for its capability (shouldn't happen for a real
    capability, but a hidden command from a registry gap would be a
    confusing way to find out)."""
    def fn():
        ...

    fn.__module__ = "src.capabilities.otp.tool"
    commands.command(name="get_otp", description="generate otp")(fn)
    monkeypatch.setattr(capability_registry, "_REGISTRY", {})

    response = client.get("/commands")

    assert response.status_code == 200
    assert len(response.json()) == 1
