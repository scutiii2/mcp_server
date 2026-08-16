# Chat History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist chat conversations server-side per user, let the user browse/rename/delete/return to past chats, and drive "which chat is open" from the URL's `?id=` query parameter (no id = new chat).

**Architecture:** A new `chats/store.py` module (plain `sqlite3`, no ORM, mirrors `auth/store.py`'s exact conventions) persists one row per chat with the whole message transcript as a JSON blob. `pages/chat/routes.py` gains CRUD-ish endpoints (`GET/PATCH/DELETE /api/chats[/​<id>]`) and `POST /api/chat` starts saving every turn, returning the chat's id so the frontend can push it into the URL. `script.js` reads `?id=` on load to hydrate a past conversation from the server (replacing the old `sessionStorage`-based resume), and a new sidebar panel (gated to the chat page) lists/renames/deletes chats.

**Tech Stack:** Flask, stdlib `sqlite3`, vanilla JS (no framework), pytest.

**Spec:** [docs/superpowers/specs/2026-08-16-chat-history-design.md](../specs/2026-08-16-chat-history-design.md)

## Global Constraints

- Persistence layer: plain stdlib `sqlite3`, no ORM — mirror `chat_app/src/chat_app/auth/store.py`'s `_connect(db_path)` pattern (create-table-if-missing, one open/close per public call, `conn.commit()` after writes).
- A chat row is scoped by `username` (a string, not a numeric id — there is no user-id concept in this codebase, see `auth/service.py`'s session-cookie-keyed-by-username design). Every store function takes `username` and filters `WHERE ... AND username = ?`. A chat that doesn't exist and a chat owned by someone else must be indistinguishable to the caller.
- A chat stores only its message transcript (`{role, content}` pairs) — no per-chat provider/model/extensions memory (see spec's "Scope cut" section). Provider/model/extensions stay global UI state, unaffected by this change.
- TDD throughout: write the failing test, run it and confirm the failure reason, write minimal code to pass, run again, commit.
- Test runner (Windows, this repo): from the `chat_app/` directory, `./venv_chat/Scripts/python.exe -m pytest <path> -v`.
- No browser-based verification by the implementing agent — the project owner tests the UI manually. Frontend tasks below still specify testable server-side contracts (the API), but don't spawn a browser-verification step.

---

## Task 1: Chat persistence store

**Files:**
- Create: `chat_app/src/chat_app/chats/__init__.py`
- Create: `chat_app/src/chat_app/chats/store.py`
- Test: `chat_app/tests/test_chats_store.py`

**Interfaces:**
- Produces (used by Task 2):
  - `class UnknownChat(Exception)`
  - `save_chat(db_path: Path, username: str, chat_id: str | None, messages: list[dict]) -> str`
  - `list_chats(db_path: Path, username: str) -> list[dict]` — each dict: `{"id": str, "title": str, "updated_at": str}`
  - `get_chat(db_path: Path, username: str, chat_id: str) -> dict | None` — dict: `{"id": str, "title": str, "messages": list[dict], "created_at": str, "updated_at": str}`
  - `rename_chat(db_path: Path, username: str, chat_id: str, title: str) -> None` — raises `ValueError` on blank title, `UnknownChat` if not found/owned
  - `delete_chat(db_path: Path, username: str, chat_id: str) -> None` — raises `UnknownChat` if not found/owned

- [ ] **Step 1: Write the failing tests**

Create `chat_app/tests/test_chats_store.py`:

```python
"""Tests for the per-user chat-history SQLite store."""

from __future__ import annotations

import pytest

from chat_app.chats import store


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "chats.db"


# --- save_chat: creating -------------------------------------------------


def test_save_chat_without_id_creates_a_new_chat_and_returns_its_id(db_path):
    chat_id = store.save_chat(
        db_path, "alice", None, [{"role": "user", "content": "hello"}]
    )

    assert isinstance(chat_id, str) and chat_id
    chat = store.get_chat(db_path, "alice", chat_id)
    assert chat["messages"] == [{"role": "user", "content": "hello"}]


def test_save_chat_derives_title_from_first_user_message(db_path):
    chat_id = store.save_chat(
        db_path,
        "alice",
        None,
        [{"role": "user", "content": "how do I reset a password?"}],
    )

    chat = store.get_chat(db_path, "alice", chat_id)
    assert chat["title"] == "how do I reset a password?"


def test_save_chat_truncates_a_long_first_message_for_the_title(db_path):
    long_message = "x" * 80
    chat_id = store.save_chat(db_path, "alice", None, [{"role": "user", "content": long_message}])

    chat = store.get_chat(db_path, "alice", chat_id)
    assert chat["title"] == "x" * 57 + "..."


def test_save_chat_falls_back_to_new_chat_title_when_no_user_message(db_path):
    chat_id = store.save_chat(db_path, "alice", None, [{"role": "assistant", "content": "hi"}])

    chat = store.get_chat(db_path, "alice", chat_id)
    assert chat["title"] == "New chat"


# --- save_chat: updating --------------------------------------------------


def test_save_chat_with_id_overwrites_messages_and_keeps_the_id(db_path):
    chat_id = store.save_chat(db_path, "alice", None, [{"role": "user", "content": "first"}])

    returned_id = store.save_chat(
        db_path,
        "alice",
        chat_id,
        [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
        ],
    )

    assert returned_id == chat_id
    chat = store.get_chat(db_path, "alice", chat_id)
    assert chat["messages"] == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply"},
    ]


def test_save_chat_with_unknown_id_raises_unknown_chat(db_path):
    with pytest.raises(store.UnknownChat):
        store.save_chat(db_path, "alice", "does-not-exist", [{"role": "user", "content": "hi"}])


def test_save_chat_with_id_owned_by_another_user_raises_unknown_chat(db_path):
    chat_id = store.save_chat(db_path, "alice", None, [{"role": "user", "content": "hi"}])

    with pytest.raises(store.UnknownChat):
        store.save_chat(db_path, "bob", chat_id, [{"role": "user", "content": "hijacked"}])


# --- list_chats ------------------------------------------------------------


def test_list_chats_returns_only_the_given_users_chats_newest_first(db_path):
    store.save_chat(db_path, "alice", None, [{"role": "user", "content": "alice chat 1"}])
    bob_chat = store.save_chat(db_path, "bob", None, [{"role": "user", "content": "bob chat"}])
    alice_chat_2 = store.save_chat(db_path, "alice", None, [{"role": "user", "content": "alice chat 2"}])

    chats = store.list_chats(db_path, "alice")

    ids = [c["id"] for c in chats]
    assert bob_chat not in ids
    assert ids[0] == alice_chat_2  # most-recently-updated first
    assert "messages" not in chats[0]  # list view is cheap - no transcript


# --- get_chat ----------------------------------------------------------


def test_get_chat_returns_none_for_unknown_id(db_path):
    assert store.get_chat(db_path, "alice", "does-not-exist") is None


def test_get_chat_returns_none_for_chat_owned_by_another_user(db_path):
    chat_id = store.save_chat(db_path, "alice", None, [{"role": "user", "content": "hi"}])

    assert store.get_chat(db_path, "bob", chat_id) is None


# --- rename_chat -------------------------------------------------------


def test_rename_chat_updates_the_title(db_path):
    chat_id = store.save_chat(db_path, "alice", None, [{"role": "user", "content": "hi"}])

    store.rename_chat(db_path, "alice", chat_id, "My renamed chat")

    assert store.get_chat(db_path, "alice", chat_id)["title"] == "My renamed chat"


def test_rename_chat_rejects_a_blank_title(db_path):
    chat_id = store.save_chat(db_path, "alice", None, [{"role": "user", "content": "hi"}])

    with pytest.raises(ValueError):
        store.rename_chat(db_path, "alice", chat_id, "   ")


def test_rename_chat_unknown_id_raises_unknown_chat(db_path):
    with pytest.raises(store.UnknownChat):
        store.rename_chat(db_path, "alice", "does-not-exist", "New title")


def test_rename_chat_owned_by_another_user_raises_unknown_chat(db_path):
    chat_id = store.save_chat(db_path, "alice", None, [{"role": "user", "content": "hi"}])

    with pytest.raises(store.UnknownChat):
        store.rename_chat(db_path, "bob", chat_id, "Hijacked title")


# --- delete_chat -------------------------------------------------------


def test_delete_chat_removes_the_row(db_path):
    chat_id = store.save_chat(db_path, "alice", None, [{"role": "user", "content": "hi"}])

    store.delete_chat(db_path, "alice", chat_id)

    assert store.get_chat(db_path, "alice", chat_id) is None


def test_delete_chat_unknown_id_raises_unknown_chat(db_path):
    with pytest.raises(store.UnknownChat):
        store.delete_chat(db_path, "alice", "does-not-exist")


def test_delete_chat_owned_by_another_user_raises_unknown_chat(db_path):
    chat_id = store.save_chat(db_path, "alice", None, [{"role": "user", "content": "hi"}])

    with pytest.raises(store.UnknownChat):
        store.delete_chat(db_path, "bob", chat_id)

    # Still there - bob's failed attempt must not have deleted alice's chat.
    assert store.get_chat(db_path, "alice", chat_id) is not None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv_chat/Scripts/python.exe -m pytest tests/test_chats_store.py -v` (from `chat_app/`)
Expected: `ModuleNotFoundError: No module named 'chat_app.chats'`

- [ ] **Step 3: Create the package and implement the store**

Create `chat_app/src/chat_app/chats/__init__.py` (empty file).

Create `chat_app/src/chat_app/chats/store.py`:

```python
"""Per-user chat history: one row per conversation, its whole message
transcript stored as a JSON blob.

Same conventions as ``auth/store.py``: plain ``sqlite3``, no ORM, a
``_connect(db_path)`` helper that creates the table if missing and
returns a connection, one open/close per public call. A JSON blob (not a
normalized per-message table) because the app already treats a
conversation as "read/write the whole thing at once" - the client
replays the full transcript on every request - so a blob matches the
real access pattern and keeps this store thin.

Every function takes ``username`` and filters ``WHERE id = ? AND
username = ?`` - a chat id belonging to another user is
indistinguishable from a nonexistent one, so nothing here can be used to
enumerate or read someone else's chats by guessing an id.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class UnknownChat(Exception):
    """Raised when chat_id doesn't exist, or doesn't belong to this user
    - the two cases are deliberately indistinguishable from the caller's
    side (see module docstring)."""


_TITLE_MAX_LENGTH = 60
_TITLE_TRUNCATE_TO = 57


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chats (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            title TEXT NOT NULL,
            messages TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chats_username_updated ON chats(username, updated_at DESC)"
    )
    conn.commit()
    return conn


def _derive_title(messages: list[dict]) -> str:
    for message in messages:
        if message.get("role") != "user":
            continue
        text = (message.get("content") or "").strip()
        if not text:
            continue
        if len(text) > _TITLE_MAX_LENGTH:
            return text[:_TITLE_TRUNCATE_TO] + "..."
        return text
    return "New chat"


def save_chat(db_path: Path, username: str, chat_id: str | None, messages: list[dict]) -> str:
    """Create (chat_id is None) or overwrite (chat_id given) a chat's
    full transcript. Returns the chat id either way."""
    conn = _connect(db_path)
    try:
        now = datetime.now(timezone.utc).isoformat()
        messages_json = json.dumps(messages)

        if chat_id is None:
            new_id = secrets.token_urlsafe(12)
            title = _derive_title(messages)
            conn.execute(
                "INSERT INTO chats (id, username, title, messages, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (new_id, username, title, messages_json, now, now),
            )
            conn.commit()
            return new_id

        updated = conn.execute(
            "UPDATE chats SET messages = ?, updated_at = ? WHERE id = ? AND username = ?",
            (messages_json, now, chat_id, username),
        ).rowcount
        conn.commit()
        if updated == 0:
            raise UnknownChat(chat_id)
        return chat_id
    finally:
        conn.close()


def list_chats(db_path: Path, username: str) -> list[dict]:
    """id/title/updated_at only - no messages - this feeds the sidebar
    list, which must stay cheap regardless of how long individual chats
    get."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, title, updated_at FROM chats WHERE username = ? ORDER BY updated_at DESC",
            (username,),
        ).fetchall()
    finally:
        conn.close()
    return [{"id": id_, "title": title, "updated_at": updated_at} for id_, title, updated_at in rows]


def get_chat(db_path: Path, username: str, chat_id: str) -> dict | None:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, title, messages, created_at, updated_at FROM chats WHERE id = ? AND username = ?",
            (chat_id, username),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    id_, title, messages_json, created_at, updated_at = row
    return {
        "id": id_,
        "title": title,
        "messages": json.loads(messages_json),
        "created_at": created_at,
        "updated_at": updated_at,
    }


def rename_chat(db_path: Path, username: str, chat_id: str, title: str) -> None:
    title = title.strip()
    if not title:
        raise ValueError("title must not be blank")
    conn = _connect(db_path)
    try:
        updated = conn.execute(
            "UPDATE chats SET title = ? WHERE id = ? AND username = ?",
            (title, chat_id, username),
        ).rowcount
        conn.commit()
        if updated == 0:
            raise UnknownChat(chat_id)
    finally:
        conn.close()


def delete_chat(db_path: Path, username: str, chat_id: str) -> None:
    conn = _connect(db_path)
    try:
        deleted = conn.execute(
            "DELETE FROM chats WHERE id = ? AND username = ?",
            (chat_id, username),
        ).rowcount
        conn.commit()
        if deleted == 0:
            raise UnknownChat(chat_id)
    finally:
        conn.close()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv_chat/Scripts/python.exe -m pytest tests/test_chats_store.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add chat_app/src/chat_app/chats/__init__.py chat_app/src/chat_app/chats/store.py chat_app/tests/test_chats_store.py
git commit -m "feat: add per-user chat history SQLite store"
```

---

## Task 2: Config, chat routes, and `/api/chat` persistence

**Files:**
- Modify: `chat_app/src/chat_app/config.py`
- Modify: `chat_app/tests/conftest.py`
- Modify: `chat_app/src/chat_app/pages/chat/routes.py`
- Test: `chat_app/tests/test_chat_routes.py`

**Interfaces:**
- Consumes (from Task 1): `chats_store.UnknownChat`, `chats_store.save_chat`, `chats_store.list_chats`, `chats_store.get_chat`, `chats_store.rename_chat`, `chats_store.delete_chat`
- Produces (used by Task 3/4):
  - `POST /api/chat` request body gains optional `"chat_id": str | null`; response JSON gains `"chat_id": str | null`.
  - `GET /api/chats` → `200` `[{"id", "title", "updated_at"}, ...]`
  - `GET /api/chats/<chat_id>` → `200 {"id", "title", "messages", "created_at", "updated_at"}` or `404 {"error": "Chat not found."}`
  - `PATCH /api/chats/<chat_id>` body `{"title": str}` → `204` or `400 {"error": "..."}` or `404 {"error": "Chat not found."}`
  - `DELETE /api/chats/<chat_id>` → `204` or `404 {"error": "Chat not found."}`

- [ ] **Step 1: Add `chats_db_path` to Settings**

Edit `chat_app/src/chat_app/config.py`, add after `users_db_path`:

```python
    # Per-user chat history - see chats/store.py. Mirrors users_db_path
    # immediately above it (relative to CWD by default, same convention).
    chats_db_path: Path = Path(_env("CHATS_DB_PATH", "data/chats.db"))
```

- [ ] **Step 2: Add the `chats_db` test fixture**

Edit `chat_app/tests/conftest.py`. Add the import:

```python
from chat_app.pages.chat import routes as chat_routes
```

Add the fixture (after the existing `users_db` fixture):

```python
@pytest.fixture
def chats_db(tmp_path, monkeypatch):
    """Points chat_app.pages.chat.routes' `settings` at a fresh, per-test
    SQLite file - same reasoning as users_db above: a frozen,
    import-time-evaluated Settings field can't be monkeypatched directly."""
    test_settings = dataclasses.replace(base_settings, chats_db_path=tmp_path / "chats.db")
    monkeypatch.setattr(chat_routes, "settings", test_settings)
    return test_settings.chats_db_path
```

- [ ] **Step 3: Write the failing route tests**

In `chat_app/tests/test_chat_routes.py`, add one import to the existing imports block at the top of the file (alongside `from chat_app.services.llm.base import ChatResult`):

```python
from chat_app.chats import store as chats_store
```

Then append these test functions to the end of the file:

```python
def test_api_chat_creates_a_new_chat_and_returns_its_id(client, chats_db):
    with patch("chat_app.services.llm.router.run_chat") as mock_run_chat:
        mock_run_chat.return_value = ChatResult(response="hi there", provider_id="openai")
        response = client.post("/api/chat", json={"question": "hello"})

    body = response.get_json()
    assert body["chat_id"]
    saved = chats_store.get_chat(chats_db, "test-admin", body["chat_id"])
    assert saved["messages"] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]
    assert saved["title"] == "hello"


def test_api_chat_with_chat_id_updates_the_existing_chat(client, chats_db):
    existing_id = chats_store.save_chat(
        chats_db, "test-admin", None, [{"role": "user", "content": "first"}]
    )

    with patch("chat_app.services.llm.router.run_chat") as mock_run_chat:
        mock_run_chat.return_value = ChatResult(response="second reply", provider_id="openai")
        response = client.post(
            "/api/chat",
            json={"question": "second question", "history": [{"role": "user", "content": "first"}], "chat_id": existing_id},
        )

    body = response.get_json()
    assert body["chat_id"] == existing_id
    saved = chats_store.get_chat(chats_db, "test-admin", existing_id)
    assert saved["messages"] == [
        {"role": "user", "content": "first"},
        {"role": "user", "content": "second question"},
        {"role": "assistant", "content": "second reply"},
    ]


def test_api_chat_persists_the_turn_even_when_the_provider_errors(client, chats_db):
    """A curated ValueError still becomes a saved assistant turn - same
    text the user sees in the transcript, so reopening the chat shows
    what happened."""
    with patch(
        "chat_app.services.llm.router.run_chat",
        side_effect=ValueError("Claude is not configured (missing API key)"),
    ):
        response = client.post("/api/chat", json={"question": "hello"})

    body = response.get_json()
    saved = chats_store.get_chat(chats_db, "test-admin", body["chat_id"])
    assert "Claude is not configured" in saved["messages"][-1]["content"]


def test_api_chat_persistence_failure_does_not_break_the_response(client, chats_db):
    with patch("chat_app.services.llm.router.run_chat") as mock_run_chat, \
         patch("chat_app.pages.chat.routes.chats_store.save_chat", side_effect=RuntimeError("disk full")):
        mock_run_chat.return_value = ChatResult(response="hi there", provider_id="openai")
        response = client.post("/api/chat", json={"question": "hello"})

    assert response.status_code == 200
    body = response.get_json()
    assert body["response"] == "hi there"
    assert body["chat_id"] is None


def test_api_chat_with_stale_chat_id_falls_back_to_creating_a_new_chat(client, chats_db):
    """The chat_id the client sent no longer exists (e.g. deleted from
    another tab) - the turn must not be lost, it lands in a fresh chat
    instead."""
    with patch("chat_app.services.llm.router.run_chat") as mock_run_chat:
        mock_run_chat.return_value = ChatResult(response="hi there", provider_id="openai")
        response = client.post("/api/chat", json={"question": "hello", "chat_id": "does-not-exist"})

    body = response.get_json()
    assert body["chat_id"] != "does-not-exist"
    saved = chats_store.get_chat(chats_db, "test-admin", body["chat_id"])
    assert saved["messages"][-1]["content"] == "hi there"


def test_list_chats_api_returns_only_the_current_users_chats(client, chats_db):
    mine = chats_store.save_chat(chats_db, "test-admin", None, [{"role": "user", "content": "mine"}])
    chats_store.save_chat(chats_db, "someone-else", None, [{"role": "user", "content": "not mine"}])

    response = client.get("/api/chats")

    ids = [c["id"] for c in response.get_json()]
    assert ids == [mine]


def test_get_chat_api_returns_the_full_record(client, chats_db):
    chat_id = chats_store.save_chat(chats_db, "test-admin", None, [{"role": "user", "content": "hi"}])

    response = client.get(f"/api/chats/{chat_id}")

    assert response.status_code == 200
    assert response.get_json()["messages"] == [{"role": "user", "content": "hi"}]


def test_get_chat_api_404_for_unknown_id(client, chats_db):
    response = client.get("/api/chats/does-not-exist")

    assert response.status_code == 404


def test_get_chat_api_404_for_a_chat_owned_by_someone_else(client, chats_db):
    chat_id = chats_store.save_chat(chats_db, "someone-else", None, [{"role": "user", "content": "hi"}])

    response = client.get(f"/api/chats/{chat_id}")

    assert response.status_code == 404


def test_rename_chat_api_updates_the_title(client, chats_db):
    chat_id = chats_store.save_chat(chats_db, "test-admin", None, [{"role": "user", "content": "hi"}])

    response = client.patch(f"/api/chats/{chat_id}", json={"title": "New title"})

    assert response.status_code == 204
    assert chats_store.get_chat(chats_db, "test-admin", chat_id)["title"] == "New title"


def test_rename_chat_api_rejects_a_blank_title(client, chats_db):
    chat_id = chats_store.save_chat(chats_db, "test-admin", None, [{"role": "user", "content": "hi"}])

    response = client.patch(f"/api/chats/{chat_id}", json={"title": "   "})

    assert response.status_code == 400


def test_rename_chat_api_404_for_unknown_id(client, chats_db):
    response = client.patch("/api/chats/does-not-exist", json={"title": "New title"})

    assert response.status_code == 404


def test_rename_chat_api_404_for_a_chat_owned_by_someone_else(client, chats_db):
    chat_id = chats_store.save_chat(chats_db, "someone-else", None, [{"role": "user", "content": "hi"}])

    response = client.patch(f"/api/chats/{chat_id}", json={"title": "Hijacked"})

    assert response.status_code == 404
    assert chats_store.get_chat(chats_db, "someone-else", chat_id)["title"] != "Hijacked"


def test_delete_chat_api_removes_the_chat(client, chats_db):
    chat_id = chats_store.save_chat(chats_db, "test-admin", None, [{"role": "user", "content": "hi"}])

    response = client.delete(f"/api/chats/{chat_id}")

    assert response.status_code == 204
    assert chats_store.get_chat(chats_db, "test-admin", chat_id) is None


def test_delete_chat_api_404_for_unknown_id(client, chats_db):
    response = client.delete("/api/chats/does-not-exist")

    assert response.status_code == 404


def test_delete_chat_api_404_for_a_chat_owned_by_someone_else(client, chats_db):
    chat_id = chats_store.save_chat(chats_db, "someone-else", None, [{"role": "user", "content": "hi"}])

    response = client.delete(f"/api/chats/{chat_id}")

    assert response.status_code == 404
    assert chats_store.get_chat(chats_db, "someone-else", chat_id) is not None
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `./venv_chat/Scripts/python.exe -m pytest tests/test_chat_routes.py -v`
Expected: FAIL — `chat_id` missing from responses, `/api/chats*` routes return 404 (undefined routes), `chats_store` not imported in `routes.py`.

- [ ] **Step 5: Implement the routes**

Edit `chat_app/src/chat_app/pages/chat/routes.py`. Add two imports near the top (with the existing ones):

```python
from chat_app.chats import store as chats_store
from chat_app.config import settings
```

Insert these new routes directly above the existing `@chat_bp.post("/api/chat")` line:

```python
@chat_bp.get("/api/chats")
def list_chats_api():
    return jsonify(chats_store.list_chats(settings.chats_db_path, service.current_username()))


@chat_bp.get("/api/chats/<chat_id>")
def get_chat_api(chat_id):
    chat = chats_store.get_chat(settings.chats_db_path, service.current_username(), chat_id)
    if chat is None:
        return jsonify({"error": "Chat not found."}), 404
    return jsonify(chat)


@chat_bp.patch("/api/chats/<chat_id>")
def rename_chat_api(chat_id):
    data = json_body()
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "Title must not be blank."}), 400
    try:
        chats_store.rename_chat(settings.chats_db_path, service.current_username(), chat_id, title)
    except chats_store.UnknownChat:
        return jsonify({"error": "Chat not found."}), 404
    return "", 204


@chat_bp.delete("/api/chats/<chat_id>")
def delete_chat_api(chat_id):
    try:
        chats_store.delete_chat(settings.chats_db_path, service.current_username(), chat_id)
    except chats_store.UnknownChat:
        return jsonify({"error": "Chat not found."}), 404
    return "", 204
```

Replace the existing `chat_api()` function body with:

```python
@chat_bp.post("/api/chat")
def chat_api():
    data = json_body()
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"response": "Please enter a question."})

    tools_used: list[str] = []
    provider_id = ""
    total_tokens = None
    try:
        result = router.run_chat(
            question,
            data.get("history", []),
            data.get("provider"),
            data.get("model"),
            data.get("enabled_extensions", []),
        )
        response_text = result.response
        tools_used = result.tools_used
        provider_id = result.provider_id
        total_tokens = result.total_tokens
    except ValueError as error:
        # Deliberately verbatim: the router raises these with wording
        # meant for whoever is chatting ("Claude is rate-limited right now
        # - try again in 42s, or pick another provider"). They contain no
        # internals, and replacing them with a reference number would make
        # the app worse for no security gain.
        response_text = f"❌ {error}"
    except Exception as error:
        # Anything else is unplanned, so its text is untrusted for display -
        # see errors.py.
        response_text = f"❌ {report(error, context='answering your question')}"

    # Persisted regardless of which branch above ran - an error turn is
    # saved too, same as the client already does unconditionally on its
    # own `history` array, so reopening a chat shows what happened.
    transcript = list(data.get("history", [])) + [
        {"role": "user", "content": question},
        {"role": "assistant", "content": response_text},
    ]
    chat_id = data.get("chat_id")
    try:
        chat_id = chats_store.save_chat(settings.chats_db_path, service.current_username(), chat_id, transcript)
    except chats_store.UnknownChat:
        # The chat_id the client sent no longer exists (deleted from
        # another tab, most likely) - fall back to creating a fresh chat
        # rather than losing this turn entirely.
        try:
            chat_id = chats_store.save_chat(settings.chats_db_path, service.current_username(), None, transcript)
        except Exception as error:  # noqa: BLE001 - persistence must not break the chat answer itself
            report(error, context="saving chat history")
            chat_id = None
    except Exception as error:  # noqa: BLE001 - persistence must not break the chat answer itself
        report(error, context="saving chat history")
        chat_id = None

    return jsonify(
        {
            "response": response_text,
            "tools_used": tools_used,
            "provider_id": provider_id,
            "total_tokens": total_tokens,
            "chat_id": chat_id,
        }
    )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `./venv_chat/Scripts/python.exe -m pytest tests/test_chat_routes.py -v`
