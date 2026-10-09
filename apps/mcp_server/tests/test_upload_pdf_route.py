from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx
import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient
from src import upload_routes

def upstream_response(*args, **kwargs):
    return httpx.Response(*args, request=httpx.Request("GET", "http://pdf/api/files"), **kwargs)

HEADERS = {"X-Internal-Token": "shared", "X-Requester-Username": "alice"}
FILE = {"file_id": "f_1", "name": "scan.pdf", "pages": 2, "kind": "pdf", "size": 12, "expires_at": 2000000000}

@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(upload_routes, "settings", SimpleNamespace(internal_api_token="shared", extensions_config_path="unused"))
    config = SimpleNamespace(transport="http", url="http://pdf/base/mcp", forward_requester=True, headers={"x-internal-token": "pdf-secret", "X-Requester-Username": "must-not-win"})
    monkeypatch.setattr(upload_routes, "load_extension_config", lambda _, id_: config)
    upstream = AsyncMock()
    upstream.get.return_value = upstream_response(200, json=[])
    upstream.post.return_value = upstream_response(201, json=FILE)
    factory = AsyncMock()
    factory.__aenter__.return_value = upstream
    monkeypatch.setattr(upload_routes.httpx, "AsyncClient", lambda **_: factory)
    app = Starlette(); upload_routes.install_upload_routes(app)
    with TestClient(app) as client:
        yield client, upstream, config

def post(client, headers=HEADERS, filename="C:\\docs\\scan.pdf", content=b"%PDF-original"):
    return client.post("/upload/pdf", headers=headers, files={"file": (filename, content)})

def test_original_bytes_and_authenticated_owner(setup):
    client, upstream, _ = setup
    response = post(client)
    assert response.status_code == 200 and response.json() == FILE
    url = upstream.post.call_args.args[0]
    sent = upstream.post.call_args.kwargs
    assert url == "http://pdf/base/api/files"
    assert sent["content"] == b"%PDF-original"
    assert sent["headers"]["X-Requester-Username"] == "alice"
    assert sent["headers"]["X-Internal-Token"] == "pdf-secret"
    assert sent["headers"]["X-Filename"] == "scan.pdf"

def test_invalid_token_and_missing_identity_cannot_upload(setup):
    client, upstream, _ = setup
    assert post(client, headers={}).status_code == 401
    assert post(client, headers={"X-Internal-Token": "shared"}).status_code == 400
    upstream.post.assert_not_called()

@pytest.mark.parametrize("setting", ["forward_requester", "headers"])
def test_missing_trusted_configuration(setup, setting):
    client, upstream, config = setup
    setattr(config, setting, False if setting == "forward_requester" else {})
    assert post(client).status_code == 503
    upstream.post.assert_not_called()

def test_wrong_pdf_token_is_rejected_before_upload(setup):
    client, upstream, _ = setup
    upstream.get.return_value = upstream_response(200, json=[], headers={"set-cookie": "pm_session=browser; Path=/"})
    assert post(client).status_code == 502
    upstream.post.assert_not_called()

def test_upstream_refusal_and_network_failure(setup):
    client, upstream, _ = setup
    upstream.post.return_value = upstream_response(415, json={"error": {"message": "Not a valid PDF"}})
    response = post(client)
    assert response.status_code == 400 and response.json()["error"] == "Not a valid PDF"
    upstream.get.side_effect = httpx.ConnectError("offline")
    assert post(client).status_code == 502

def test_limit_and_unsupported_types(setup):
    client, upstream, _ = setup
    assert post(client, filename="a.exe").status_code == 400
    assert post(client, content=b"x" * (15 * 1024 * 1024 + 1)).status_code == 413
    upstream.post.assert_not_called()
