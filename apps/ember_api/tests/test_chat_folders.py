from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from src.services import folder_service
from tests.conftest import FakeAgent, FakeEmailSender
from tests.test_admin import login, make_member
from tests.test_logs import messages, my_id
from tests.test_registration import as_admin
from tests.test_turns import events, start


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
    assert client.delete("/api/chat-folders/1").status_code == 401

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
    assert client.delete(f"/api/chat-folders/{folder_id}").status_code == 404
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


# --- moving and pinning chats ------------------------------------------------------


def listed(client: TestClient, chat_id: str) -> dict:
    return next(c for c in client.get("/api/chats").json() if c["id"] == chat_id)


def test_a_chat_can_be_moved_into_a_folder_and_out_again(client: TestClient) -> None:
    as_admin(client)
    chat_id = make_chat(client)
    folder_id = new_folder(client).json()["id"]

    moved = client.patch(f"/api/chats/{chat_id}", json={"folder_id": folder_id})

    assert moved.status_code == 200
    assert moved.json()["folder_id"] == folder_id
    assert listed(client, chat_id)["folder_id"] == folder_id
    assert folders(client)[0]["chat_count"] == 1

    out = client.patch(f"/api/chats/{chat_id}", json={"folder_id": None})

    assert out.json()["folder_id"] is None
    assert folders(client)[0]["chat_count"] == 0


def test_pinning_keeps_the_folder(client: TestClient) -> None:
    as_admin(client)
    chat_id = make_chat(client)
    folder_id = new_folder(client).json()["id"]
    client.patch(f"/api/chats/{chat_id}", json={"folder_id": folder_id})

    pinned = client.patch(f"/api/chats/{chat_id}", json={"pinned": True}).json()

    assert (pinned["pinned"], pinned["folder_id"]) == (True, folder_id)
    assert client.patch(f"/api/chats/{chat_id}", json={"pinned": False}).json()["pinned"] is False
    assert listed(client, chat_id)["folder_id"] == folder_id


def test_moving_or_pinning_does_not_change_the_order(client: TestClient) -> None:
    as_admin(client)
    chat_id = make_chat(client)
    before = listed(client, chat_id)["updated_at"]
    folder_id = new_folder(client).json()["id"]

    client.patch(f"/api/chats/{chat_id}", json={"folder_id": folder_id, "pinned": True})

    assert listed(client, chat_id)["updated_at"] == before


def test_a_rename_still_works_and_can_be_combined(client: TestClient) -> None:
    as_admin(client)
    chat_id = make_chat(client)
    folder_id = new_folder(client).json()["id"]

    body = client.patch(f"/api/chats/{chat_id}", json={"title": "  New   title ", "folder_id": folder_id}).json()

    assert (body["title"], body["folder_id"]) == ("New title", folder_id)


def test_an_empty_or_blank_patch_is_refused(client: TestClient) -> None:
    as_admin(client)
    chat_id = make_chat(client)

    assert client.patch(f"/api/chats/{chat_id}", json={}).status_code == 422
    assert client.patch(f"/api/chats/{chat_id}", json={"title": None}).status_code == 422
    assert client.patch(f"/api/chats/{chat_id}", json={"title": "   "}).status_code == 422


def test_moving_into_someone_elses_or_a_missing_folder_is_404(client: TestClient, email: FakeEmailSender) -> None:
    as_admin(client)
    foreign = new_folder(client, "Admin only").json()["id"]
    client.post("/api/auth/logout", json={})
    make_member(client, email)
    login(client, "alice")
    chat_id = make_chat(client)

    assert client.patch(f"/api/chats/{chat_id}", json={"folder_id": foreign}).status_code == 404
    assert client.patch(f"/api/chats/{chat_id}", json={"folder_id": 99999}).status_code == 404
    assert listed(client, chat_id)["folder_id"] is None


def test_a_branch_stays_in_the_source_folder_and_is_not_pinned(client: TestClient) -> None:
    as_admin(client)
    chat_id = make_chat(client)
    folder_id = new_folder(client).json()["id"]
    client.patch(f"/api/chats/{chat_id}", json={"folder_id": folder_id, "pinned": True})

    branch = client.post(f"/api/chats/{chat_id}/branch", json={"upto": 1})

    assert branch.status_code == 201, branch.text
    assert (branch.json()["folder_id"], branch.json()["pinned"]) == (folder_id, False)


# --- deleting a folder -------------------------------------------------------------


def put_in(client: TestClient, folder_id: int, count: int) -> list[str]:
    ids = [make_chat(client, f"chat {i}") for i in range(count)]
    for chat_id in ids:
        assert client.patch(f"/api/chats/{chat_id}", json={"folder_id": folder_id}).status_code == 200
    return ids


def test_deleting_a_folder_deletes_its_chats_and_their_shares(client: TestClient) -> None:
    as_admin(client)
    keep = make_chat(client, "unfiled")
    other = new_folder(client, "Other").json()["id"]
    (kept_elsewhere,) = put_in(client, other, 1)
    doomed = new_folder(client, "Doomed").json()["id"]
    first, second = put_in(client, doomed, 2)
    token = client.post(f"/api/chats/{first}/shares", json={}).json()["token"]
    assert client.get(f"/api/shared/{token}").status_code == 200

    response = client.delete(f"/api/chat-folders/{doomed}")

    assert response.status_code == 204
    assert [f["name"] for f in folders(client)] == ["Other"]
    remaining = {c["id"] for c in client.get("/api/chats").json()}
    assert remaining == {keep, kept_elsewhere}
    assert client.get(f"/api/chats/{second}").status_code == 404
    assert client.get(f"/api/shared/{token}").status_code == 404  # the link died with the chat


def test_deleting_an_empty_folder(client: TestClient) -> None:
    as_admin(client)
    folder_id = new_folder(client).json()["id"]

    assert client.delete(f"/api/chat-folders/{folder_id}").status_code == 204
    assert folders(client) == []
    assert client.delete(f"/api/chat-folders/{folder_id}").status_code == 404


def test_a_folder_with_an_answering_chat_cannot_be_deleted(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    folder_id = new_folder(client).json()["id"]
    (chat_id,) = put_in(client, folder_id, 1)
    agent.hold = True
    assert start(client, chat_id, "q3").status_code == 202

    try:
        response = client.delete(f"/api/chat-folders/{folder_id}")
        assert response.status_code == 409
        assert "answer" in response.json()["detail"]
        assert len(folders(client)) == 1  # nothing was deleted
        assert client.get(f"/api/chats/{chat_id}").status_code == 200
    finally:
        agent.release()
    events(client, chat_id)

    assert client.delete(f"/api/chat-folders/{folder_id}").status_code == 204
    assert client.get(f"/api/chats/{chat_id}").status_code == 404


def test_deleting_a_folder_writes_an_audit_entry(client: TestClient) -> None:
    as_admin(client)
    folder_id = new_folder(client, "Audit me").json()["id"]
    put_in(client, folder_id, 2)

    client.delete(f"/api/chat-folders/{folder_id}")

    assert 'Deleted folder "Audit me" and its 2 chat(s)' in messages(client, "action", my_id(client))
