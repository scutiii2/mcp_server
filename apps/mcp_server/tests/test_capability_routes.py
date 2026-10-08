"""Tests for GET /capabilities, POST /capabilities/refresh and PATCH /capabilities/{name}.

Same Starlette TestClient pattern as test_extension_routes.py. Each test
builds its own real FastMCP instance, registers one or two fake
capabilities onto it via capability_registry.capturing(), and hands the
routes a CapabilityLoader built on that instance and a temp config path.
"""

from __future__ import annotations

import json
import warnings
from dataclasses import replace
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette

warnings.filterwarnings("ignore", category=DeprecationWarning)
from starlette.testclient import TestClient  # noqa: E402

from src.capability_routes import install_capability_routes  # noqa: E402
from src.services import capability_registry  # noqa: E402
from src.services.capability_loader import CapabilityLoader  # noqa: E402


@pytest.fixture(autouse=True)
def clean_registry():
    capability_registry._REGISTRY.clear()
    yield
    capability_registry._REGISTRY.clear()


@pytest.fixture
def test_mcp():
    server = FastMCP(name="test-server")

    with capability_registry.capturing(server, "widgets"):
        @server.tool()
        def make_widget() -> str:
            return "widget"

    with capability_registry.capturing(server, "gadgets"):
        @server.tool()
        def make_gadget() -> str:
            return "gadget"

    return server


@pytest.fixture
def config_path(tmp_path: Path):
    return tmp_path / "config_capabilities.json"


@pytest.fixture
def client(test_mcp, config_path, monkeypatch):
    loader = CapabilityLoader(test_mcp, "src.capabilities", config_path)
    app = Starlette()
    install_capability_routes(app, loader)
    with TestClient(app) as test_client:
        yield test_client


def test_get_lists_every_registered_capability(client):
    response = client.get("/capabilities")

    assert response.status_code == 200
    assert response.json() == [
        {"name": "gadgets", "enabled": True, "label": "gadgets", "tools": ["make_gadget"], "resources": [], "has_gui": False,
         "load_error": None, "missing": False, "loaded": True},
        {"name": "widgets", "enabled": True, "label": "widgets", "tools": ["make_widget"], "resources": [], "has_gui": False,
         "load_error": None, "missing": False, "loaded": True},
    ]


def test_get_reports_a_registered_label(monkeypatch, client):
    monkeypatch.setitem(
        capability_registry._REGISTRY, "widgets",
        replace(capability_registry._REGISTRY["widgets"], label="Widgets"),
    )

    response = client.get("/capabilities")

    widgets = next(entry for entry in response.json() if entry["name"] == "widgets")
    assert widgets["label"] == "Widgets"


def test_patch_disables_a_capability(client, test_mcp):
    response = client.patch("/capabilities/widgets", json={"enabled": False})

    assert response.status_code == 200
    assert response.json() == {
        "name": "widgets", "enabled": False, "label": "widgets", "tools": ["make_widget"], "resources": [], "has_gui": False,
        "load_error": None, "missing": False, "loaded": True,
    }
    assert "make_widget" not in {t.name for t in test_mcp._tool_manager.list_tools()}
    # The sibling capability is untouched.
    assert "make_gadget" in {t.name for t in test_mcp._tool_manager.list_tools()}


def test_patch_re_enables_a_capability(client, test_mcp):
    client.patch("/capabilities/widgets", json={"enabled": False})

    response = client.patch("/capabilities/widgets", json={"enabled": True})

    assert response.status_code == 200
    assert response.json() == {
        "name": "widgets", "enabled": True, "label": "widgets", "tools": ["make_widget"], "resources": [], "has_gui": False,
        "load_error": None, "missing": False, "loaded": True,
    }
    assert "make_widget" in {t.name for t in test_mcp._tool_manager.list_tools()}


def test_patch_persists_to_disk(client, config_path):
    client.patch("/capabilities/widgets", json={"enabled": False})

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved == {"widgets": {"enabled": False}}


def test_patch_preserves_other_capabilities_on_disk(client, config_path):
    client.patch("/capabilities/widgets", json={"enabled": False})
    client.patch("/capabilities/gadgets", json={"enabled": False})

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved == {"widgets": {"enabled": False}, "gadgets": {"enabled": False}}


def test_patch_unknown_capability_is_404(client):
    response = client.patch("/capabilities/nonexistent", json={"enabled": False})

    assert response.status_code == 404
    assert "nonexistent" in response.json()["error"]


def test_patch_missing_enabled_field_is_400(client):
    response = client.patch("/capabilities/widgets", json={})

    assert response.status_code == 400


def test_patch_non_boolean_enabled_is_400(client):
    response = client.patch("/capabilities/widgets", json={"enabled": "yes"})

    assert response.status_code == 400


def test_patch_malformed_json_body_is_400(client):
    response = client.patch(
        "/capabilities/widgets", content=b"not json", headers={"content-type": "application/json"}
    )

    assert response.status_code == 400


def test_refresh_returns_the_capability_list(client):
    response = client.post("/capabilities/refresh")

    assert response.status_code == 200
    # The scan also finds the real folders of src.capabilities (as offline entries).
    names = [entry["name"] for entry in response.json()]
    assert {"gadgets", "widgets", "watch"} <= set(names)
    assert names == sorted(names)
    assert next(e for e in response.json() if e["name"] == "watch")["loaded"] is False


def test_patch_online_that_fails_to_load_is_409_with_the_message(test_mcp, config_path, tmp_path, monkeypatch):
    loader = CapabilityLoader(test_mcp, "src.capabilities", config_path)

    async def refuse(name, online):
        from src.services.capability_loader import CapabilityLoadError

        raise CapabilityLoadError("boom")

    monkeypatch.setattr(loader, "set_online", refuse)
    app = Starlette()
    install_capability_routes(app, loader)
    with TestClient(app) as test_client:
        response = test_client.patch("/capabilities/widgets", json={"enabled": True})

    assert response.status_code == 409
    assert response.json() == {"error": "boom"}


def test_get_lists_a_discovered_but_unloaded_capability(test_mcp, config_path):
    from src.services.capability_loader import CapabilityRecord

    loader = CapabilityLoader(test_mcp, "src.capabilities", config_path)
    capability_registry.register_unloaded("fresh", "Fresh")
    loader._records["fresh"] = CapabilityRecord("fresh", "fresh", "Fresh")
    app = Starlette()
    install_capability_routes(app, loader)
    with TestClient(app) as test_client:
        entry = next(e for e in test_client.get("/capabilities").json() if e["name"] == "fresh")

    assert entry == {"name": "fresh", "enabled": False, "label": "Fresh", "tools": [], "resources": [], "has_gui": False,
                     "load_error": None, "missing": False, "loaded": False}
