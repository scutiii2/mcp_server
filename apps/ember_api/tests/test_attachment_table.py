"""POST /api/attachments/table: forwards a CSV/XLSX to mcp_server's /upload/table."""

from __future__ import annotations

import base64

import httpx
from fastapi.testclient import TestClient

from tests.conftest import FakeUpstream
from tests.test_registration import as_admin

TABLE = {"table_id": "tbl-1", "filename": "sales.csv", "rows": 2, "columns": ["region", "units"], "sheet": None, "notes": []}


def mcp_server(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/upload/table" and request.method == "POST":
        if b'filename="bad.csv"' in request.content:
            return httpx.Response(400, json={"error": "The file needs a header row and at least one data row."})
        return httpx.Response(200, json=TABLE)
    return httpx.Response(404, json={"error": "no route"})


def post(client: TestClient, filename: str, content: bytes = b"region,units\nEU,1\n"):
    return client.post(
        "/api/attachments/table", json={"filename": filename, "data": base64.b64encode(content).decode()}
    )


def test_a_csv_is_forwarded_and_the_table_info_comes_back(client: TestClient, upstream: FakeUpstream) -> None:
    upstream.handler = mcp_server
    as_admin(client)

    response = post(client, "C:\\Users\\me\\sales.csv")

    assert response.status_code == 200, response.text
    assert response.json() == TABLE
    sent = upstream.requests[-1]
    assert sent.url.path == "/upload/table"
    assert b'filename="sales.csv"' in sent.content and b"region,units" in sent.content
    assert sent.headers["x-requester-username"] == "root"


def test_other_file_types_and_bad_input_are_refused_before_mcp_server(client: TestClient, upstream: FakeUpstream) -> None:
    upstream.handler = mcp_server
    as_admin(client)

    refused = post(client, "notes.txt")
    assert refused.status_code == 400 and ".csv and .xlsx" in refused.json()["detail"]
    assert client.post("/api/attachments/table", json={"filename": "a.csv", "data": "not base64!"}).status_code == 400
    assert upstream.requests == []


def test_a_refusal_from_mcp_server_is_a_400_with_its_reason(client: TestClient, upstream: FakeUpstream) -> None:
    upstream.handler = mcp_server
    as_admin(client)

    response = post(client, "bad.csv")

    assert response.status_code == 400 and "header row" in response.json()["detail"]


def test_an_unreachable_mcp_server_is_a_502(client: TestClient, upstream: FakeUpstream) -> None:
    upstream.unreachable = True
    as_admin(client)

    assert post(client, "sales.csv").status_code == 502


def test_it_needs_a_login(client: TestClient) -> None:
    assert post(client, "sales.csv").status_code == 401


def test_a_token_mismatch_at_mcp_server_is_a_502_not_a_400(client: TestClient, upstream: FakeUpstream) -> None:
    upstream.handler = lambda request: httpx.Response(401, json={"error": "bad internal token"})
    as_admin(client)

    response = post(client, "sales.csv")

    assert response.status_code == 502 and response.json()["detail"] == "mcp_server is unreachable"


def test_the_table_upload_waits_longer_than_the_default(client: TestClient, upstream: FakeUpstream) -> None:
    upstream.handler = mcp_server
    as_admin(client)

    assert post(client, "sales.csv").status_code == 200
    assert upstream.requests[-1].extensions["timeout"]["read"] == 120.0
