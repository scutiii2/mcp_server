"""Tests for POST /upload/table - same Starlette TestClient pattern as test_upload_routes.py."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from src import upload_routes
from src.services import tables
from src.upload_routes import install_upload_routes

CSV = b"region,units\nEU,10\nUS,20\n"
HEADERS = {"X-Internal-Token": "shared-secret", "X-Requester-Username": "alice"}


@pytest.fixture
def client():
    app = Starlette()
    install_upload_routes(app)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def fake_settings(tmp_path, monkeypatch):
    fake = SimpleNamespace(internal_api_token="shared-secret", uploads_dir=tmp_path / "uploads")
    monkeypatch.setattr(upload_routes, "settings", fake)
    return fake


@pytest.fixture(autouse=True)
def fresh_registry(monkeypatch):
    registry = tables.TableRegistry()
    monkeypatch.setattr(tables, "registry", registry)
    return registry


def post(client, name="sales.csv", content=CSV, headers=HEADERS):
    return client.post("/upload/table", files={"file": (name, content, "text/csv")}, headers=headers)


def test_a_csv_becomes_a_table_owned_by_the_requester(client, fresh_registry):
    response = post(client)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["filename"] == "sales.csv" and body["rows"] == 2 and body["columns"] == ["region", "units"]
    assert body["sheet"] is None and body["notes"] == []
    assert fresh_registry.get(body["table_id"], "alice") is not None
    assert fresh_registry.get(body["table_id"], "bob") is None
    assert not (upload_routes.settings.uploads_dir).exists()  # nothing written to disk


def test_missing_or_wrong_token_is_a_401(client):
    assert post(client, headers={"X-Requester-Username": "alice"}).status_code == 401
    assert post(client, headers={**HEADERS, "X-Internal-Token": "nope"}).status_code == 401


def test_an_unset_token_never_validates(client, fake_settings):
    fake_settings.internal_api_token = ""

    assert post(client, headers={"X-Internal-Token": "", "X-Requester-Username": "alice"}).status_code == 401


def test_missing_file_is_a_400(client):
    assert client.post("/upload/table", headers=HEADERS).status_code == 400


def test_a_refused_file_is_a_400_with_the_reason(client):
    assert "Only .csv and .xlsx" in post(client, name="notes.txt").json()["error"]
    assert post(client, name="empty.csv", content=b"a,b\n").status_code == 400


def test_an_unidentified_caller_is_refused(client):
    response = post(client, headers={"X-Internal-Token": "shared-secret"})

    assert response.status_code == 400 and "not identified" in response.json()["error"]
