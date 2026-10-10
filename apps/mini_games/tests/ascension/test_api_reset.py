import pytest

from tests.ascension.test_api import TOKEN, client, clock, headers, open_battle, start_profile  # noqa: F401 (fixtures)


def reset(client, body=None, **kwargs):
    return client.post("/ascension/profile/reset", json={"confirm": True} if body is None else body, headers=headers(**kwargs))


def test_reset_deletes_the_profile_and_a_new_one_can_start(client):
    start_profile(client)
    client.post("/ascension/encounters", headers=headers())
    response = reset(client)
    assert response.status_code == 200 and response.json() == {"reset": True}
    assert client.get("/ascension/profile", headers=headers()).status_code == 404
    assert start_profile(client, starter="scout")["ascendeds"][0]["ascended_id"] == "scout"


def test_reset_does_not_touch_another_player(client):
    start_profile(client, "ann")
    start_profile(client, "bob")
    assert reset(client, owner="ann").status_code == 200
    assert client.get("/ascension/profile", headers=headers("bob")).status_code == 200


def test_reset_without_a_profile_is_404(client):
    assert reset(client).status_code == 404


def test_reset_during_a_battle_is_409_and_keeps_everything(client):
    open_battle(client)
    response = reset(client)
    assert response.status_code == 409 and "forfeit" in response.json()["error"]
    assert client.get("/ascension/profile", headers=headers()).json()["active_battle"] is not None


def test_a_retry_returns_the_same_response(client):
    start_profile(client)
    first = reset(client, key="same")
    again = reset(client, key="same")
    assert (first.status_code, again.status_code) == (200, 200) and first.json() == again.json() == {"reset": True}


@pytest.mark.parametrize("body", [{}, {"confirm": False}, {"confirm": "true"}, {"confirm": 1}, {"confirm": True, "extra": 1}])
def test_a_missing_false_or_unknown_confirmation_is_400_and_deletes_nothing(client, body):
    start_profile(client)
    response = reset(client, body)
    assert response.status_code == 400 and "error" in response.json()
    assert client.get("/ascension/profile", headers=headers()).status_code == 200


def test_reset_needs_an_idempotency_key(client):
    start_profile(client)
    response = reset(client, key=False)
    assert response.status_code == 400 and "Idempotency-Key" in response.json()["error"]
    assert client.get("/ascension/profile", headers=headers()).status_code == 200