Expected: all tests PASS.

- [ ] **Step 7: Run the full test suite to check for regressions**

Run: `./venv_chat/Scripts/python.exe -m pytest -q`
Expected: same pass count as before this task, plus the new tests. (Two pre-existing, environment-only failures — `test_api_providers_reflects_availability` and `test_list_providers_automatic_ignores_providers_outside_automatic_order` — depend on a live local Ollama server and are expected to fail in a sandbox with no Ollama running; unrelated to this change.)

- [ ] **Step 8: Commit**

```bash
git add chat_app/src/chat_app/config.py chat_app/tests/conftest.py chat_app/src/chat_app/pages/chat/routes.py chat_app/tests/test_chat_routes.py
git commit -m "feat: persist chat history and add /api/chats endpoints"
```

---

## Task 3: Frontend — URL-driven chat identity, load/save wiring

**Files:**
- Modify: `chat_app/src/chat_app/pages/chat/template/script.js`

**Interfaces:**
- Consumes (from Task 2): `GET /api/chats/<id>` → `{id, title, messages, created_at, updated_at}` or 404; `POST /api/chat` now accepts `chat_id` and returns `chat_id`.
- Produces (used by Task 4): global `let currentChatId`; `async function loadChatHistory()` (Task 4 implements its body — Task 3 only needs the call site to exist, so define it here as a stub that Task 4 replaces in the same file).

