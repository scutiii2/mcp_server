from __future__ import annotations

import dataclasses

from fastapi.testclient import TestClient

from src.app import create_app
from tests.conftest import TEST_TOKEN

INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
HEADERS = {"Accept": "application/json, text/event-stream"}


def test_mcp_without_token_is_401(settings):
    with TestClient(create_app(settings)) as client:
        response = client.post("/mcp", json=INIT, headers=HEADERS)

    assert response.status_code == 401


def test_mcp_with_token_passes_the_middleware(settings):
    with TestClient(create_app(settings)) as client:
        response = client.post("/mcp", json=INIT, headers={**HEADERS, "X-Internal-Token": TEST_TOKEN})

    assert response.status_code != 401


def test_unset_token_never_validates(settings):
    open_settings = dataclasses.replace(settings, internal_api_token="")

    with TestClient(create_app(open_settings)) as client:
        response = client.post("/mcp", json=INIT, headers={**HEADERS, "X-Internal-Token": ""})

    assert response.status_code == 401


def test_rest_api_is_not_affected(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/health").status_code == 200
