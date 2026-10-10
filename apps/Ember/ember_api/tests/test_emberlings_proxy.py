"""The real EmberlingsGateway behind /api/emberlings, talking to a fake
mini_games: what actually leaves ember_api, and what never reaches the browser."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from src.app import create_app
from src.config import DEFAULT_EMBERLINGS_URL
from src.services.traffic import TrafficRecorder
from tests.conftest import FakeAgent, FakeEmailSender, FakeServerTools, FakeUpstream, make_settings
from tests.test_registration import as_admin

TOKEN = "shared-secret"


@pytest.fixture
def real_client(
    tmp_path: Path,
    email: FakeEmailSender,
    upstream: FakeUpstream,
    agent: FakeAgent,
    server_tools: FakeServerTools,
    traffic: TrafficRecorder,
) -> Iterator[TestClient]:
    app = create_app(
        make_settings(tmp_path, internal_token=TOKEN),
        email_sender=email,
        upstream_transport=httpx.MockTransport(upstream),
        agent_gateway=agent,
        server_tools=server_tools,
        traffic=traffic,
    )
    with TestClient(app) as client:
        yield client


def games(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"id": "b1", "status": "active"})


def sent_to_games(upstream: FakeUpstream) -> list[httpx.Request]:
    return [r for r in upstream.requests if str(r.url).startswith(DEFAULT_EMBERLINGS_URL)]


def test_owner_and_token_come_from_ember_api_not_the_browser(real_client: TestClient, upstream: FakeUpstream) -> None:
    upstream.handler = games
    as_admin(real_client)
    me = real_client.get("/api/auth/me").json()

    response = real_client.post(
        "/api/emberlings/battles/b1/advance",
        json={"round": 1, "revision": 2},
        headers={
            "Idempotency-Key": "key-1",
            "X-Requester-Username": "mallory",
            "X-Requester-Email": "mallory@evil.example",
            "X-Internal-Token": "guess",
        },
    )

    assert response.status_code == 200, response.text
    [sent] = sent_to_games(upstream)
    assert str(sent.url) == f"{DEFAULT_EMBERLINGS_URL}/ascendeds/battles/b1/advance"
    assert sent.headers["X-Requester-Username"] == str(me["id"]) != me["username"]
    assert sent.headers["X-Internal-Token"] == TOKEN
    assert sent.headers["Idempotency-Key"] == "key-1"
    assert "X-Requester-Email" not in sent.headers
    assert json.loads(sent.content) == {"round": 1, "revision": 2}


def test_a_token_mismatch_shows_neither_address_nor_token(real_client: TestClient, upstream: FakeUpstream) -> None:
    upstream.handler = lambda r: httpx.Response(401, json={"error": "Invalid or missing internal API token"})
    as_admin(real_client)

    response = real_client.get("/api/emberlings/catalog")

    assert response.status_code == 502
    assert response.json() == {"detail": "Emberlings is not available right now"}
    assert "8060" not in response.text and TOKEN not in response.text


def test_mini_games_down_is_502(real_client: TestClient, upstream: FakeUpstream) -> None:
    upstream.unreachable = True
    as_admin(real_client)

    assert real_client.get("/api/emberlings/profile").status_code == 502


def test_a_refusal_reaches_the_browser_as_detail(real_client: TestClient, upstream: FakeUpstream) -> None:
    upstream.handler = lambda r: httpx.Response(409, json={"error": "a new encounter can be rolled in 12 seconds", "retry_after": 12})
    as_admin(real_client)

    response = real_client.post("/api/emberlings/encounters", json={}, headers={"Idempotency-Key": "k"})

    assert (response.status_code, response.json()) == (409, {"detail": "a new encounter can be rolled in 12 seconds"})


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/emberlings/catalog", None),
        ("GET", "/api/emberlings/ascendeds/guardian/personalities?limit=5", None),
        ("POST", "/api/emberlings/encounters", {}),
        ("POST", "/api/emberlings/battles/b1/forfeit", {}),
        ("PUT", "/api/emberlings/ascendeds/guardian/presets/1", {"instance_ids": ["i1"]}),
    ],
)
def test_browser_identity_headers_never_reach_mini_games(
    real_client: TestClient, upstream: FakeUpstream, method: str, path: str, body: dict | None
) -> None:
    upstream.handler = games
    as_admin(real_client)
    me = real_client.get("/api/auth/me").json()

    response = real_client.request(
        method,
        path,
        json=body,
        headers={
            "Idempotency-Key": "k",
            "X-Requester-Username": "mallory",
            "x-requester-email": "mallory@evil.example",
            "x-internal-token": "guess",
        },
    )

    assert response.status_code in (200, 201), response.text
    [sent] = sent_to_games(upstream)
    assert sent.headers.get_list("X-Requester-Username") == [str(me["id"])]
    assert sent.headers.get_list("X-Internal-Token") == [TOKEN]
    assert "X-Requester-Email" not in sent.headers
    assert "mallory" not in str(sent.headers)


def test_the_gateway_never_follows_a_redirect(real_client: TestClient, upstream: FakeUpstream) -> None:
    upstream.handler = lambda r: httpx.Response(302, json={"id": "x"}, headers={"Location": "http://evil.example/steal"})
    as_admin(real_client)

    response = real_client.get("/api/emberlings/catalog")

    assert response.status_code == 502
    assert not any("evil.example" in str(r.url) for r in upstream.requests)
    assert real_client.app.state.emberlings._client.follow_redirects is False
