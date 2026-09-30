"""The command form's server side: select options from a tool's declared
options_url, and file uploads to mcp_server for file-path parameters."""

from __future__ import annotations

import base64

import httpx
from fastapi.testclient import TestClient

from src.services.mcp_server_info import normalize_options
from tests.conftest import FakeServerTools, FakeUpstream
from tests.test_registration import as_admin

SAVED_PATH = r"C:\data\uploads\abc.csv"


def mcp_server(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/options/apps":
        return httpx.Response(200, json=["web", {"value": "db", "label": "Database", "host": "10.0.0.2"}])
    if path.startswith("/options/apps/") and path.endswith("/versions"):
        app = path.split("/")[3]
        return httpx.Response(200, json={f"{app}-1": f"{app} v1"})
    if path == "/upload" and request.method == "POST":
        if request.headers.get("x-internal-token") != "s3cret":
            return httpx.Response(401, json={"error": "Invalid or missing internal API token"})
        if b'filename="input.csv"' not in request.content:
            return httpx.Response(400, json={"error": "Unsupported file type - allowed: .csv"})
        return httpx.Response(200, json={"path": SAVED_PATH})
    return httpx.Response(404, json={"error": "no route"})


def test_options_come_from_a_declared_template(
    client: TestClient, upstream: FakeUpstream, server_tools: FakeServerTools
) -> None:
    upstream.handler = mcp_server
    server_tools.templates = {"/options/apps", "/options/apps/{app}/versions"}
    as_admin(client)

    response = client.get("/api/commands/options", params={"template": "/options/apps"})
    assert response.status_code == 200, response.text
    assert response.json() == [
        {"value": "web", "label": "web", "extra": {}},
        {"value": "db", "label": "Database", "extra": {"host": "10.0.0.2"}},
    ]

    dependent = client.get(
        "/api/commands/options", params={"template": "/options/apps/{app}/versions", "arg.app": "web/x"}
    )
    assert dependent.status_code == 200, dependent.text
    assert upstream.requests[-1].url.raw_path == b"/options/apps/web%2Fx/versions"

    missing = client.get("/api/commands/options", params={"template": "/options/apps/{app}/versions"})
    assert missing.status_code == 400 and "arg.app" in missing.json()["detail"]


def test_options_refuse_undeclared_paths(client: TestClient, upstream: FakeUpstream, server_tools: FakeServerTools) -> None:
    upstream.handler = mcp_server
    server_tools.templates = {"http://evil.example/x"}
    as_admin(client)

    for template in ("/capabilities", "http://evil.example/x"):
        response = client.get("/api/commands/options", params={"template": template})
        assert response.status_code == 400, template
    assert upstream.requests == []

    server_tools.unreachable = True
    assert client.get("/api/commands/options", params={"template": "/x"}).status_code == 502


def test_upload_forwards_the_file_with_the_token(client_factory, upstream: FakeUpstream) -> None:
    upstream.handler = mcp_server
    client = client_factory(internal_token="s3cret")
    as_admin(client)
    data = base64.b64encode(b"a,b\n1,2\n").decode()

    response = client.post("/api/uploads", json={"filename": r"C:\Users\me\input.csv", "data": data})

    assert response.status_code == 201, response.text
    assert response.json() == {"path": SAVED_PATH}
    sent = upstream.requests[-1]
    assert sent.url.path == "/upload" and b"a,b\n1,2\n" in sent.content

    refused = client.post("/api/uploads", json={"filename": "x.exe", "data": data})
    assert refused.status_code == 400 and "Unsupported file type" in refused.json()["detail"]
    assert client.post("/api/uploads", json={"filename": "x.csv", "data": "not base64!"}).status_code == 400


def test_command_form_needs_login(client: TestClient) -> None:
    assert client.get("/api/commands/options", params={"template": "/x"}).status_code == 401
    assert client.post("/api/uploads", json={"filename": "a.csv", "data": "YQ=="}).status_code == 401


def test_normalize_options_shapes() -> None:
    assert normalize_options({"a": "A"}) == [{"value": "a", "label": "A"}]
    assert normalize_options(["x", None, {"label": "no value"}, 3]) == [
        {"value": "x", "label": "x"},
        {"value": "3", "label": "3"},
    ]
    assert normalize_options("nonsense") == []
