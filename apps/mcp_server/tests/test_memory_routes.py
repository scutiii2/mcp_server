"""DELETE /memory/owners/{uid}: the route ember_api calls when an account is deleted."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from src import memory_routes
from src.memory_routes import install_memory_routes
from src.services import memory_store

TOKEN = "shared-secret"
UID_A = "a" * 32
UID_B = "b" * 32


@pytest.fixture
def db(tmp_path):
    return tmp_path / "memory.db"


@pytest.fixture
def fake_settings(monkeypatch, db):
    fake = SimpleNamespace(internal_api_token=TOKEN, memory_db_path=db)
    monkeypatch.setattr(memory_routes, "settings", fake)
    return fake


@pytest.fixture
def online(monkeypatch):
    state = {"on": True}
    monkeypatch.setattr(memory_routes, "_memory_online", lambda: state["on"])
    return state


@pytest.fixture
def client(fake_settings, online):
    app = Starlette()
    install_memory_routes(app)
    with TestClient(app) as test_client:
        yield test_client


def purge(client, uid=UID_A, token=TOKEN):
    headers = {"X-Internal-Token": token} if token is not None else {}
    return client.delete(f"/memory/owners/{uid}", headers=headers)


def test_it_removes_only_that_owners_notes(client, db, caplog):
    memory_store.save(db, UID_A, "alpha")
    memory_store.save(db, UID_B, "beta")

    caplog.set_level(logging.INFO, logger="uvicorn.access")
    response = purge(client)
    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d', "127.0.0.1", "DELETE", f"/memory/owners/{UID_A}", "1.1", 200
    )
    assert UID_A not in caplog.text
    assert "/memory/owners/[redacted]" in caplog.text

    assert response.status_code == 200 and response.json() == {"purged": 1}
    assert memory_store.search(db, UID_A) == []
    assert len(memory_store.search(db, UID_B)) == 1


def test_an_owner_with_no_notes_purges_zero(client):
    assert purge(client).json() == {"purged": 0}


@pytest.mark.parametrize("token", [None, "wrong"])
def test_a_missing_or_wrong_token_is_a_401_and_deletes_nothing(client, db, token):
    memory_store.save(db, UID_A, "alpha")
    assert purge(client, token=token).status_code == 401
    assert len(memory_store.search(db, UID_A)) == 1


def test_an_unset_token_never_validates(client, fake_settings, db):
    fake_settings.internal_api_token = ""
    memory_store.save(db, UID_A, "alpha")
    assert purge(client, token="").status_code == 401
    assert len(memory_store.search(db, UID_A)) == 1


@pytest.mark.parametrize("uid", ["alice", "A" * 32, "a" * 31, "a" * 33, "..%2F"])
def test_only_a_32_hex_uid_is_accepted(client, uid):
    assert purge(client, uid=uid).status_code in (400, 404)


def test_it_does_nothing_when_memory_is_offline(client, online, db):
    memory_store.save(db, UID_A, "alpha")
    online["on"] = False
    assert purge(client).status_code == 404
    assert len(memory_store.search(db, UID_A)) == 1


def test_only_delete_is_allowed(client):
    assert client.get(f"/memory/owners/{UID_A}", headers={"X-Internal-Token": TOKEN}).status_code == 405
