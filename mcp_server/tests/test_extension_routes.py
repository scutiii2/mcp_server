"""Tests for GET /extensions.

The property that matters here is the JSON shape: another agent is
building chat_app's sidebar against this contract concurrently, so a
field renamed or a status value spelled differently breaks that work
silently. Same Starlette TestClient pattern as test_approval_routes.py.
"""

from __future__ import annotations

import warnings

import pytest
from starlette.applications import Starlette

warnings.filterwarnings("ignore", category=DeprecationWarning)
from starlette.testclient import TestClient  # noqa: E402

from mcp_server.extension_routes import install_extension_routes  # noqa: E402
from mcp_server.infra import extensions  # noqa: E402


@pytest.fixture
def client():
    app = Starlette()
    install_extension_routes(app)
    with TestClient(app) as test_client:
        yield test_client


def test_a_connected_extension_reports_its_tools(client, monkeypatch):
    monkeypatch.setattr(
        extensions,
        "current_statuses",
        lambda: [
            extensions.ExtensionStatus(
                id="reference",
                label="Reference Extension (dev fixture)",
                description="Two trivial tools used to prove the mechanism works.",
                status="connected",
                error=None,
                tools=["reference__echo", "reference__add"],
            )
        ],
    )

    response = client.get("/extensions")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "reference",
            "label": "Reference Extension (dev fixture)",
            "description": "Two trivial tools used to prove the mechanism works.",
            "status": "connected",
            "error": None,
            "tools": ["reference__echo", "reference__add"],
        }
    ]


def test_an_errored_extension_reports_a_message_and_no_tools(client, monkeypatch):
    monkeypatch.setattr(
        extensions,
        "current_statuses",
        lambda: [
            extensions.ExtensionStatus(
                id="broken",
                label="Broken Extension",
                description="Deliberately misconfigured.",
                status="error",
                error="No such file or directory: 'nonexistent-command'",
                tools=[],
            )
        ],
    )

    response = client.get("/extensions")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["status"] == "error"
    assert body[0]["tools"] == []
    assert "nonexistent-command" in body[0]["error"]


def test_multiple_extensions_all_appear(client, monkeypatch):
    monkeypatch.setattr(
        extensions,
        "current_statuses",
        lambda: [
            extensions.ExtensionStatus(
                id="a", label="A", description="", status="connected", error=None, tools=["a__x"]
            ),
            extensions.ExtensionStatus(
                id="b", label="B", description="", status="error", error="boom", tools=[]
            ),
        ],
    )

    response = client.get("/extensions")

    assert [item["id"] for item in response.json()] == ["a", "b"]


def test_nothing_configured_is_an_empty_list_not_an_error(client, monkeypatch):
    monkeypatch.setattr(extensions, "current_statuses", lambda: [])

    response = client.get("/extensions")

    assert response.status_code == 200
    assert response.json() == []


# --- POST /extensions -----------------------------------------------------
# Runtime add: connects (or records a connect failure - still a 201, same
# as a broken config.json entry today) and persists to config.json, all
# through extensions.add_extension - mocked here so these tests are about
# the route's own validation and id-generation, not the registry.


