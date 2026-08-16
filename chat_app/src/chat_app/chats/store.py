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
