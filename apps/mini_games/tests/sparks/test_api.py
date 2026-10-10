import dataclasses
import itertools

import pytest
from fastapi.testclient import TestClient

from src.app import create_app
from src.laya_client import LayaClient
from src.sparks.api import mount_sparks
from src.sparks.composition import build_spark_services
from src.sparks.runtime import SeededRandom
from tests.fake_laya import FakeEngine
from tests.sparks.helpers import FixedClock

TOKEN = "t0ken"
_KEYS = itertools.count(1)


def headers(owner="ann", key=True, token=TOKEN):
    result = {"X-Internal-Token": token} if token else {}
    if owner:
        result["X-Requester-Username"] = owner
    if key is True:
        result["Idempotency-Key"] = f"k{next(_KEYS)}"
    elif key:
        result["Idempotency-Key"] = key
    return result


@pytest.fixture
def clock():
    return FixedClock()


@pytest.fixture
def client(config, tmp_path, clock):
    config = dataclasses.replace(config, database_path=tmp_path / "api.sqlite3")
    app = create_app(TOKEN)
    services = build_spark_services(config, LayaClient(FakeEngine(fail=True)), clock=clock, rng=SeededRandom(5))
    mount_sparks(app, services)
    with TestClient(app) as test_client:
        yield test_client


def start_profile(client, owner="ann", starter="guardian"):
    response = client.post("/sparks/profile", json={"starter_spark_id": starter}, headers=headers(owner))
    assert response.status_code == 201, response.text
    return response.json()


# -- access --------------------------------------------------------------------------

def test_health_needs_no_token(client):
    assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize("h", [{}, {"X-Requester-Username": "ann"}, {"X-Internal-Token": "wrong", "X-Requester-Username": "ann"}])
def test_the_internal_token_is_required(client, h):
    assert client.get("/sparks/profile", headers=h).status_code == 401


def test_the_requester_header_is_required(client):
    response = client.get("/sparks/profile", headers=headers(owner=None))
    assert response.status_code == 400 and "X-Requester-Username" in response.json()["error"]


def test_mutations_need_an_idempotency_key(client):
    response = client.post("/sparks/profile", json={"starter_spark_id": "guardian"}, headers=headers(key=False))
    assert response.status_code == 400 and "Idempotency-Key" in response.json()["error"]


def test_the_catalog_is_readable_and_complete(client):
    data = client.get("/sparks/catalog", headers=headers(owner="anyone")).json()
    assert len(data["sparks"]) == 7 and [t["id"] for t in data["tiers"]][-1] == "forbidden"
    assert {s["id"] for s in data["sparks"] if s["starter"]} == {"guardian", "striker", "scout"}
    assert len(data["personalities"]) == 8


# -- profile, personalities, presets -------------------------------------------------

def test_profile_creation_is_once_and_idempotent(client):
    first = client.post("/sparks/profile", json={"starter_spark_id": "scout"}, headers=headers(key="same"))
    again = client.post("/sparks/profile", json={"starter_spark_id": "scout"}, headers=headers(key="same"))
    other = client.post("/sparks/profile", json={"starter_spark_id": "scout"}, headers=headers())
    clash = client.post("/sparks/profile", json={"starter_spark_id": "striker"}, headers=headers(key="same"))
    assert first.status_code == again.status_code == 201 and first.json() == again.json()
    assert other.status_code == 409 and clash.status_code == 409
    profile = client.get("/sparks/profile", headers=headers()).json()
    assert profile["emblems"] == {"normal": 5} and profile["insignia"] == 0 and profile["sparks"][0]["spark_id"] == "scout"


def test_a_bad_starter_and_unknown_fields_are_400(client):
    assert client.post("/sparks/profile", json={"starter_spark_id": "forbidden"}, headers=headers()).status_code == 400
    assert client.post("/sparks/profile", json={"starter_spark_id": "guardian", "insignia": 9999}, headers=headers()).status_code == 400
    assert client.post("/sparks/profile", json={}, headers=headers()).status_code == 400


def test_profiles_are_private_to_their_owner(client):
    start_profile(client, "ann")
    assert client.get("/sparks/profile", headers=headers("bob")).status_code == 404
    assert client.get("/sparks/sparks/guardian/personalities", headers=headers("bob")).status_code == 404


def test_personalities_and_presets_over_http(client):
    start_profile(client)
    pool = client.get("/sparks/sparks/guardian/personalities", headers=headers()).json()
    ids = [p["id"] for p in pool["items"]]
    assert len(ids) == 1 and pool["next_cursor"] is None
    put = client.put("/sparks/sparks/guardian/presets/2", json={"instance_ids": ids}, headers=headers())
    assert put.status_code == 200 and client.get("/sparks/sparks/guardian/presets/2", headers=headers()).json()["instance_ids"] == ids
    assert client.put("/sparks/sparks/guardian/presets/2", json={"instance_ids": ["nope"]}, headers=headers()).status_code == 400
    assert client.put("/sparks/sparks/guardian/presets/9", json={"instance_ids": []}, headers=headers()).status_code == 400
    assert client.get("/sparks/sparks/guardian/personalities?limit=500", headers=headers()).status_code == 400


# -- encounters ----------------------------------------------------------------------

def test_encounter_rolls_respect_the_cooldown(client, clock):
    start_profile(client)
    first = client.post("/sparks/encounters", headers=headers())
    early = client.post("/sparks/encounters", headers=headers())
    assert first.status_code == 201 and "personalities" not in first.text
    assert early.status_code == 409 and early.json()["retry_after"] == pytest.approx(30)
    clock.advance(31)
    assert client.post("/sparks/encounters", headers=headers()).status_code == 201


