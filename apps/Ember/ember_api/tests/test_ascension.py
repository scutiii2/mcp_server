"""/api/ascension against FakeAscension: permission, validation, pass-through, audit."""

from __future__ import annotations

import re
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.services.ascension_gateway import UNAVAILABLE_MESSAGE
from tests.conftest import FakeEmailSender, FakeAscension
from tests.test_admin import login, make_member, role_by_name
from tests.test_registration import as_admin

KEY = {"Idempotency-Key": "key-1"}
ROUND = {"round": 1, "revision": 2}
START = {"encounter_id": "enc_1", "ascended_id": "guardian", "preset_slot": 1, "mode": "autonomous", "emblem_limit": "rare"}

# (ember_api path, mini_games path, forwarded query)
READS = [
    ("/api/ascension/catalog", "/ascension/catalog", None),
    ("/api/ascension/profile", "/ascension/profile", None),
    (
        "/api/ascension/ascendeds/guardian/personalities?limit=10&cursor=5",
        "/ascension/ascendeds/guardian/personalities",
        {"limit": 10, "cursor": 5},
    ),
    ("/api/ascension/ascendeds/guardian/personalities", "/ascension/ascendeds/guardian/personalities", None),
    ("/api/ascension/ascendeds/guardian/presets/2", "/ascension/ascendeds/guardian/presets/2", None),
    ("/api/ascension/encounters/enc_1", "/ascension/encounters/enc_1", None),
    ("/api/ascension/battles/bat-1", "/ascension/battles/bat-1", None),
]

ACTION = {**ROUND, "action": {"kind": "ability", "ability_id": "guardian_bulwark"}}
# (method, ember_api path, body sent, mini_games path, body forwarded, status)
MUTATIONS: list[tuple[str, str, dict[str, Any], str, Any, int]] = [
    ("POST", "/api/ascension/profile", {"starter_ascended_id": "guardian"}, "/ascension/profile", {"starter_ascended_id": "guardian"}, 201),
    (
        "PUT",
        "/api/ascension/ascendeds/guardian/presets/1",
        {"instance_ids": ["p1", "p2"]},
        "/ascension/ascendeds/guardian/presets/1",
        {"instance_ids": ["p1", "p2"]},
        200,
    ),
    ("POST", "/api/ascension/profile/reset", {}, "/ascension/profile/reset", {"confirm": True}, 200),
    ("POST", "/api/ascension/encounters", {}, "/ascension/encounters", None, 201),
    ("POST", "/api/ascension/encounters/enc_1/decline", {}, "/ascension/encounters/enc_1/decline", None, 200),
    ("POST", "/api/ascension/battles", START, "/ascension/battles", START, 201),
    ("POST", "/api/ascension/battles/b1/actions", ACTION, "/ascension/battles/b1/actions", ACTION, 200),
    ("POST", "/api/ascension/battles/b1/emblem", {**ROUND, "tier": "common"}, "/ascension/battles/b1/emblem", {**ROUND, "tier": "common"}, 200),
    ("POST", "/api/ascension/battles/b1/advance", ROUND, "/ascension/battles/b1/advance", ROUND, 200),
    ("POST", "/api/ascension/battles/b1/mode", {**ROUND, "mode": "manual"}, "/ascension/battles/b1/mode", {**ROUND, "mode": "manual"}, 200),
    ("POST", "/api/ascension/battles/b1/forfeit", {}, "/ascension/battles/b1/forfeit", None, 200),
    (
        "POST",
        "/api/ascension/shop/purchases",
        {"kind": "emblem", "tier": "common", "quantity": 2},
        "/ascension/shop/purchases",
        {"kind": "emblem", "tier": "common", "quantity": 2},
        201,
    ),
    (
        "POST",
        "/api/ascension/shop/purchases",
        {"kind": "copies", "tier": "rare", "ascended_id": "bruiser"},
        "/ascension/shop/purchases",
        {"kind": "copies", "tier": "rare", "quantity": 1, "ascended_id": "bruiser"},
        201,
    ),
    ("POST", "/api/ascension/ascendeds/guardian/sales", {}, "/ascension/ascendeds/guardian/sales", None, 201),
]


def my_id(client: TestClient) -> int:
    return client.get("/api/auth/me").json()["id"]


# --- pass-through ---------------------------------------------------------------


