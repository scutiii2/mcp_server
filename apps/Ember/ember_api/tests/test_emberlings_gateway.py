"""EmberlingsGateway against a fake mini_games (httpx.MockTransport)."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest

from src.models import Account
from src.services.emberlings_gateway import (
    TIMEOUT_SECONDS,
    UNAVAILABLE_MESSAGE,
    EmberlingsGateway,
    EmberlingsRefused,
    EmberlingsUnavailable,
    is_allowed,
)
from src.services.traffic import TrafficRecorder

BASE = "http://games.internal:8060/"
ACCOUNT = cast(Account, SimpleNamespace(id=7, username="alice", email="alice@example.com"))

Handler = Callable[[httpx.Request], httpx.Response]


def call(handler: Handler, method: str, path: str, *, token: str | None = "tok", **kwargs: Any) -> tuple[Any, list[httpx.Request]]:
    """One gateway request against `handler`; returns the result and what was sent."""
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    async def run() -> Any:
        async with httpx.AsyncClient(transport=httpx.MockTransport(record)) as client:
            return await EmberlingsGateway(client, BASE, token, TrafficRecorder()).request(method, path, ACCOUNT, **kwargs)

    return asyncio.run(run()), seen


def test_sends_the_owner_id_token_key_and_body() -> None:
    result, seen = call(
        lambda r: httpx.Response(200, json={"id": "b1"}),
        "POST",
        "/ascension/battles/b1/advance",
        json={"round": 1, "revision": 2},
        idempotency_key="key-1",
    )

    assert result == {"id": "b1"}
    sent = seen[0]
    assert str(sent.url) == "http://games.internal:8060/ascendeds/battles/b1/advance"
    # The account id, never the username: a renamed account keeps its Ascended.
    assert sent.headers["X-Requester-Username"] == "7"
    assert sent.headers["X-Internal-Token"] == "tok"
    assert sent.headers["Idempotency-Key"] == "key-1"
    assert "X-Requester-Email" not in sent.headers
    assert json.loads(sent.content) == {"round": 1, "revision": 2}
    assert sent.extensions["timeout"] == {
        "connect": TIMEOUT_SECONDS,
        "read": TIMEOUT_SECONDS,
        "write": TIMEOUT_SECONDS,
        "pool": TIMEOUT_SECONDS,
    }


def test_reset_profile_posts_confirm_with_owner_token_and_key() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"reset": True})

    async def run() -> Any:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await EmberlingsGateway(client, BASE, "tok", TrafficRecorder()).reset_profile(ACCOUNT, "key-9")

    assert asyncio.run(run()) == {"reset": True}
    sent = seen[0]
    assert (sent.method, str(sent.url)) == ("POST", "http://games.internal:8060/ascendeds/profile/reset")
    assert sent.headers["X-Requester-Username"] == "7"
    assert sent.headers["X-Internal-Token"] == "tok"
    assert sent.headers["Idempotency-Key"] == "key-9"
    assert json.loads(sent.content) == {"confirm": True}


def test_sends_a_query_and_leaves_out_headers_it_does_not_have() -> None:
    _, seen = call(
        lambda r: httpx.Response(200, json={"items": [], "next_cursor": None}),
        "GET",
        "/ascension/ascendeds/guardian/personalities",
        token=None,
        params={"limit": 10, "cursor": 5},
    )

    sent = seen[0]
    assert dict(sent.url.params) == {"limit": "10", "cursor": "5"}
    assert "X-Internal-Token" not in sent.headers
    assert "Idempotency-Key" not in sent.headers
    assert sent.content == b""


def test_no_content_is_none() -> None:
    result, _ = call(lambda r: httpx.Response(204), "GET", "/ascension/profile")

    assert result is None


@pytest.mark.parametrize("status", [400, 404, 409])
def test_refusals_keep_their_status_and_message(status: int) -> None:
    with pytest.raises(EmberlingsRefused) as raised:
        call(
            lambda r: httpx.Response(status, json={"error": "the battle moved on; reload it and try again"}),
            "POST",
            "/ascension/battles/b1/advance",
            json={"round": 1, "revision": 1},
            idempotency_key="k",
        )

    assert (raised.value.status, str(raised.value)) == (status, "the battle moved on; reload it and try again")


def test_a_fastapi_detail_is_read_and_other_client_errors_become_400() -> None:
    with pytest.raises(EmberlingsRefused) as raised:
        call(lambda r: httpx.Response(422, json={"detail": "bad body"}), "POST", "/ascension/profile", json={}, idempotency_key="k")

    assert (raised.value.status, str(raised.value)) == (400, "bad body")


def test_a_wrong_token_is_unavailable_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="src.services.emberlings_gateway"):
        with pytest.raises(EmberlingsUnavailable):
            call(lambda r: httpx.Response(401, json={"error": "Invalid or missing internal API token"}), "GET", "/ascension/catalog")

    assert "INTERNAL_API_TOKEN" in caplog.text


@pytest.mark.parametrize("response", [httpx.Response(500, json={"error": "boom"}), httpx.Response(200, text="not json")])
def test_server_errors_and_garbage_are_unavailable(response: httpx.Response) -> None:
    with pytest.raises(EmberlingsUnavailable):
        call(lambda r: response, "GET", "/ascension/catalog")


def test_no_connection_is_unavailable() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(EmberlingsUnavailable):
        call(refuse, "GET", "/ascension/catalog")


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/ascension/catalog"),
        ("POST", "/ascension/profile"),
        ("POST", "/ascension/profile/reset"),
        ("GET", "/ascension/profile"),
        ("GET", "/ascension/ascendeds/guardian/personalities"),
        ("GET", "/ascension/ascendeds/guardian/presets/1"),
        ("PUT", "/ascension/ascendeds/guardian/presets/5"),
        ("POST", "/ascension/encounters"),
        ("GET", "/ascension/encounters/Ab_c-1"),
        ("POST", "/ascension/encounters/Ab_c-1/decline"),
        ("POST", "/ascension/battles"),
        ("GET", "/ascension/battles/b1"),
        ("POST", "/ascension/battles/b1/actions"),
        ("POST", "/ascension/battles/b1/emblem"),
        ("POST", "/ascension/battles/b1/advance"),
        ("POST", "/ascension/battles/b1/mode"),
        ("POST", "/ascension/battles/b1/forfeit"),
        ("POST", "/ascension/shop/purchases"),
        ("POST", "/ascension/ascendeds/guardian/sales"),
    ],
)
def test_every_route_of_the_spec_is_allowed(method: str, path: str) -> None:
    assert is_allowed(method, path)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/ascension/admin"),
        ("DELETE", "/ascension/profile"),
        ("GET", "/ascension/battles/../profile"),
        ("POST", "/ascension/battles/b1/rewards"),
        ("GET", "/ascension/ascendeds/guardian/presets/9"),
        ("GET", "/health"),
    ],
)
def test_nothing_else_is_reachable(method: str, path: str) -> None:
    assert not is_allowed(method, path)
    with pytest.raises(ValueError):
        call(lambda r: httpx.Response(200, json={}), method, path)


# --- hardening ------------------------------------------------------------------

SECRET_URL = "http://10.9.8.7:8060/ascendeds/catalog?token=hunter2"


def test_a_transport_error_is_neither_logged_nor_raised_with_its_text(caplog: pytest.LogCaptureFixture) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot connect to {SECRET_URL}", request=request)

    with caplog.at_level(logging.WARNING, logger="src.services.emberlings_gateway"):
        with pytest.raises(EmberlingsUnavailable) as raised:
            call(refuse, "GET", "/ascension/catalog")

    assert str(raised.value) == UNAVAILABLE_MESSAGE
    assert "10.9.8.7" not in caplog.text and "hunter2" not in caplog.text
    assert "ConnectError" in caplog.text and "GET" in caplog.text and "/ascension/catalog" in caplog.text


def test_an_invalid_url_is_unavailable() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.InvalidURL(f"bad url {SECRET_URL}")

    with pytest.raises(EmberlingsUnavailable) as raised:
        call(refuse, "GET", "/ascension/catalog")

    assert str(raised.value) == UNAVAILABLE_MESSAGE


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_a_redirect_is_unavailable_even_with_a_json_body(status: int) -> None:
    with pytest.raises(EmberlingsUnavailable):
        call(lambda r: httpx.Response(status, json={"id": "x"}, headers={"Location": "http://evil.example/"}), "GET", "/ascension/catalog")


def traffic_status(status: int) -> list[str]:
    traffic = TrafficRecorder()
    handler = lambda r: httpx.Response(status, json={"error": "x"})  # noqa: E731

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises((EmberlingsUnavailable, EmberlingsRefused)):
                await EmberlingsGateway(client, BASE, "tok", traffic).request("GET", "/ascension/catalog", ACCOUNT)

    asyncio.run(run())
    return [key[2] for key in traffic.pending()]


@pytest.mark.parametrize(("status", "expected"), [(401, "failed"), (500, "failed"), (503, "failed"), (302, "failed"), (409, "ok"), (404, "ok")])
def test_traffic_counts_a_token_refusal_and_server_errors_as_failed(status: int, expected: str) -> None:
    assert traffic_status(status) == [expected]


def test_a_long_message_from_mini_games_is_cut_to_300_characters() -> None:
    with pytest.raises(EmberlingsRefused) as raised:
        call(lambda r: httpx.Response(409, json={"error": "x" * 5000}), "POST", "/ascension/profile", json={}, idempotency_key="k")

    assert len(str(raised.value)) == 300
