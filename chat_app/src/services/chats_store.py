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
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.utils.catalog import catalog


class UnknownChat(Exception):
    """Raised when chat_id doesn't exist, or doesn't belong to this user
    - the two cases are deliberately indistinguishable from the caller's
    side (see module docstring)."""


_TITLE_MAX_LENGTH = 60
_TITLE_TRUNCATE_TO = 57

# Matches the delimited attachment blocks Chat/script.js's
# buildAttachmentBlocks() folds into a user message's content when a file
# is attached (see parseAttachmentMarkers() there for the client-side
# counterpart, which strips the same blocks back out for display). Kept
# out of a derived title below - the model needs the full extracted text
# for context, but "[[ATTACHMENT filename=..." is not a usable title.
_ATTACHMENT_BLOCK_RE = re.compile(
    r'\[\[ATTACHMENT filename="[^"]*" chars="\d+" truncated="(?:true|false)"\]\]\n'
    r".*?\n\[\[/ATTACHMENT\]\]",
    re.DOTALL,
)


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
            updated_at TEXT NOT NULL,
            last_response_at TEXT
        )
        """
    )
    columns = {column[1] for column in conn.execute("PRAGMA table_info(chats)")}
    if "last_response_at" not in columns:
        conn.execute("ALTER TABLE chats ADD COLUMN last_response_at TEXT")
        conn.execute(
            "UPDATE chats SET last_response_at = updated_at WHERE last_response_at IS NULL"
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
        text = _ATTACHMENT_BLOCK_RE.sub("", message.get("content") or "").strip()
        if not text:
            continue
        if len(text) > _TITLE_MAX_LENGTH:
            return text[:_TITLE_TRUNCATE_TO] + "..."
        return text
    return "New chat"


def save_chat(db_path: Path, username: str, chat_id: str | None, messages: list[dict]) -> str:
    """Create (chat_id is None) or overwrite (chat_id given) a chat's
    full transcript. Returns the chat id either way.

    The overwrite (UPDATE) branch also replaces `title` when the existing
    title is still the "New chat" placeholder - this lets a chat created
    with an empty transcript up front (see pages/chat/routes.py's early
    chat_id minting) pick up a real title on its next save, without ever
    touching a title the user set via rename_chat."""
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

        # title is only replaced when it's still the "New chat" placeholder
        # - a chat created with an empty transcript up front (see
        # pages/chat/routes.py's early chat_id minting) gets that
        # placeholder on INSERT, and this is where it becomes a real title
        # once the first real transcript arrives. A title the user set via
        # rename_chat is anything else and must survive every later save.
        updated = conn.execute(
            "UPDATE chats SET messages = ?, updated_at = ?, "
            "title = CASE WHEN title = 'New chat' THEN ? ELSE title END "
            "WHERE id = ? AND username = ?",
            (messages_json, now, _derive_title(messages), chat_id, username),
        ).rowcount
        conn.commit()
        if updated == 0:
            raise UnknownChat(chat_id)
        return chat_id
    finally:
        conn.close()


def record_last_response(db_path: Path, username: str, chat_id: str, timestamp: str) -> None:
    """Record when ``chat_id`` last received a model response."""
    conn = _connect(db_path)
    try:
        updated = conn.execute(
            "UPDATE chats SET last_response_at = ? WHERE id = ? AND username = ?",
            (timestamp, chat_id, username),
        ).rowcount
        conn.commit()
        if updated == 0:
            raise UnknownChat(chat_id)
    finally:
        conn.close()


def list_chats(
    db_path: Path,
    username: str,
    activity_by_chat: dict[str, dict] | None = None,
) -> list[dict]:
    """Sidebar metadata and optional activity, without loading transcripts."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, title, updated_at, last_response_at FROM chats WHERE username = ?",
            (username,),
        ).fetchall()
    finally:
        conn.close()
    activity_by_chat = activity_by_chat or {}
    chats = [
        {
            "id": id_,
            "title": title,
            "updated_at": updated_at,
            "last_response_at": last_response_at,
            "activity": activity_by_chat.get(id_),
        }
        for id_, title, updated_at, last_response_at in rows
    ]
    running = [
        chat
        for chat in chats
        if chat["activity"] and chat["activity"].get("status") == "running"
    ]
    completed = [
        chat
        for chat in chats
        if not (chat["activity"] and chat["activity"].get("status") == "running")
    ]
    running.sort(key=lambda chat: chat["activity"].get("started_at", ""), reverse=True)
    completed.sort(key=lambda chat: chat["last_response_at"] or "", reverse=True)
    return running + completed