@pytest.mark.parametrize(("path", "upstream_path", "params"), READS)
def test_reads_are_passed_through(client: TestClient, ascension: FakeAscension, path, upstream_path, params) -> None:
    as_admin(client)

    response = client.get(path)

    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True}
    assert ascension.calls == [
        {"method": "GET", "path": upstream_path, "owner": str(my_id(client)), "json": None, "params": params, "key": None}
    ]


@pytest.mark.parametrize(("method", "path", "body", "upstream_path", "forwarded", "status"), MUTATIONS)
def test_changes_are_passed_through_with_their_key(
    client: TestClient, ascension: FakeAscension, method, path, body, upstream_path, forwarded, status
) -> None:
    as_admin(client)

    response = client.request(method, path, json=body, headers=KEY)

    assert response.status_code == status, response.text
    assert ascension.calls == [
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
def test_refusals_keep_their_status_and_message(client: TestClient, ascension: FakeAscension, status, message) -> None:
    as_admin(client)
    ascension.refuse = (status, message)

    response = client.post("/api/ascension/battles/b1/advance", json=ROUND, headers=KEY)

    assert (response.status_code, response.json()["detail"]) == (status, message)


def test_unavailable_is_502(client: TestClient, ascension: FakeAscension) -> None:
    as_admin(client)
    ascension.unavailable = True

    response = client.get("/api/ascension/profile")

    assert (response.status_code, response.json()["detail"]) == (502, UNAVAILABLE_MESSAGE)


# --- access ---------------------------------------------------------------------


def test_logged_out_is_401_before_anything_else(client: TestClient, ascension: FakeAscension) -> None:
    assert client.get("/api/ascension/catalog").status_code == 401
    # No key either: the login check comes first.
    assert client.post("/api/ascension/encounters", json={}).status_code == 401
    assert ascension.calls == []


def test_needs_ascension_play(client: TestClient, email: FakeEmailSender, ascension: FakeAscension) -> None:
    make_member(client, email)
    login(client, "alice")

    assert client.get("/api/ascension/profile").status_code == 403
    assert client.post("/api/ascension/encounters", json={}, headers=KEY).status_code == 403
    assert ascension.calls == []


def test_the_administrator_role_has_the_permission_and_member_does_not(client: TestClient) -> None:
    as_admin(client)

    assert "ascension.play" in role_by_name(client, "Administrator")["permissions"]
    assert "ascension.play" not in role_by_name(client, "Member")["permissions"]


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
def test_a_change_needs_an_idempotency_key(client: TestClient, ascension: FakeAscension, headers) -> None:
    as_admin(client)

    response = client.post("/api/ascension/battles/b1/advance", json=ROUND, headers=headers)

    assert response.status_code == 400
    assert "Idempotency-Key" in response.json()["detail"]
    assert ascension.calls == []


@pytest.mark.parametrize("key", ["k" * 200, "AZaz09_.:-", "9b2f6c1e-3d4a-4f5b-8c7d-1234567890ab"])
def test_a_valid_key_is_accepted(client: TestClient, ascension: FakeAscension, key) -> None:
    as_admin(client)

    response = client.post("/api/ascension/battles/b1/advance", json=ROUND, headers={"Idempotency-Key": key})

    assert response.status_code == 200
    assert ascension.calls[0]["key"] == key


@pytest.mark.parametrize(
    "query",
    ["limit=0", "limit=101", "limit=abc", "limit=1.5", "cursor=-1", "cursor=abc", "cursor=99999999999999999999"],
)
def test_bad_personality_paging_is_refused_and_never_forwarded(client: TestClient, ascension: FakeAscension, query) -> None:
    as_admin(client)

    response = client.get(f"/api/ascension/ascendeds/guardian/personalities?{query}")

    assert response.status_code in (400, 422), response.text
    assert ascension.calls == []


def test_only_limit_and_cursor_are_forwarded(client: TestClient, ascension: FakeAscension) -> None:
    as_admin(client)

    response = client.get("/api/ascension/ascendeds/guardian/personalities?limit=100&cursor=0&owner=bob&sort=x")

    assert response.status_code == 200
    assert ascension.calls[0]["params"] == {"limit": 100, "cursor": 0}


@pytest.mark.parametrize(
    ("path", "body", "word"),
    [
        ("/api/ascension/battles/b1/advance", {**ROUND, "hp": 999}, "hp"),
        ("/api/ascension/battles/b1/actions", {**ROUND, "action": {"kind": "attack", "damage": 50}}, "damage"),
        ("/api/ascension/battles", {**START, "rewards": 1}, "rewards"),
        ("/api/ascension/profile", {"starter_ascended_id": "guardian", "owner": "bob"}, "owner"),
        ("/api/ascension/battles/b1/advance", {"round": True, "revision": 2}, "round"),
        ("/api/ascension/battles/b1/actions", {**ROUND, "action": {"kind": "steal"}}, "kind"),
        ("/api/ascension/shop/purchases", {"kind": "copies", "tier": "rare"}, "ascended_id"),
        ("/api/ascension/shop/purchases", {"kind": "emblem", "tier": "common", "quantity": 100}, "quantity"),
        ("/api/ascension/battles", {**START, "ascended_id": "../profile"}, "ascended_id"),
    ],
)
def test_bad_bodies_are_400_and_never_forwarded(client: TestClient, ascension: FakeAscension, path, body, word) -> None:
    as_admin(client)

    response = client.post(path, json=body, headers=KEY)

    assert response.status_code == 400, response.text
    assert word in response.json()["detail"]
    assert ascension.calls == []


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/ascension/battles/bad.id"),
        ("GET", "/api/ascension/encounters/" + "x" * 65),
        ("GET", "/api/ascension/ascendeds/guardian/presets/9"),
        ("GET", "/api/ascension/ascendeds/guardian/presets/one"),
        ("POST", "/api/ascension/ascendeds/bad.ascended/sales"),
        ("POST", "/api/ascension/battles/bad.id/forfeit"),
    ],
)
def test_bad_ids_are_400(client: TestClient, ascension: FakeAscension, method, path) -> None:
    as_admin(client)

    response = client.request(method, path, json={} if method == "POST" else None, headers=KEY)

    assert response.status_code == 400, response.text
    assert ascension.calls == []