No automated test coverage for this task (this codebase has no JS test suite — see Global Constraints). Task 2's route tests already cover the API contract this task consumes.

- [ ] **Step 1: Remove the sessionStorage-based session mechanism**

In `chat_app/src/chat_app/pages/chat/template/script.js`, delete the entire "Chat session persistence" block — lines 36 through 76 (from the `// --- Chat session persistence ------` comment through the closing `}` of `saveSessionToStorage()`). This removes: `SESSION_STORAGE_KEY`, `sessionLog`, `loadSessionFromStorage()`, `saveSessionToStorage()`.

Replace it with:

```javascript
// --- Chat identity ------------------------------------------------------
// The URL's `id` query param is this page's chat identity; no id means a
// new, not-yet-saved chat. This replaces the old sessionStorage-based
// resume mechanism entirely: unlike sessionStorage, server-side
// persistence (via /api/chats) survives a closed tab/browser restart,
// and supports more than one conversation.
//
// NOTE: this file already has a top-level `const history = []` (the
// LLM-facing conversation array, declared at the very top of this
// file) - that shadows the browser's global `window.history` within
// this script's scope. Any URL-manipulation call below MUST go through
// `window.history.*` explicitly, never bare `history.*`, or it will
// silently call Array methods instead of the History API.
let currentChatId = new URLSearchParams(location.search).get('id');
```

