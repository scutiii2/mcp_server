from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from src.services import folder_service
from tests.conftest import FakeEmailSender
from tests.test_admin import login, make_member
from tests.test_registration import as_admin


def make_chat(client: TestClient, title: str = "A chat") -> str:
    chat_id = str(uuid.uuid4())
    response = client.put(
        f"/api/chats/{chat_id}",
        json={
            "title": title,
            "agent_id": None,
            "messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}],
        },
    )
    assert response.status_code == 200, response.text
    return chat_id


def test_a_new_chat_is_unfiled_and_not_pinned(client: TestClient) -> None:
    as_admin(client)
    chat_id = make_chat(client)

    row = next(c for c in client.get("/api/chats").json() if c["id"] == chat_id)

    assert row["folder_id"] is None
    assert row["pinned"] is False
    full = client.get(f"/api/chats/{chat_id}").json()
    assert (full["folder_id"], full["pinned"]) == (None, False)


def new_folder(client: TestClient, name: str = "Work"):
    return client.post("/api/chat-folders", json={"name": name})


def folders(client: TestClient) -> list[dict]:
    response = client.get("/api/chat-folders")
    assert response.status_code == 200, response.text
    return response.json()


# --- access --------------------------------------------------------------------


def test_folders_need_login_and_chat_use(client: TestClient, email: FakeEmailSender) -> None:
    assert client.get("/api/chat-folders").status_code == 401
    assert new_folder(client).status_code == 401
    assert client.patch("/api/chat-folders/1", json={"name": "x"}).status_code == 401

    make_member(client, email, verify=False)
    login(client, "alice")
    assert client.get("/api/chat-folders").status_code == 403  # unverified: no permissions


# --- create and list -------------------------------------------------------------


def test_create_and_list(client: TestClient) -> None:
    as_admin(client)

    response = new_folder(client, "  Work   stuff ")

    assert response.status_code == 201
    assert response.json()["name"] == "Work stuff"  # trimmed, spaces collapsed
    assert response.json()["chat_count"] == 0
    new_folder(client, "Home")
    assert [f["name"] for f in folders(client)] == ["Work stuff", "Home"]  # creation order


@pytest.mark.parametrize("name", ["", "   ", "x" * 61])
def test_bad_names_are_refused(client: TestClient, name: str) -> None:
    as_admin(client)

    assert new_folder(client, name).status_code == 422


def test_a_duplicate_name_is_refused_ignoring_case(client: TestClient) -> None:
    as_admin(client)
    assert new_folder(client, "Work").status_code == 201

    assert new_folder(client, "work").status_code == 409
    assert len(folders(client)) == 1


def test_the_folder_limit(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(folder_service, "MAX_FOLDERS_PER_ACCOUNT", 2)
    as_admin(client)
    assert new_folder(client, "a").status_code == 201
    assert new_folder(client, "b").status_code == 201

    response = new_folder(client, "c")

    assert response.status_code == 409
    assert "2" in response.json()["detail"]


def test_folders_are_private_to_their_account(client: TestClient, email: FakeEmailSender) -> None:
    as_admin(client)
    folder_id = new_folder(client, "Secret").json()["id"]
    client.post("/api/auth/logout", json={})
    make_member(client, email)
    login(client, "alice")

    assert folders(client) == []
    assert client.patch(f"/api/chat-folders/{folder_id}", json={"name": "Mine"}).status_code == 404
    assert new_folder(client, "Secret").status_code == 201  # same name is fine for another account


# --- rename and reorder ----------------------------------------------------------


def test_rename(client: TestClient) -> None:
    as_admin(client)
    folder_id = new_folder(client, "Work").json()["id"]
    new_folder(client, "Home")

    response = client.patch(f"/api/chat-folders/{folder_id}", json={"name": "Office"})

    assert response.status_code == 200
    assert response.json()["name"] == "Office"
    assert client.patch(f"/api/chat-folders/{folder_id}", json={"name": "home"}).status_code == 409


def test_renaming_to_its_own_name_with_other_case_is_allowed(client: TestClient) -> None:
    as_admin(client)
    folder_id = new_folder(client, "work").json()["id"]

    assert client.patch(f"/api/chat-folders/{folder_id}", json={"name": "Work"}).json()["name"] == "Work"


def test_reorder_moves_a_folder(client: TestClient) -> None:
    as_admin(client)
    first = new_folder(client, "a").json()["id"]
    new_folder(client, "b")
    new_folder(client, "c")

    assert client.patch(f"/api/chat-folders/{first}", json={"position": 10}).status_code == 200

    assert [f["name"] for f in folders(client)] == ["b", "c", "a"]


def test_a_patch_must_change_something(client: TestClient) -> None:
    as_admin(client)
    folder_id = new_folder(client).json()["id"]

    assert client.patch(f"/api/chat-folders/{folder_id}", json={}).status_code == 422
    assert client.patch(f"/api/chat-folders/{folder_id}", json={"position": -1}).status_code == 422