# --- audit ----------------------------------------------------------------------


def action_log(client: TestClient) -> list[dict[str, Any]]:
    response = client.get("/api/logs/action", params={"actor": str(my_id(client))})
    assert response.status_code == 200, response.text
    return [e for e in response.json() if e["source"].startswith("ascension.")]


def test_only_changes_of_value_are_audited(client: TestClient, ascension: FakeAscension) -> None:
    as_admin(client)
    ascension.responses[("POST", "/ascension/battles")] = {"id": "b1", "wild": {"name": "Bruiser", "level": 4}}
    ascension.responses[("POST", "/ascension/shop/purchases")] = {"kind": "emblems", "tier_id": "common", "quantity": 2, "price": 20}
    ascension.responses[("POST", "/ascension/ascendeds/guardian/sales")] = {"kind": "sale", "ascended_id": "guardian", "value": 12}

    for method, path, body, *_ in MUTATIONS:
        assert client.request(method, path, json=body, headers=KEY).status_code < 300
    for path, *_ in READS:
        assert client.get(path).status_code == 200

    entries = action_log(client)
    assert sorted(e["source"] for e in entries) == [
        "ascension.ascended_sell",
        "ascension.battle_forfeit",
        "ascension.battle_start",
        "ascension.profile_create",
        "ascension.profile_reset",
        "ascension.shop_buy",
        "ascension.shop_buy",
    ]
    messages = {e["message"] for e in entries}
    assert "Started Ascension with the starter 'guardian'" in messages
    assert "Started a battle against Bruiser (level 4)" in messages
    assert "Bought 2 common EMBLEMs for 20 Insignia" in messages
    assert "Sold a guardian copy for 12 Insignia" in messages


def test_a_refused_change_is_not_audited(client: TestClient, ascension: FakeAscension) -> None:
    as_admin(client)
    ascension.refuse = (409, "that costs 40 Insignia and you have 3")

    assert client.post("/api/ascension/shop/purchases", json={"kind": "emblem", "tier": "rare"}, headers=KEY).status_code == 409
    assert action_log(client) == []


# --- every route ----------------------------------------------------------------


def ascension_routes(client: TestClient) -> list[tuple[str, str]]:
    """(method, concrete path) for every route under /api/ascension; a new handler is picked up by itself."""
    found = []
    # The OpenAPI document lists every registered operation, however FastAPI nests its routers.
    for path, operations in client.app.openapi()["paths"].items():
        if not path.startswith("/api/ascension"):
            continue
        concrete = path.replace("{slot}", "1")
        concrete = re.sub(r"\{[a-z_]+\}", "abc", concrete)
        found.extend((method.upper(), concrete) for method in operations)
    return found


