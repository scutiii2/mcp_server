"""Tests for the per-user chat-history SQLite store."""

from __future__ import annotations

import sqlite3

import pytest

from src.services import chats_store as store


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


def test_save_chat_title_excludes_a_folded_in_attachment_block(db_path):
    # Matches Chat/script.js's buildAttachmentBlocks() format - a file
    # attached to a chat message folds its extracted text into `content`
    # this way so ai_agent still gets it as context, but it must never
    # leak into the derived title (see chats_store._ATTACHMENT_BLOCK_RE).
    content = (
        "Summarize this file\n\n"
        '[[ATTACHMENT filename="notes.txt" chars="11" truncated="false"]]\n'
        "hello world\n"
        "[[/ATTACHMENT]]"
    )
    chat_id = store.save_chat(db_path, "alice", None, [{"role": "user", "content": content}])

    chat = store.get_chat(db_path, "alice", chat_id)
    assert chat["title"] == "Summarize this file"


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


def test_save_chat_update_sets_title_when_still_the_new_chat_placeholder(db_path):
    """Regression coverage for chat_api's early chat_id minting (see
    pages/chat/routes.py): a chat created with an empty transcript (via
    save_chat(..., None, [])) gets the "New chat" placeholder title; the
    very next save (the real transcript, via the id-given/UPDATE path)
    must compute a real title instead of leaving the placeholder forever."""
    chat_id = store.save_chat(db_path, "alice", None, [])

    store.save_chat(db_path, "alice", chat_id, [{"role": "user", "content": "how do I reset a password?"}])

    assert store.get_chat(db_path, "alice", chat_id)["title"] == "how do I reset a password?"


def test_save_chat_update_preserves_a_manually_renamed_title(db_path):
    """A title the user set via rename_chat must survive a later
    save_chat update - only the "New chat" placeholder gets replaced."""
    chat_id = store.save_chat(db_path, "alice", None, [{"role": "user", "content": "first"}])
    store.rename_chat(db_path, "alice", chat_id, "My renamed chat")

    store.save_chat(
        db_path, "alice", chat_id,
        [{"role": "user", "content": "first"}, {"role": "assistant", "content": "reply"}],
    )

    assert store.get_chat(db_path, "alice", chat_id)["title"] == "My renamed chat"


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


def test_list_chats_prioritizes_running_activity_and_returns_response_timestamp(db_path):
    first_chat = store.save_chat(db_path, "alice", None, [{"role": "user", "content": "first"}])
    second_chat = store.save_chat(db_path, "alice", None, [{"role": "user", "content": "second"}])
    response_timestamp = "2026-09-16T10:00:00+00:00"
    running_activity = {"status": "running", "started_at": "2026-09-16T10:01:00+00:00"}

    store.record_last_response(db_path, "alice", first_chat, response_timestamp)

    chats = store.list_chats(
        db_path,
        "alice",
        activity_by_chat={second_chat: running_activity},
    )

    assert [chat["id"] for chat in chats] == [second_chat, first_chat]
    assert chats[0]["activity"]["status"] == "running"
    assert chats[1]["last_response_at"] == response_timestamp


def test_list_chats_keeps_new_chat_response_timestamp_empty_after_reconnecting(db_path):
    chat_id = store.save_chat(db_path, "alice", None, [{"role": "user", "content": "hello"}])

    chats = store.list_chats(db_path, "alice")

    assert chats[0]["id"] == chat_id
    assert chats[0]["last_response_at"] is None


def test_connect_backfills_response_timestamp_when_migrating_legacy_chats(db_path):
    legacy_timestamp = "2026-09-16T09:00:00+00:00"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE chats (
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
        "INSERT INTO chats VALUES (?, ?, ?, ?, ?, ?)",
        ("legacy-chat", "alice", "Legacy", "[]", legacy_timestamp, legacy_timestamp),
    )
    conn.commit()
    conn.close()

    chats = store.list_chats(db_path, "alice")

    assert chats[0]["last_response_at"] == legacy_timestamp


# --- get_chat ----------------------------------------------------------


def test_get_chat_returns_the_last_response_timestamp(db_path):
    chat_id = store.save_chat(db_path, "alice", None, [{"role": "user", "content": "hi"}])
    response_timestamp = "2026-09-17T10:00:00+00:00"
    store.record_last_response(db_path, "alice", chat_id, response_timestamp)

    chat = store.get_chat(db_path, "alice", chat_id)

    assert chat["last_response_at"] == response_timestamp


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


def test_delete_chats_removes_only_the_requested_chats_owned_by_the_user(db_path):
    first = store.save_chat(db_path, "alice", None, [{"role": "user", "content": "first"}])
    second = store.save_chat(db_path, "alice", None, [{"role": "user", "content": "second"}])
    keep = store.save_chat(db_path, "alice", None, [{"role": "user", "content": "keep"}])
    other_user = store.save_chat(db_path, "bob", None, [{"role": "user", "content": "private"}])

    deleted = store.delete_chats(db_path, "alice", [first, second, other_user])

    assert deleted == 2
    assert store.get_chat(db_path, "alice", first) is None
    assert store.get_chat(db_path, "alice", second) is None
    assert store.get_chat(db_path, "alice", keep) is not None
    assert store.get_chat(db_path, "bob", other_user) is not None