def test_decline_over_http(client):
    start_profile(client)
    encounter = client.post("/sparks/encounters", headers=headers()).json()
    assert client.post(f"/sparks/encounters/{encounter['id']}/decline", headers=headers()).json()["status"] == "declined"
    assert client.get(f"/sparks/encounters/{encounter['id']}", headers=headers("bob")).status_code == 404


# -- battles -------------------------------------------------------------------------

def open_battle(client, mode="manual", **extra):
    start_profile(client)
    encounter = client.post("/sparks/encounters", headers=headers()).json()
    body = {"encounter_id": encounter["id"], "spark_id": "guardian", "preset_slot": 1, "mode": mode, **extra}
    response = client.post("/sparks/battles", json=body, headers=headers())
    assert response.status_code == 201, response.text
    return response.json()


def test_a_battle_can_be_started_played_and_forfeited(client):
    view = open_battle(client)
    assert view["phase"] == "choosing" and any(a["kind"] == "attack" for a in view["actions"])
    action = {"round": view["round"], "revision": view["revision"], "action": {"kind": "attack"}}
    after = client.post(f"/sparks/battles/{view['id']}/actions", json=action, headers=headers())
    assert after.status_code == 200 and after.json()["revision"] == 2 and len(after.json()["history"]) == 1
    if after.json()["status"] == "active":
        done = client.post(f"/sparks/battles/{view['id']}/forfeit", headers=headers()).json()
        assert done["status"] == "terminal" and done["result"]["kind"] == "forfeited"
        assert client.post(f"/sparks/battles/{view['id']}/forfeit", headers=headers()).status_code == 409


def test_a_stale_action_is_a_409_and_a_retry_is_not_repeated(client):
    view = open_battle(client)
    body = {"round": 1, "revision": 1, "action": {"kind": "attack"}}
    first = client.post(f"/sparks/battles/{view['id']}/actions", json=body, headers=headers(key="once"))
    retry = client.post(f"/sparks/battles/{view['id']}/actions", json=body, headers=headers(key="once"))
    stale = client.post(f"/sparks/battles/{view['id']}/actions", json=body, headers=headers())
    assert first.status_code == retry.status_code == 200 and first.json() == retry.json()
    assert stale.status_code == 409


def test_clients_cannot_send_rewards_or_chances(client):
    view = open_battle(client)
    cheat = {"round": 1, "revision": 1, "action": {"kind": "attack", "damage": 9999}}
    assert client.post(f"/sparks/battles/{view['id']}/actions", json=cheat, headers=headers()).status_code == 400
    cheat = {"round": 1, "revision": 1, "action": {"kind": "attack"}, "xp": 5000}
    assert client.post(f"/sparks/battles/{view['id']}/actions", json=cheat, headers=headers()).status_code == 400


def test_illegal_actions_and_wrong_modes(client):
    view = open_battle(client)
    nope = {"round": 1, "revision": 1, "action": {"kind": "ability", "ability_id": "unknown"}}
    assert client.post(f"/sparks/battles/{view['id']}/actions", json=nope, headers=headers()).status_code == 400
    advance = client.post(f"/sparks/battles/{view['id']}/advance", json={"round": 1, "revision": 1}, headers=headers())
    assert advance.status_code == 409  # manual battles wait for the player


def test_autonomous_advance_and_mode_switch(client):
    view = open_battle(client, mode="autonomous", emblem_limit="normal")
    played = client.post(f"/sparks/battles/{view['id']}/advance", json={"round": 1, "revision": 1}, headers=headers())
    assert played.status_code == 200
    data = played.json()
    if data["phase"] == "awaiting_emblem":  # the Spark chose CATCH: the player has five seconds to pick an EMBLEM
        assert data["history"] == [] and data["prompt"]["seconds_left"] == 5.0
        body = {"round": data["round"], "revision": data["revision"], "mode": "manual"}
        assert client.post(f"/sparks/battles/{view['id']}/mode", json=body, headers=headers()).status_code == 409
        return
    assert len(data["history"]) == 1
    if data["status"] == "active":
        body = {"round": data["round"], "revision": data["revision"], "mode": "manual"}
        assert client.post(f"/sparks/battles/{view['id']}/mode", json=body, headers=headers()).json()["mode"] == "manual"


def test_battles_are_private_to_their_owner(client):
    view = open_battle(client)
    start_profile(client, "bob")
    assert client.get(f"/sparks/battles/{view['id']}", headers=headers("bob")).status_code == 404
    assert client.post(f"/sparks/battles/{view['id']}/forfeit", headers=headers("bob")).status_code == 404
    assert client.get("/sparks/battles/missing", headers=headers()).status_code == 404


def test_a_second_battle_is_refused_while_one_is_active(client):
    open_battle(client)
    assert client.post("/sparks/encounters", headers=headers()).status_code == 409


# -- shop ----------------------------------------------------------------------------

def test_shop_over_http(client):
    start_profile(client)
    poor = client.post("/sparks/shop/purchases", json={"kind": "emblem", "tier": "rare", "quantity": 1}, headers=headers())
    assert poor.status_code == 409
    assert client.post("/sparks/shop/purchases", json={"kind": "copies", "spark_id": "sentinel", "tier": "normal"}, headers=headers()).status_code == 409
    assert client.post("/sparks/shop/purchases", json={"kind": "stock", "tier": "rare"}, headers=headers()).status_code == 400
    assert client.post("/sparks/shop/purchases", json={"kind": "emblem", "tier": "gold", "quantity": 1}, headers=headers()).status_code == 400
    assert client.post("/sparks/sparks/guardian/sales", headers=headers()).status_code == 409  # nothing to sell
    assert client.post("/sparks/sparks/dragon/sales", headers=headers()).status_code == 400
