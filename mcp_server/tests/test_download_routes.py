"""GET /download?path=<id>: the route a download card's link reaches."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from src import download_routes
from src.download_routes import install_download_routes
from src.services import downloads
from src.services.downloads import DownloadRegistry

TOKEN = "shared-secret"


@pytest.fixture
def registry(monkeypatch) -> DownloadRegistry:
    fresh = DownloadRegistry()
    monkeypatch.setattr(downloads, "registry", fresh)
    return fresh


@pytest.fixture
def fake_settings(monkeypatch):
    fake = SimpleNamespace(internal_api_token=TOKEN)
    monkeypatch.setattr(download_routes, "settings", fake)
    return fake


@pytest.fixture
def client(registry, fake_settings):
    app = Starlette()
    install_download_routes(app)
    with TestClient(app) as test_client:
        yield test_client


def fetch(client, download_id, user="alice", token=TOKEN):
    headers = {}
    if token is not None:
        headers["X-Internal-Token"] = token
    if user is not None:
        headers["X-Requester-Username"] = user
    return client.get("/download", params={"path": download_id}, headers=headers)


def test_the_owner_gets_the_bytes_as_an_attachment(client, registry):
    entry = registry.offer("alice", "web-logs.log", b"line 1\nline 2\n")

    response = fetch(client, entry.id)

    assert response.status_code == 200
    assert response.content == b"line 1\nline 2\n"
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-disposition"] == "attachment; filename*=UTF-8''web-logs.log"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-length"] == "14"


def test_it_can_be_fetched_again_while_it_lasts(client, registry):
    entry = registry.offer("alice", "a.log", b"x")

    assert fetch(client, entry.id).status_code == 200
    assert fetch(client, entry.id).status_code == 200


def test_no_token_is_a_401(client, registry):
    entry = registry.offer("alice", "a.log", b"x")

    assert fetch(client, entry.id, token=None).status_code == 401


def test_a_wrong_token_is_a_401(client, registry):
    entry = registry.offer("alice", "a.log", b"x")

    assert fetch(client, entry.id, token="nope").status_code == 401


def test_an_unset_token_never_validates(client, registry, fake_settings):
    fake_settings.internal_api_token = ""
    entry = registry.offer("alice", "a.log", b"x")

    assert fetch(client, entry.id, token="").status_code == 401


def test_another_account_gets_the_same_404_as_an_unknown_id(client, registry):
    entry = registry.offer("alice", "a.log", b"x")

    other = fetch(client, entry.id, user="bob")
    unknown = fetch(client, "does-not-exist")

    assert (other.status_code, unknown.status_code) == (404, 404)
    assert other.json() == unknown.json()


def test_a_request_with_no_requester_gets_nothing(client, registry):
    entry = registry.offer("alice", "a.log", b"x")

    assert fetch(client, entry.id, user=None).status_code == 404
    assert fetch(client, entry.id, user="").status_code == 404


def test_an_expired_download_is_a_404(client, registry):
    clock = [0.0]
    short = DownloadRegistry(ttl_seconds=5, clock=lambda: clock[0])
    downloads.registry = short  # the fixture restores the real one afterwards
    entry = short.offer("alice", "a.log", b"x")
    assert fetch(client, entry.id).status_code == 200

    clock[0] = 5.0

    assert fetch(client, entry.id).status_code == 404


def test_a_missing_path_parameter_is_a_404(client):
    assert client.get("/download", headers={"X-Internal-Token": TOKEN, "X-Requester-Username": "alice"}).status_code == 404


@pytest.mark.parametrize("value", ["/etc/passwd", "../secrets/x", "C:\\boot.ini", "file:///etc/passwd"])
def test_a_file_path_is_never_served(client, registry, value):
    registry.offer("alice", "a.log", b"x")

    assert fetch(client, value).status_code == 404


def test_only_get_is_allowed(client, registry):
    entry = registry.offer("alice", "a.log", b"x")

    response = client.post("/download", params={"path": entry.id}, headers={"X-Internal-Token": TOKEN})

    assert response.status_code == 405
