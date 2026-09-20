"""Tests for POST /upload - same Starlette TestClient pattern as
test_help_routes.py."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from src import upload_routes
from src.upload_routes import install_upload_routes


@pytest.fixture
def client():
    app = Starlette()
    install_upload_routes(app)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def fake_settings(tmp_path, monkeypatch):
    fake = SimpleNamespace(internal_api_token="shared-secret", uploads_dir=tmp_path / "uploads")
    monkeypatch.setattr(upload_routes, "settings", fake)
    return fake


def test_upload_missing_token_is_a_401(client, fake_settings):
    response = client.post("/upload", files={"file": ("input.xlsx", b"data", "application/vnd.ms-excel")})

    assert response.status_code == 401


def test_upload_wrong_token_is_a_401(client, fake_settings):
    response = client.post(
        "/upload",
        files={"file": ("input.xlsx", b"data", "application/vnd.ms-excel")},
        headers={"X-Internal-Token": "not-the-secret"},
    )

    assert response.status_code == 401


def test_upload_with_no_configured_token_never_validates(client, fake_settings):
    """An unset expected token must never validate against an equally
    empty header - same "forgot to configure this must not mean anyone
    can call it" reasoning as chat_app's internal_routes.py."""
    fake_settings.internal_api_token = ""

    response = client.post(
        "/upload",
        files={"file": ("input.xlsx", b"data", "application/vnd.ms-excel")},
        headers={"X-Internal-Token": ""},
    )

    assert response.status_code == 401


def test_upload_missing_file_is_a_400(client, fake_settings):
    response = client.post("/upload", headers={"X-Internal-Token": "shared-secret"})

    assert response.status_code == 400


def test_upload_disallowed_extension_is_a_400(client, fake_settings):
    response = client.post(
        "/upload",
        files={"file": ("script.exe", b"data", "application/octet-stream")},
        headers={"X-Internal-Token": "shared-secret"},
    )

    assert response.status_code == 400


def test_upload_success_writes_the_file_under_uploads_dir_with_a_generated_name(client, fake_settings):
    response = client.post(
        "/upload",
        files={"file": ("input.xlsx", b"binary content", "application/vnd.ms-excel")},
        headers={"X-Internal-Token": "shared-secret"},
    )

    assert response.status_code == 200
    saved_path = response.json()["path"]
    from pathlib import Path

    path = Path(saved_path)
    assert path.exists()
    assert path.read_bytes() == b"binary content"
    assert path.suffix == ".xlsx"
    assert path.parent == fake_settings.uploads_dir.resolve()
    # Never the client-supplied filename - see upload_routes.py's docstring
    # on why (path traversal / collisions).
    assert path.stem != "input"
