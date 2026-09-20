from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from src import registry
from src.routes import install_catalog_routes


@pytest.fixture
def client():
    app = Starlette()
    install_catalog_routes(app)
    with TestClient(app) as test_client:
        yield test_client


def test_get_catalog_returns_status_and_entries(monkeypatch, client):
    monkeypatch.setattr(registry, "current", lambda: ("ready", [{"id": "a.b.c"}]))

    response = client.get("/catalog")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "entries": [{"id": "a.b.c"}]}


def test_get_catalog_entry_found(monkeypatch, client):
    monkeypatch.setattr(registry, "get_by_id", lambda entry_id: {"id": entry_id})

    response = client.get("/catalog/chat_app.src.services.foo.bar")

    assert response.status_code == 200
    assert response.json() == {"id": "chat_app.src.services.foo.bar"}


def test_get_catalog_entry_missing_is_404(monkeypatch, client):
    monkeypatch.setattr(registry, "get_by_id", lambda entry_id: None)

    response = client.get("/catalog/does.not.exist")

    assert response.status_code == 404
    assert "does.not.exist" in response.json()["error"]


def test_get_catalog_entry_snippet_found(monkeypatch, client):
    monkeypatch.setattr(registry, "get_by_id", lambda entry_id: {"id": entry_id, "type": "function"})
    monkeypatch.setattr(
        "src.routes.scanner.extract_snippet", lambda sources, entry: "@catalog\ndef bar(): ..."
    )

    response = client.get("/catalog/chat_app.src.services.foo.bar/snippet")

    assert response.status_code == 200
    assert response.json() == {"snippet": "@catalog\ndef bar(): ..."}


def test_get_catalog_entry_snippet_missing_entry_is_404(monkeypatch, client):
    monkeypatch.setattr(registry, "get_by_id", lambda entry_id: None)

    response = client.get("/catalog/does.not.exist/snippet")

    assert response.status_code == 404


def test_get_catalog_entry_snippet_unavailable_is_404(monkeypatch, client):
    monkeypatch.setattr(registry, "get_by_id", lambda entry_id: {"id": entry_id, "type": "function"})
    monkeypatch.setattr("src.routes.scanner.extract_snippet", lambda sources, entry: None)

    response = client.get("/catalog/chat_app.src.services.foo.bar/snippet")

    assert response.status_code == 404
    assert response.json() == {"error": "Snippet unavailable"}


def test_post_refresh_triggers_registry_refresh_and_returns_immediately(monkeypatch, client):
    calls = []
    monkeypatch.setattr(
        registry, "refresh", lambda sources, cache_path: calls.append((sources, cache_path))
    )

    response = client.post("/catalog/refresh")

    assert response.status_code == 200
    assert response.json() == {"status": "scanning"}
    assert len(calls) == 1


def test_health_returns_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_index_serves_html(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