- [ ] **Step 2: Remove every remaining reference to the deleted session functions**

In the `send()` function, delete these two lines (they called the now-deleted `saveSessionToStorage()` and pushed to the now-deleted `sessionLog`):

```javascript
  sessionLog.push({ role: 'user', text: question });
  saveSessionToStorage();
```

(this pair appears once right after `history.push({ role: 'user', content: question });` near the top of `send()`)

and these two blocks further down in `send()`:

```javascript
      appendMsg('system', note);
      sessionLog.push({ role: 'system', text: note });
      saveSessionToStorage();
```
→ becomes just:
```javascript
      appendMsg('system', note);
```

and:

```javascript
    history.push({ role: 'assistant', content: data.response });
    sessionLog.push({ role: 'assistant', text: data.response, meta: finalTimerText });
    saveSessionToStorage();
```
→ becomes:
```javascript
    history.push({ role: 'assistant', content: data.response });
```

- [ ] **Step 3: Add `chat_id` to the outgoing request and handle it in the response**

In `send()`, find the `fetch('/api/chat', ...)` call's JSON body and add `chat_id`:

```javascript
      body: JSON.stringify({
        question,
        history,
        provider: selectedProvider,
        model: selectedModel,
        enabled_extensions: currentEnabledExtensions(),
        chat_id: currentChatId,
      }),
```

