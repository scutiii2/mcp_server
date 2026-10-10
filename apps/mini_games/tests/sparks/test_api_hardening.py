import dataclasses
import json

import pytest

import src.run as run_module
from src.laya_client import LayaClient
from tests.sparks.test_api import TOKEN, client, clock, headers, open_battle, start_profile  # noqa: F401 (fixtures)

PERSONALITY_IDS = ("AGGRESSIVE", "DEFENSIVE", "SUPPORTIVE", "COWARD", "TENACIOUS", "BOLD", "CAUTIOUS", "DISCIPLINED")
FORBIDDEN_WORDS = ("seed", "draw", "counter", "pending", "probabilit")


def test_an_oversized_or_negative_cursor_is_a_400_not_a_500(client):
    start_profile(client)
    for cursor in (2**63, 2**80, -1):
        response = client.get(f"/sparks/sparks/guardian/personalities?cursor={cursor}", headers=headers())
        assert response.status_code == 400 and "error" in response.json()
    assert client.get(f"/sparks/sparks/guardian/personalities?cursor={2**63 - 1}", headers=headers()).status_code == 200


def test_unknown_routes_and_wrong_methods_use_the_error_shape(client):
    missing = client.get("/sparks/nope", headers=headers())
    wrong = client.delete("/sparks/profile", headers=headers())
    assert missing.status_code == 404 and set(missing.json()) == {"error"}
    assert wrong.status_code == 405 and set(wrong.json()) == {"error"} and "allow" in wrong.headers
    denied = client.get("/sparks/nope", headers={})
    assert denied.status_code == 401 and set(denied.json()) == {"error"}


def _assert_clean(text: str, words=FORBIDDEN_WORDS) -> None:
    lowered = text.lower()
    for word in words:
        assert word not in lowered, word
    for name in PERSONALITY_IDS:
        assert name not in text, name


def test_battle_views_and_results_hide_hidden_state(client):
    view = open_battle(client)
    _assert_clean(json.dumps(view))
    fetched = client.get(f"/sparks/battles/{view['id']}", headers=headers())
    _assert_clean(fetched.text)
    played = client.post(f"/sparks/battles/{view['id']}/actions", headers=headers(),
                         json={"round": 1, "revision": 1, "action": {"kind": "attack"}})
    assert played.status_code == 200
    _assert_clean(played.text)
    if played.json()["status"] == "active":
        done = client.post(f"/sparks/battles/{view['id']}/forfeit", headers=headers())
        assert done.status_code == 200 and done.json()["result"]["kind"] == "forfeited"
        _assert_clean(done.text)  # no capture, so no wild personalities in the result


def test_encounter_responses_hide_wild_personalities(client):
    start_profile(client)
    rolled = client.post("/sparks/encounters", headers=headers())
    # An encounter's own status is legitimately "pending", so only the hidden state is checked here.
    _assert_clean(rolled.text, ("seed", "draw", "counter", "probabilit"))
    _assert_clean(client.get(f"/sparks/encounters/{rolled.json()['id']}", headers=headers()).text, ("seed", "draw", "counter", "probabilit"))


def test_a_laya_load_failure_degrades_to_heuristics(config, tmp_path, monkeypatch):
    class BrokenLaya(LayaClient):
        def is_available(self) -> bool:
            return True

        def prepare(self) -> None:
            raise OSError("weights missing")

    monkeypatch.setattr(run_module, "load_config", lambda: dataclasses.replace(config, database_path=tmp_path / "r.sqlite3"))
    monkeypatch.setattr(run_module, "load_token", lambda: TOKEN)
    monkeypatch.setattr(run_module, "LayaClient", BrokenLaya)
    app, loaded = run_module.build_app()
    assert app is not None and loaded.port == config.port
