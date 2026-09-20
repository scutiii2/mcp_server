"""Tests for GET /commands/help/{capability} - same Starlette TestClient
pattern as test_command_routes.py."""

from __future__ import annotations

import json

import pytest
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.testclient import TestClient

from src import capability_help
from src.help_routes import install_help_routes
from src.services import capability_meta, capability_registry


@pytest.fixture
def client():
    app = Starlette()
    install_help_routes(app)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _isolated_registries(monkeypatch):
    monkeypatch.setattr(capability_meta, "_BY_FOLDER", {})
    monkeypatch.setattr(capability_registry, "_REGISTRY", {})


@pytest.fixture
def widget_capability(tmp_path, monkeypatch):
    capability_meta.register(folder="widgets", id="widget", label="Widgets")
    fake_mcp = FastMCP(name="test")
    with capability_registry.capturing(fake_mcp, "widget", label="Widgets"):
        pass  # no real tools needed - this test only exercises the help endpoint

    folder = tmp_path / "widgets"
    folder.mkdir()
    data = {
        "summary": "Makes widgets.",
        "tools": [
            {
                "name": "make_widget_tool",
                "purpose": "Make one.",
                "connection": "SSH",
                "commands": ["make"],
            }
        ],
        "commands": [{"name": "make", "tool": "make_widget_tool", "params": []}],
        "workflow": [],
    }
    (folder / "help.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(capability_help, "_CAPABILITIES_DIR", tmp_path)


def test_get_help_index_lists_the_registered_capability(client, widget_capability):
    response = client.get("/commands/help")

    assert response.status_code == 200
    body = response.json()
    row = next(r for r in body["capabilities"] if r["capability"] == "/widget")
    assert row["label"] == "Widgets"
    assert "make" in row["commands"].split(", ")
    assert "help" in row["commands"].split(", ")


def test_get_help_index_omits_a_disabled_capability(client, widget_capability):
    fake_mcp = FastMCP(name="test-disable-index")
    capability_registry.set_enabled(fake_mcp, "widget", False)

    response = client.get("/commands/help")

    assert response.status_code == 200
    assert response.json()["capabilities"] == []


def test_get_help_returns_every_table_by_default(client, widget_capability):
    response = client.get("/commands/help/widget")

    assert response.status_code == 200
    body = response.json()
    assert body["tools"][0]["tool"] == "make_widget_tool"
    assert body["commands"][0]["slash_command"] == "/widget make"


def test_get_help_target_filters_to_one_table(client, widget_capability):
    response = client.get("/commands/help/widget?target=tools")

    body = response.json()
    assert "tools" in body
    assert "commands" not in body


def test_get_help_command_param_returns_just_that_command(client, widget_capability):
    response = client.get("/commands/help/widget?command=make")

    body = response.json()
    assert body["commands"][0]["slash_command"] == "/widget make"


def test_get_help_unknown_target_is_a_400(client, widget_capability):
    response = client.get("/commands/help/widget?target=bogus")

    assert response.status_code == 400
    assert "target" in response.json()["error"]


def test_get_help_unknown_command_is_a_400(client, widget_capability):
    response = client.get("/commands/help/widget?command=bogus")

    assert response.status_code == 400
    assert "bogus" in response.json()["error"]


def test_get_help_unregistered_capability_is_a_404(client):
    response = client.get("/commands/help/nope")

    assert response.status_code == 404


def test_get_help_disabled_capability_is_a_404(client, widget_capability):
    fake_mcp = FastMCP(name="test-disable")
    capability_registry.set_enabled(fake_mcp, "widget", False)

    response = client.get("/commands/help/widget")

    assert response.status_code == 404