def test_the_route_walk_sees_the_whole_api(client: TestClient) -> None:
    assert len(ascension_routes(client)) == 19


def test_every_route_is_401_logged_out(client: TestClient, ascension: FakeAscension) -> None:
    for method, path in ascension_routes(client):
        response = client.request(method, path, json={}, headers=KEY)
        assert response.status_code == 401, (method, path)
    assert ascension.calls == []


def test_every_route_is_403_without_ascension_play(
    client: TestClient, email: FakeEmailSender, ascension: FakeAscension
) -> None:
    make_member(client, email)
    login(client, "alice")

    for method, path in ascension_routes(client):
        response = client.request(method, path, json={}, headers=KEY)
        assert response.status_code == 403, (method, path)
    assert ascension.calls == []


def test_every_change_without_a_key_is_400_and_never_forwarded(client: TestClient, ascension: FakeAscension) -> None:
    as_admin(client)
    changes = [(m, p) for m, p in ascension_routes(client) if m in ("POST", "PUT", "PATCH", "DELETE")]
    assert len(changes) == 13

    for method, path in changes:
        response = client.request(method, path, json={})
        assert response.status_code == 400, (method, path)
        assert "Idempotency-Key" in response.json()["detail"], (method, path)
    assert ascension.calls == []


def test_a_forfeit_is_audited_with_its_battle_id(client: TestClient, ascension: FakeAscension) -> None:
    as_admin(client)

    assert client.post("/api/ascension/battles/b_9-x/forfeit", json={}, headers=KEY).status_code == 200

    assert [e["message"] for e in action_log(client)] == ["Forfeited battle b_9-x"]


# --- reset ----------------------------------------------------------------------


def test_a_reset_sends_confirm_itself_and_is_audited_once(client: TestClient, ascension: FakeAscension) -> None:
    as_admin(client)
    ascension.responses[("POST", "/ascension/profile/reset")] = {"reset": True}

    response = client.post("/api/ascension/profile/reset", json={}, headers={"Idempotency-Key": "reset-1"})

    assert (response.status_code, response.json()) == (200, {"reset": True})
    assert ascension.calls == [
        {
            "method": "POST",
            "path": "/ascension/profile/reset",
            "owner": str(my_id(client)),
            "json": {"confirm": True},
            "params": None,
            "key": "reset-1",
        }
    ]
    assert [(e["source"], e["message"]) for e in action_log(client)] == [
        ("ascension.profile_reset", "Reset all Ascension progress")
    ]


def test_a_reset_ignores_a_body_from_the_browser(client: TestClient, ascension: FakeAscension) -> None:
    as_admin(client)

    response = client.post("/api/ascension/profile/reset", json={"confirm": False}, headers=KEY)

    assert response.status_code == 200
    assert ascension.calls[0]["json"] == {"confirm": True}


@pytest.mark.parametrize("headers", [{}, {"Idempotency-Key": "bad key!"}, {"Idempotency-Key": "x" * 201}])
def test_a_reset_needs_a_valid_key(client: TestClient, ascension: FakeAscension, headers) -> None:
    as_admin(client)

    assert client.post("/api/ascension/profile/reset", json={}, headers=headers).status_code == 400
    assert ascension.calls == []


@pytest.mark.parametrize(("status", "message"), [(404, "no profile yet"), (409, "finish or forfeit your battle first")])
def test_a_refused_reset_keeps_its_message_and_is_not_audited(
    client: TestClient, ascension: FakeAscension, status, message
) -> None:
    as_admin(client)
    ascension.refuse = (status, message)

    response = client.post("/api/ascension/profile/reset", json={}, headers=KEY)

    assert (response.status_code, response.json()["detail"]) == (status, message)
    assert action_log(client) == []


def test_an_unavailable_reset_is_502_and_not_audited(client: TestClient, ascension: FakeAscension) -> None:
    as_admin(client)
    ascension.unavailable = True

    response = client.post("/api/ascension/profile/reset", json={}, headers=KEY)

    assert (response.status_code, response.json()["detail"]) == (502, UNAVAILABLE_MESSAGE)
    assert action_log(client) == []
