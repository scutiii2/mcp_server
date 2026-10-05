from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

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