def get_chat(db_path: Path, username: str, chat_id: str) -> dict | None:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, title, messages, created_at, updated_at, last_response_at FROM chats WHERE id = ? AND username = ?",
            (chat_id, username),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    id_, title, messages_json, created_at, updated_at, last_response_at = row
    return {
        "id": id_,
        "title": title,
        "messages": json.loads(messages_json),
        "created_at": created_at,
        "updated_at": updated_at,
        "last_response_at": last_response_at,
    }


@catalog
def render_messages(messages: list[dict]) -> str:
    """Plain-text rendering of a list of transcript messages, one
    "--- header ---" / content / blank-line block per message - shared by
    export_messages below (the full-chat download) and
    services/summarization.py (both the raw text folded into the
    summarization prompt and the cumulative log-attachment message it
    writes back), so every plain-text rendering of a transcript in this
    app looks identical."""
    lines = []
    for message in messages:
        header = "command" if message.get("kind") == "command" else message.get("role", "unknown")
        meta_bits = []
        if message.get("model"):
            meta_bits.append(message["model"])
        if isinstance(message.get("total_tokens"), int):
            meta_bits.append(f"{message['total_tokens']} tokens")
        if isinstance(message.get("elapsed_seconds"), (int, float)):
            meta_bits.append(f"{message['elapsed_seconds']}s")
        if meta_bits:
            header = f"{header} ({', '.join(meta_bits)})"
        lines.append(f"--- {header} ---")
        lines.append(message.get("content") or "")
        lines.append("")
    return "\n".join(lines)


def _fence(text: str) -> str:
    """Wrap text in a code fence longer than any backtick run inside it."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    ticks = "`" * max(3, longest + 1)
    return f"{ticks}text\n{text.rstrip()}\n{ticks}"


def render_messages_markdown(messages: list[dict]) -> str:
    """Markdown rendering of a transcript. Cleared history lives in the
    "log_attachment" message (raw log of everything before the clear) and
    an optional "summary" message; both get their own section so the
    export covers cleared turns too."""
    parts = []
    for message in messages:
        kind = message.get("kind")
        content = message.get("content") or ""
        if kind == "log_attachment":
            parts.append("## Cleared history (raw log)\n\n" + _fence(content))
            continue
        if kind == "summary":
            parts.append("## Summary of earlier conversation\n\n" + content)
            continue
        header = "Command" if kind == "command" else str(message.get("role", "unknown")).capitalize()
        meta_bits = []
        if message.get("model"):
            meta_bits.append(message["model"])
        if isinstance(message.get("total_tokens"), int):
            meta_bits.append(f"{message['total_tokens']} tokens")
        if isinstance(message.get("elapsed_seconds"), (int, float)):
            meta_bits.append(f"{message['elapsed_seconds']}s")
        if meta_bits:
            header = f"{header} ({', '.join(meta_bits)})"
        body = _fence(content) if kind == "command" else content
        parts.append(f"### {header}\n\n{body}")
    return "\n\n".join(parts) + "\n"


def export_messages(db_path: Path, username: str, chat_id: str) -> str | None:
    """Markdown rendering of a chat's full transcript, including history
    already cleared out of the LLM context (see render_messages_markdown).
    Returns None for an unknown or not-yours chat id (same
    indistinguishable-404 reasoning as get_chat), never raises.

    Reads straight off get_chat's dicts, no schema change - content
    already carries any folded-in attachment text (see script.js's
    buildAttachmentBlocks)."""
    chat = get_chat(db_path, username, chat_id)
    if chat is None:
        return None
    header = f"# {chat['title']}\n\nExported: {datetime.now(timezone.utc).isoformat()}\n\n"
    return header + render_messages_markdown(chat["messages"])


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


def delete_chats(db_path: Path, username: str, chat_ids: list[str]) -> int:
    """Delete the requested chats that belong to ``username``.

    Missing IDs and chats owned by another account are intentionally ignored:
    the browser treats a stale selection from another tab as already deleted,
    and this preserves the store's non-enumeration boundary.
    """
    unique_ids = list(dict.fromkeys(chat_ids))
    if not unique_ids:
        return 0
    placeholders = ", ".join("?" for _ in unique_ids)
    conn = _connect(db_path)
    try:
        deleted = conn.execute(
            f"DELETE FROM chats WHERE username = ? AND id IN ({placeholders})",
            [username, *unique_ids],
        ).rowcount
        conn.commit()
        return deleted
    finally:
        conn.close()