Immediately after the line `history.push({ role: 'assistant', content: data.response });` (from Step 2, inside the `try` block of `send()`), add:

```javascript
    // A brand-new chat just got its first id back, or an existing one
    // was confirmed - either way the sidebar list (Task 4) may now be
    // stale.
    if (data.chat_id && data.chat_id !== currentChatId) {
      currentChatId = data.chat_id;
      window.history.pushState(null, '', `/chat?id=${encodeURIComponent(currentChatId)}`);
    }
    if (data.chat_id) {
      loadChatHistory();
    }
```

- [ ] **Step 4: Add `loadChat()` and replace the init/restore block**

Add this function near the bottom of the file, above the `document.getElementById('q').addEventListener(...)` block:

```javascript
async function loadChat(chatId) {
  try {
    const res = await fetch(`/api/chats/${encodeURIComponent(chatId)}`);
    if (!res.ok) {
      // Unknown or not-yours chat id - degrade to a fresh chat rather
      // than showing an error for what's just a stale/foreign link.
      currentChatId = null;
      window.history.replaceState(null, '', '/chat');
      return false;
    }
    const chat = await res.json();
    currentChatId = chat.id;
    for (const message of chat.messages) {
      appendMsg(message.role, message.content);
      history.push({ role: message.role, content: message.content });
    }
    return true;
  } catch (err) {
    currentChatId = null;
    window.history.replaceState(null, '', '/chat');
    return false;
  }
}

// Implemented in full by the sidebar-history-list feature - stubbed
// here so send()'s and the init block's calls have something to call
// while this file is worked on task-by-task. (Task 4 replaces this
// stub with a real implementation in this same file.)
async function loadChatHistory() {}
```