def test_post_creates_an_http_extension(client, monkeypatch):
    captured = {}

    async def fake_add_extension(config, config_path):
        captured["config"] = config
        return extensions.ExtensionStatus(
            id=config.id,
            label=config.label,
            description=config.description,
            status="connected",
            error=None,
            tools=[f"{config.id}__echo"],
        )

    monkeypatch.setattr(extensions, "current_statuses", lambda: [])
    monkeypatch.setattr(extensions, "add_extension", fake_add_extension)

    response = client.post(
        "/extensions",
        json={"label": "My Extension", "url": "http://127.0.0.1:9000/mcp", "description": "desc"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body == {
        "id": "my_extension",
        "label": "My Extension",
        "description": "desc",
        "status": "connected",
        "error": None,
        "tools": ["my_extension__echo"],
    }
    assert captured["config"].transport == "http"
    assert captured["config"].url == "http://127.0.0.1:9000/mcp"
    assert captured["config"].id == "my_extension"


def test_post_a_connect_failure_is_still_201(client, monkeypatch):
    """Mirrors how a broken config.json entry behaves today: it's still
    registered (and, here, persisted) - status/error in the body say it's
    unreachable, nothing about the HTTP response itself signals failure."""

    async def fake_add_extension(config, config_path):
        return extensions.ExtensionStatus(
            id=config.id,
            label=config.label,
            description=config.description,
            status="error",
            error="Connection refused",
            tools=[],
        )

    monkeypatch.setattr(extensions, "current_statuses", lambda: [])
    monkeypatch.setattr(extensions, "add_extension", fake_add_extension)

    response = client.post("/extensions", json={"label": "Unreachable", "url": "http://127.0.0.1:1/mcp"})

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "error"
    assert body["error"] == "Connection refused"


def test_post_missing_label_is_400(client, monkeypatch):
    monkeypatch.setattr(extensions, "current_statuses", lambda: [])

    response = client.post("/extensions", json={"url": "http://127.0.0.1:9000/mcp"})

    assert response.status_code == 400
    assert "label" in response.json()["error"]


def test_post_blank_label_is_400(client, monkeypatch):
    monkeypatch.setattr(extensions, "current_statuses", lambda: [])

    response = client.post("/extensions", json={"label": "   ", "url": "http://127.0.0.1:9000/mcp"})

    assert response.status_code == 400
    assert "label" in response.json()["error"]


def test_post_missing_url_is_400(client, monkeypatch):
    monkeypatch.setattr(extensions, "current_statuses", lambda: [])

    response = client.post("/extensions", json={"label": "My Extension"})

    assert response.status_code == 400
    assert "url" in response.json()["error"]


def test_post_bad_url_scheme_is_400(client, monkeypatch):
    monkeypatch.setattr(extensions, "current_statuses", lambda: [])

    response = client.post("/extensions", json={"label": "My Extension", "url": "ftp://example.com/mcp"})

    assert response.status_code == 400
    assert "http" in response.json()["error"]


def test_post_url_without_a_host_is_400(client, monkeypatch):
    monkeypatch.setattr(extensions, "current_statuses", lambda: [])

    response = client.post("/extensions", json={"label": "My Extension", "url": "http://"})

    assert response.status_code == 400


def test_post_duplicate_label_disambiguates_the_generated_id(client, monkeypatch):
    monkeypatch.setattr(
        extensions,
        "current_statuses",
        lambda: [
            extensions.ExtensionStatus(
                id="my_extension", label="My Extension", description="", status="connected", error=None, tools=[]
            )
        ],
    )

    captured = {}

    async def fake_add_extension(config, config_path):
        captured["config"] = config
        return extensions.ExtensionStatus(
            id=config.id, label=config.label, description=config.description, status="connected", error=None, tools=[]
        )

    monkeypatch.setattr(extensions, "add_extension", fake_add_extension)

    response = client.post("/extensions", json={"label": "My Extension", "url": "http://127.0.0.1:9001/mcp"})

    assert response.status_code == 201
    assert response.json()["id"] == "my_extension_2"
    assert captured["config"].id == "my_extension_2"


# --- DELETE /extensions/{extension_id} -------------------------------------


def test_delete_removes_a_known_extension(client, monkeypatch):
    async def fake_remove_extension(extension_id, config_path):
        assert extension_id == "reference"
        return True

    monkeypatch.setattr(extensions, "remove_extension", fake_remove_extension)

    response = client.delete("/extensions/reference")

    assert response.status_code == 204
    assert response.content == b""


def test_delete_unknown_id_is_404(client, monkeypatch):
    async def fake_remove_extension(extension_id, config_path):
        return False

    monkeypatch.setattr(extensions, "remove_extension", fake_remove_extension)

    response = client.delete("/extensions/nope")

    assert response.status_code == 404
    assert "nope" in response.json()["error"]
