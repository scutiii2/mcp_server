"""Tests for GET /capabilities and PATCH /capabilities/{name}.

Same Starlette TestClient pattern as test_extension_routes.py. Each test
builds its own real FastMCP instance and registers one or two fake
capabilities onto it via capability_registry.capturing(), then
monkeypatches capability_routes.mcp to point at that instance instead of
the real src.server.mcp - the same reasoning test_approval_routes.py's
`db` fixture gives for swapping in a throwaway settings object.
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

from src import config  # noqa: E402
from src.capability_routes import install_capability_routes  # noqa: E402
from src.infra import capability_registry  # noqa: E402


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
    patched_settings = replace(config.settings, configs_dir=config_path.parent)
    monkeypatch.setattr("src.capability_routes.mcp", test_mcp)
    monkeypatch.setattr("src.capability_routes.settings", patched_settings)

    app = Starlette()
    install_capability_routes(app)
    with TestClient(app) as test_client:
        yield test_client


def test_get_lists_every_registered_capability(client):
    response = client.get("/capabilities")

    assert response.status_code == 200
    assert response.json() == [
        {"name": "gadgets", "enabled": True, "title": "gadgets", "command_id": "gadgets"},
        {"name": "widgets", "enabled": True, "title": "widgets", "command_id": "widgets"},
    ]


def test_patch_disables_a_capability(client, test_mcp):
    response = client.patch("/capabilities/widgets", json={"enabled": False})

    assert response.status_code == 200
    assert response.json() == {"name": "widgets", "enabled": False, "title": "widgets", "command_id": "widgets"}
    assert "make_widget" not in {t.name for t in test_mcp._tool_manager.list_tools()}
    # The sibling capability is untouched.
    assert "make_gadget" in {t.name for t in test_mcp._tool_manager.list_tools()}


def test_patch_re_enables_a_capability(client, test_mcp):
    client.patch("/capabilities/widgets", json={"enabled": False})

    response = client.patch("/capabilities/widgets", json={"enabled": True})

    assert response.status_code == 200
    assert response.json() == {"name": "widgets", "enabled": True, "title": "widgets", "command_id": "widgets"}
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