Now find the block at the very bottom of the file:

```javascript
loadProviders();
setInterval(loadProviders, 15000);

loadExtensions();
setInterval(loadExtensions, 15000); // same cadence as the provider poll above

// Restore a saved session (if this load is a navigation/reload within the
// same tab, not a first visit) before deciding whether to greet.
const savedSession = loadSessionFromStorage();
const hasRestoredMessages = !!savedSession && savedSession.log.length > 0;
if (savedSession) {
  for (const entry of savedSession.log) {
    const wrap = appendMsg(entry.role, entry.text);
    if (entry.meta) {
      // A completed, historical duration - it won't tick, which is
      // correct: the request it timed is long over.
      wrap.appendChild(createTimerElement(entry.meta));
    }
    sessionLog.push(entry);
  }
  history.push(...savedSession.history); // `history` is const - only ever .push()d into, never reassigned
}

// Only greet on a genuine first visit (nothing to restore) - reappending
// a fresh greeting on every reload/navigation made the log balloon with
// "Hi! I'm ready when you are." repeated on top of a restored
// conversation, which is exactly what the persistence feature above is
// supposed to prevent.
if (!hasRestoredMessages) {
  const greeting = pickGreetingMessage();
  appendMsg('assistant', greeting);
  sessionLog.push({ role: 'assistant', text: greeting });
  saveSessionToStorage();
}
```

Replace the whole block with:

