"""/api/emberlings against FakeEmberlings: permission, validation, pass-through, audit."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.services.emberlings_gateway import UNAVAILABLE_MESSAGE
from tests.conftest import FakeEmailSender, FakeEmberlings
from tests.test_admin import login, make_member, role_by_name
from tests.test_registration import as_admin

KEY = {"Idempotency-Key": "key-1"}
ROUND = {"round": 1, "revision": 2}
START = {"encounter_id": "enc_1", "spark_id": "guardian", "preset_slot": 1, "mode": "autonomous", "emblem_limit": "rare"}

# (ember_api path, mini_games path, forwarded query)
READS = [
    ("/api/emberlings/catalog", "/sparks/catalog", None),
    ("/api/emberlings/profile", "/sparks/profile", None),
    (
        "/api/emberlings/sparks/guardian/personalities?limit=10&cursor=5",
        "/sparks/sparks/guardian/personalities",
        {"limit": 10, "cursor": 5},
    ),
    ("/api/emberlings/sparks/guardian/personalities", "/sparks/sparks/guardian/personalities", None),
    ("/api/emberlings/sparks/guardian/presets/2", "/sparks/sparks/guardian/presets/2", None),
    ("/api/emberlings/encounters/enc_1", "/sparks/encounters/enc_1", None),
    ("/api/emberlings/battles/bat-1", "/sparks/battles/bat-1", None),
]

ACTION = {**ROUND, "action": {"kind": "ability", "ability_id": "guardian_bulwark"}}
# (method, ember_api path, body sent, mini_games path, body forwarded, status)
MUTATIONS: list[tuple[str, str, dict[str, Any], str, Any, int]] = [
    ("POST", "/api/emberlings/profile", {"starter_spark_id": "guardian"}, "/sparks/profile", {"starter_spark_id": "guardian"}, 201),
    (
        "PUT",
        "/api/emberlings/sparks/guardian/presets/1",
        {"instance_ids": ["p1", "p2"]},
        "/sparks/sparks/guardian/presets/1",
        {"instance_ids": ["p1", "p2"]},
        200,
    ),
    ("POST", "/api/emberlings/encounters", {}, "/sparks/encounters", None, 201),
    ("POST", "/api/emberlings/encounters/enc_1/decline", {}, "/sparks/encounters/enc_1/decline", None, 200),
    ("POST", "/api/emberlings/battles", START, "/sparks/battles", START, 201),
    ("POST", "/api/emberlings/battles/b1/actions", ACTION, "/sparks/battles/b1/actions", ACTION, 200),
    ("POST", "/api/emberlings/battles/b1/emblem", {**ROUND, "tier": "normal"}, "/sparks/battles/b1/emblem", {**ROUND, "tier": "normal"}, 200),
    ("POST", "/api/emberlings/battles/b1/advance", ROUND, "/sparks/battles/b1/advance", ROUND, 200),
    ("POST", "/api/emberlings/battles/b1/mode", {**ROUND, "mode": "manual"}, "/sparks/battles/b1/mode", {**ROUND, "mode": "manual"}, 200),
    ("POST", "/api/emberlings/battles/b1/forfeit", {}, "/sparks/battles/b1/forfeit", None, 200),
    (
        "POST",
        "/api/emberlings/shop/purchases",
        {"kind": "emblem", "tier": "normal", "quantity": 2},
        "/sparks/shop/purchases",
        {"kind": "emblem", "tier": "normal", "quantity": 2},
        201,
    ),
    (
        "POST",
        "/api/emberlings/shop/purchases",
        {"kind": "copies", "tier": "rare", "spark_id": "bruiser"},
        "/sparks/shop/purchases",
        {"kind": "copies", "tier": "rare", "quantity": 1, "spark_id": "bruiser"},
        201,
    ),
    ("POST", "/api/emberlings/sparks/guardian/sales", {}, "/sparks/sparks/guardian/sales", None, 201),
]


def my_id(client: TestClient) -> int:
    return client.get("/api/auth/me").json()["id"]


# --- pass-through ---------------------------------------------------------------


@pytest.mark.parametrize(("path", "upstream_path", "params"), READS)
def test_reads_are_passed_through(client: TestClient, emberlings: FakeEmberlings, path, upstream_path, params) -> None:
    as_admin(client)

    response = client.get(path)

    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True}
    assert emberlings.calls == [
        {"method": "GET", "path": upstream_path, "owner": str(my_id(client)), "json": None, "params": params, "key": None}
    ]


@pytest.mark.parametrize(("method", "path", "body", "upstream_path", "forwarded", "status"), MUTATIONS)
def test_changes_are_passed_through_with_their_key(
    client: TestClient, emberlings: FakeEmberlings, method, path, body, upstream_path, forwarded, status
) -> None:
    as_admin(client)

    response = client.request(method, path, json=body, headers=KEY)

    assert response.status_code == status, response.text
    assert emberlings.calls == [
        {"method": method, "path": upstream_path, "owner": str(my_id(client)), "json": forwarded, "params": None, "key": "key-1"}
    ]


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (404, "no such battle"),
        (409, "the battle moved on; reload it and try again"),
        (400, "choose a starter from: guardian, scout, striker"),
    ],
)
def test_refusals_keep_their_status_and_message(client: TestClient, emberlings: FakeEmberlings, status, message) -> None:
    as_admin(client)
    emberlings.refuse = (status, message)

    response = client.post("/api/emberlings/battles/b1/advance", json=ROUND, headers=KEY)

    assert (response.status_code, response.json()["detail"]) == (status, message)


def test_unavailable_is_502(client: TestClient, emberlings: FakeEmberlings) -> None:
    as_admin(client)
    emberlings.unavailable = True

    response = client.get("/api/emberlings/profile")

    assert (response.status_code, response.json()["detail"]) == (502, UNAVAILABLE_MESSAGE)


# --- access ---------------------------------------------------------------------


def test_logged_out_is_401_before_anything_else(client: TestClient, emberlings: FakeEmberlings) -> None:
    assert client.get("/api/emberlings/catalog").status_code == 401
    # No key either: the login check comes first.
    assert client.post("/api/emberlings/encounters", json={}).status_code == 401
    assert emberlings.calls == []


def test_needs_emberlings_play(client: TestClient, email: FakeEmailSender, emberlings: FakeEmberlings) -> None:
    make_member(client, email)
    login(client, "alice")

    assert client.get("/api/emberlings/profile").status_code == 403
    assert client.post("/api/emberlings/encounters", json={}, headers=KEY).status_code == 403
    assert emberlings.calls == []


def test_the_administrator_role_has_the_permission_and_member_does_not(client: TestClient) -> None:
    as_admin(client)

    assert "emberlings.play" in role_by_name(client, "Administrator")["permissions"]
    assert "emberlings.play" not in role_by_name(client, "Member")["permissions"]


# --- validation -----------------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Idempotency-Key": ""},
        {"Idempotency-Key": "   "},
        {"Idempotency-Key": "k" * 201},
        {"Idempotency-Key": "has space"},
        {"Idempotency-Key": "a/b"},
        {"Idempotency-Key": "key;drop"},
    ],
)
def test_a_change_needs_an_idempotency_key(client: TestClient, emberlings: FakeEmberlings, headers) -> None:
    as_admin(client)

    response = client.post("/api/emberlings/battles/b1/advance", json=ROUND, headers=headers)

    assert response.status_code == 400
    assert "Idempotency-Key" in response.json()["detail"]
    assert emberlings.calls == []


@pytest.mark.parametrize("key", ["k" * 200, "AZaz09_.:-", "9b2f6c1e-3d4a-4f5b-8c7d-1234567890ab"])
def test_a_valid_key_is_accepted(client: TestClient, emberlings: FakeEmberlings, key) -> None:
    as_admin(client)

    response = client.post("/api/emberlings/battles/b1/advance", json=ROUND, headers={"Idempotency-Key": key})

    assert response.status_code == 200
    assert emberlings.calls[0]["key"] == key


@pytest.mark.parametrize(
    "query",
    ["limit=0", "limit=101", "limit=abc", "limit=1.5", "cursor=-1", "cursor=abc", "cursor=99999999999999999999"],
)
def test_bad_personality_paging_is_refused_and_never_forwarded(client: TestClient, emberlings: FakeEmberlings, query) -> None:
    as_admin(client)

    response = client.get(f"/api/emberlings/sparks/guardian/personalities?{query}")

    assert response.status_code in (400, 422), response.text
    assert emberlings.calls == []


def test_only_limit_and_cursor_are_forwarded(client: TestClient, emberlings: FakeEmberlings) -> None:
    as_admin(client)

    response = client.get("/api/emberlings/sparks/guardian/personalities?limit=100&cursor=0&owner=bob&sort=x")

    assert response.status_code == 200
    assert emberlings.calls[0]["params"] == {"limit": 100, "cursor": 0}


@pytest.mark.parametrize(
    ("path", "body", "word"),
    [
        ("/api/emberlings/battles/b1/advance", {**ROUND, "hp": 999}, "hp"),
        ("/api/emberlings/battles/b1/actions", {**ROUND, "action": {"kind": "attack", "damage": 50}}, "damage"),
        ("/api/emberlings/battles", {**START, "rewards": 1}, "rewards"),
        ("/api/emberlings/profile", {"starter_spark_id": "guardian", "owner": "bob"}, "owner"),
        ("/api/emberlings/battles/b1/advance", {"round": True, "revision": 2}, "round"),
        ("/api/emberlings/battles/b1/actions", {**ROUND, "action": {"kind": "steal"}}, "kind"),
        ("/api/emberlings/shop/purchases", {"kind": "copies", "tier": "rare"}, "spark_id"),
        ("/api/emberlings/shop/purchases", {"kind": "emblem", "tier": "normal", "quantity": 100}, "quantity"),
        ("/api/emberlings/battles", {**START, "spark_id": "../profile"}, "spark_id"),
    ],
)
def test_bad_bodies_are_400_and_never_forwarded(client: TestClient, emberlings: FakeEmberlings, path, body, word) -> None:
    as_admin(client)

    response = client.post(path, json=body, headers=KEY)

    assert response.status_code == 400, response.text
    assert word in response.json()["detail"]
    assert emberlings.calls == []


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/emberlings/battles/bad.id"),
        ("GET", "/api/emberlings/encounters/" + "x" * 65),
        ("GET", "/api/emberlings/sparks/guardian/presets/9"),
        ("GET", "/api/emberlings/sparks/guardian/presets/one"),
        ("POST", "/api/emberlings/sparks/bad.spark/sales"),
        ("POST", "/api/emberlings/battles/bad.id/forfeit"),
    ],
)
def test_bad_ids_are_400(client: TestClient, emberlings: FakeEmberlings, method, path) -> None:
    as_admin(client)

    response = client.request(method, path, json={} if method == "POST" else None, headers=KEY)

    assert response.status_code == 400, response.text
    assert emberlings.calls == []


# --- audit ----------------------------------------------------------------------


def action_log(client: TestClient) -> list[dict[str, Any]]:
    response = client.get("/api/logs/action", params={"actor": str(my_id(client))})
    assert response.status_code == 200, response.text
    return [e for e in response.json() if e["source"].startswith("emberlings.")]


def test_only_changes_of_value_are_audited(client: TestClient, emberlings: FakeEmberlings) -> None:
    as_admin(client)
    emberlings.responses[("POST", "/sparks/battles")] = {"id": "b1", "wild": {"name": "Bruiser", "level": 4}}
    emberlings.responses[("POST", "/sparks/shop/purchases")] = {"kind": "emblems", "tier_id": "normal", "quantity": 2, "price": 20}
    emberlings.responses[("POST", "/sparks/sparks/guardian/sales")] = {"kind": "sale", "spark_id": "guardian", "value": 12}

    for method, path, body, *_ in MUTATIONS:
        assert client.request(method, path, json=body, headers=KEY).status_code < 300
    for path, *_ in READS:
        assert client.get(path).status_code == 200

    entries = action_log(client)
    assert sorted(e["source"] for e in entries) == [
        "emberlings.battle_forfeit",
        "emberlings.battle_start",
        "emberlings.profile_create",
        "emberlings.shop_buy",
        "emberlings.shop_buy",
        "emberlings.spark_sell",
    ]
    messages = {e["message"] for e in entries}
    assert "Started Emberlings with the starter 'guardian'" in messages
    assert "Started a battle against Bruiser (level 4)" in messages
    assert "Bought 2 normal EMBLEMs for 20 Insignia" in messages
    assert "Sold a guardian copy for 12 Insignia" in messages


def test_a_refused_change_is_not_audited(client: TestClient, emberlings: FakeEmberlings) -> None:
    as_admin(client)
    emberlings.refuse = (409, "that costs 40 Insignia and you have 3")

    assert client.post("/api/emberlings/shop/purchases", json={"kind": "emblem", "tier": "rare"}, headers=KEY).status_code == 409
    assert action_log(client) == []