```javascript
loadProviders();
setInterval(loadProviders, 15000);

loadExtensions();
setInterval(loadExtensions, 15000); // same cadence as the provider poll above

loadChatHistory();

// Only greet on a genuine fresh chat (no id in the URL, or the id
// turned out to be stale/foreign) - loadChat() itself replays every
// restored message, so this only decides whether a greeting is ALSO
// needed on top of that.
(async () => {
  const restored = currentChatId ? await loadChat(currentChatId) : false;
  if (!restored) {
    const greeting = pickGreetingMessage();
    appendMsg('assistant', greeting);
  }
})();
```

- [ ] **Step 5: Manual smoke check (no automated test for this file)**

Confirm by reading the edited file that no reference to `sessionLog`, `saveSessionToStorage`, or `loadSessionFromStorage` remains:

Run: `grep -n "sessionLog\|saveSessionToStorage\|loadSessionFromStorage" chat_app/src/chat_app/pages/chat/template/script.js`
Expected: no output (no matches).

- [ ] **Step 6: Run the full backend test suite (confirms no Python regressions from Task 2 are still green)**

Run: `./venv_chat/Scripts/python.exe -m pytest -q` (from `chat_app/`)
Expected: same pass count as the end of Task 2.

- [ ] **Step 7: Commit**

```bash
git add chat_app/src/chat_app/pages/chat/template/script.js
git commit -m "feat: drive chat identity from the URL, load/save via /api/chats"
```

---

## Task 4: Frontend — sidebar chat history list, rename, delete

**Files:**
- Modify: `chat_app/src/chat_app/pages/_shared/template/sidebar.html`
- Modify: `chat_app/src/chat_app/pages/_shared/template/sidebar.css`
- Modify: `chat_app/src/chat_app/pages/chat/template/script.js`

**Interfaces:**
- Consumes (from Task 2): `GET /api/chats`, `PATCH /api/chats/<id>`, `DELETE /api/chats/<id>`
- Consumes (from Task 3): `currentChatId`, `appendMsg`
- Consumes (existing, from `shared/modal.js`, already loaded on this page): `confirmModal({title, message, confirmLabel, danger}) -> Promise<boolean>`
- Replaces the `loadChatHistory()` stub Task 3 added with a real implementation.

No automated test coverage for this task (same reasoning as Task 3).

- [ ] **Step 1: Add the sidebar markup**

Edit `chat_app/src/chat_app/pages/_shared/template/sidebar.html`. Insert this block right after the closing `</nav>` tag and before the `{% if 'invites' in scopes %}` block:

```html
  {% if current_page == 'chat' %}
  <div class="sidebar-chats">
    <a href="/chat" class="sidebar-new-chat-btn">+ New chat</a>
    <div id="chat-history-list" class="chat-history-list"><p class="chat-history-empty">Loading...</p></div>
  </div>
  {% endif %}
```

- [ ] **Step 2: Add the sidebar CSS**

Edit `chat_app/src/chat_app/pages/_shared/template/sidebar.css`. Add after the `.sidebar-home` rule (before the `.sidebar-invite` comment block):

```css
/* Chat history panel - chat page only (see sidebar.html's current_page
   gate). Sits directly under the nav in DOM order, above the
   margin-top: auto-pushed .sidebar-invite/.sidebar-user pair below it. */
.sidebar-chats {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-top: 12px;
  border-top: 1px solid #e2e2e2;
}
.sidebar-new-chat-btn {
  font-size: 12px;
  font-weight: 500;
  text-align: center;
  padding: 6px 8px;
  border: 1px solid #ccc;
  border-radius: 6px;
  background: #fff;
  color: #1a1a1a;
  text-decoration: none;
  cursor: pointer;
}
.sidebar-new-chat-btn:hover { background: #f0f0ef; }

.chat-history-list { display: flex; flex-direction: column; gap: 2px; }
.chat-history-empty { font-size: 11px; color: #888; margin: 0; padding: 4px 2px; }

.chat-history-item {
  display: flex;
  align-items: center;
  gap: 4px;
  border-radius: 6px;
  padding: 2px 2px 2px 8px;
}
.chat-history-item:hover { background: #ececea; }
.chat-history-item.active { background: #e6f1fb; }

.chat-history-link {
  flex: 1;
  min-width: 0;
  font-size: 12px;
  color: #444;
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chat-history-item.active .chat-history-link { color: #185fa5; font-weight: 500; }

.chat-history-time {
  font-size: 10px;
  color: #888;
  flex-shrink: 0;
}

.chat-history-controls {
  display: none;
  flex-shrink: 0;
  gap: 2px;
}
.chat-history-item:hover .chat-history-controls { display: flex; }
.chat-history-rename-btn,
.chat-history-delete-btn {
  width: 20px;
  height: 20px;
  border: none;
  border-radius: 4px;
  background: none;
  color: #888;
  cursor: pointer;
  font-size: 12px;
  line-height: 1;
}
.chat-history-rename-btn:hover,
.chat-history-delete-btn:hover { background: #dcdcda; color: #1a1a1a; }

.chat-history-rename-input {
  flex: 1;
  min-width: 0;
  font: inherit;
  font-size: 12px;
  padding: 2px 4px;
  border: 1px solid #185fa5;
  border-radius: 4px;
}
```

In the existing `@media (max-width: 700px)` block near the bottom of the same file, add one rule so the chats panel wraps onto its own row in the horizontal mobile layout rather than cramming into the row alongside the nav links:

```css
  .sidebar-chats { flex-basis: 100%; border-top: none; }
```

- [ ] **Step 3: Implement the real `loadChatHistory()` and its supporting functions**

In `chat_app/src/chat_app/pages/chat/template/script.js`, replace the stub added in Task 3:

```javascript
// Implemented in full by the sidebar-history-list feature - stubbed
// here so send()'s and the init block's calls have something to call
// while this file is worked on task-by-task. (Task 4 replaces this
// stub with a real implementation in this same file.)
async function loadChatHistory() {}
```

with:

```javascript
async function loadChatHistory() {
  const list = document.getElementById('chat-history-list');
  if (!list) return; // not on the chat page's sidebar variant - nothing to do
  try {
    const res = await fetch('/api/chats');
    const chats = await res.json();
    renderChatHistoryList(chats);
  } catch (err) {
    list.innerHTML = '<p class="chat-history-empty">Could not load chat history.</p>';
  }
}

// Compact buckets, e.g. "2h ago" / "3d ago" - falls back to a plain
// date once it's old enough that a relative count stops being useful.
function formatRelativeTime(isoString) {
  const then = new Date(isoString).getTime();
  const diffSeconds = Math.max(0, (Date.now() - then) / 1000);
  if (diffSeconds < 60) return 'just now';
  const diffMinutes = Math.floor(diffSeconds / 60);
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 7) return `${diffDays}d ago`;
  return new Date(isoString).toLocaleDateString();
}

function renderChatHistoryList(chats) {
  const list = document.getElementById('chat-history-list');
  list.innerHTML = '';

  if (chats.length === 0) {
    list.innerHTML = '<p class="chat-history-empty">No chats yet.</p>';
    return;
  }

  for (const chat of chats) {
    list.appendChild(buildChatHistoryItem(chat));
  }
}

function buildChatHistoryItem(chat) {
  const item = document.createElement('div');
  item.className = 'chat-history-item' + (chat.id === currentChatId ? ' active' : '');

  const link = document.createElement('a');
  link.className = 'chat-history-link';
  link.href = `/chat?id=${encodeURIComponent(chat.id)}`;
  link.textContent = chat.title;
  item.appendChild(link);

  const time = document.createElement('span');
  time.className = 'chat-history-time';
  time.textContent = formatRelativeTime(chat.updated_at);
  item.appendChild(time);

  const controls = document.createElement('div');
  controls.className = 'chat-history-controls';

  const renameBtn = document.createElement('button');
  renameBtn.type = 'button';
  renameBtn.className = 'chat-history-rename-btn';
  renameBtn.setAttribute('aria-label', `Rename ${chat.title}`);
  renameBtn.textContent = '✎';
  renameBtn.addEventListener('click', () => startRenameChat(item, chat));
  controls.appendChild(renameBtn);

  const deleteBtn = document.createElement('button');
  deleteBtn.type = 'button';
  deleteBtn.className = 'chat-history-delete-btn';
  deleteBtn.setAttribute('aria-label', `Delete ${chat.title}`);
  deleteBtn.textContent = '×';
  deleteBtn.addEventListener('click', () => deleteChatEntry(chat));
  controls.appendChild(deleteBtn);

  item.appendChild(controls);
  return item;
}

function startRenameChat(item, chat) {
  const link = item.querySelector('.chat-history-link');
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'chat-history-rename-input';
  input.value = chat.title;
  link.replaceWith(input);
  input.focus();
  input.select();

  let settled = false;

  const commit = async () => {
    if (settled) return;
    settled = true;
    const newTitle = input.value.trim();
    if (newTitle && newTitle !== chat.title) {
      try {
        const res = await fetch(`/api/chats/${encodeURIComponent(chat.id)}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: newTitle }),
        });
        if (!res.ok) throw new Error(`Server responded with ${res.status}`);
      } catch (err) {
        // The list reload below shows the true (unrenamed) title either
        // way, which is enough feedback that the rename didn't take -
        // no separate error UI for a sidebar-scoped action this small.
      }
    }
    await loadChatHistory();
  };

  input.addEventListener('blur', commit);
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') input.blur(); // triggers commit via the blur handler above
    if (e.key === 'Escape') {
      settled = true;
      loadChatHistory();
    }
  });
}

async function deleteChatEntry(chat) {
  const confirmed = await confirmModal({
    title: 'Delete chat?',
    message: `Delete "${chat.title}"? This can't be undone.`,
    confirmLabel: 'Delete',
    danger: true,
  });
  if (!confirmed) return;

  try {
    const res = await fetch(`/api/chats/${encodeURIComponent(chat.id)}`, { method: 'DELETE' });
    if (!res.ok && res.status !== 404) throw new Error(`Server responded with ${res.status}`);
  } catch (err) {
    // Best-effort - the list reload / navigation below reflects
    // whatever the server's actual state ended up being either way.
  }

  if (chat.id === currentChatId) {
    location.href = '/chat';
    return;
  }
  await loadChatHistory();
}
```

- [ ] **Step 4: Manual smoke check**

Run: `grep -n "loadChatHistory" chat_app/src/chat_app/pages/chat/template/script.js`
Expected: shows the function definition plus its call sites in `send()` and the bottom init block (added in Task 3) — confirms the stub was fully replaced and every caller still resolves to this one definition.

- [ ] **Step 5: Run the full backend test suite (confirms the HTML/CSS/JS edits didn't touch anything Python-tested)**

Run: `./venv_chat/Scripts/python.exe -m pytest -q` (from `chat_app/`)
Expected: same pass count as the end of Task 2/3.

- [ ] **Step 6: Commit**

```bash
git add chat_app/src/chat_app/pages/_shared/template/sidebar.html chat_app/src/chat_app/pages/_shared/template/sidebar.css chat_app/src/chat_app/pages/chat/template/script.js
git commit -m "feat: add chat history list with rename/delete to the sidebar"
```

---

## Done

After Task 4, the feature is complete: `/chat` with no `id` starts fresh, sending a message creates a chat and pushes `?id=` into the URL, reloading or revisiting a `?id=` URL replays that chat from the server, the sidebar (chat page only) lists every chat with relative timestamps, and each entry can be renamed or deleted. The project owner should verify manually in a browser per this project's usual workflow (send a few messages, reload mid-conversation, open a second chat, rename one, delete one, confirm an unknown `?id=` degrades to a fresh chat).
