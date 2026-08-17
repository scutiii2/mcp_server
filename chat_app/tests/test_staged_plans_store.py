"""Tests for services/llm/staged_plans_store.py - mirrors
mcp_server/tests/test_pending_requests.py's shape: real SQLite file I/O
via tmp_path, not a mocked sqlite3, since the whole point of this module
is that the state survives outside the process.
"""

from __future__ import annotations

from pathlib import Path

from chat_app.services.llm import staged_plans_store


def test_save_then_get_roundtrips_the_plan(tmp_path: Path):
    db = tmp_path / "staged_plans.db"
    plan = [{"type": "tool_call", "detail": "check zima's health"}]
    results = [{"detail": "check zima's health", "result": "zima: cpu 12%"}]

    staged_plans_store.save(db, "chat-1", "ollama", "phi4-mini:latest", plan, 1, results)
    record = staged_plans_store.get(db, "chat-1")

    assert record is not None
    assert record.provider_id == "ollama"
    assert record.model == "phi4-mini:latest"
    assert record.plan == plan
    assert record.step_index == 1
    assert record.results == results
    assert record.is_expired is False


def test_get_unknown_chat_id_returns_none(tmp_path: Path):
    assert staged_plans_store.get(tmp_path / "staged_plans.db", "no-such-chat") is None


def test_save_twice_for_the_same_chat_id_replaces_the_row(tmp_path: Path):
    """A resumed plan's step_index advances across turns - the second
    save() must overwrite, not create a second row for the same chat."""
    db = tmp_path / "staged_plans.db"
    staged_plans_store.save(db, "chat-1", "ollama", "m", [{"type": "ask_user", "detail": "q1"}], 0, [])

    staged_plans_store.save(
        db, "chat-1", "ollama", "m", [{"type": "ask_user", "detail": "q1"}], 1,
        [{"detail": "q1", "result": "answered"}],
    )

    record = staged_plans_store.get(db, "chat-1")
    assert record.step_index == 1
    assert record.results == [{"detail": "q1", "result": "answered"}]


def test_negative_ttl_is_already_expired_and_get_returns_none(tmp_path: Path):
    db = tmp_path / "staged_plans.db"
    staged_plans_store.save(db, "chat-1", "ollama", "m", [], 0, [], ttl_hours=-1)

    assert staged_plans_store.get(db, "chat-1") is None


def test_delete_removes_the_row(tmp_path: Path):
    db = tmp_path / "staged_plans.db"
    staged_plans_store.save(db, "chat-1", "ollama", "m", [], 0, [])

    staged_plans_store.delete(db, "chat-1")

    assert staged_plans_store.get(db, "chat-1") is None


def test_delete_of_an_unknown_chat_id_is_a_quiet_no_op(tmp_path: Path):
    staged_plans_store.delete(tmp_path / "staged_plans.db", "no-such-chat")  # must not raise


def test_db_file_created_in_a_nonexistent_parent_directory(tmp_path: Path):
    db = tmp_path / "does" / "not" / "exist" / "staged_plans.db"

    staged_plans_store.save(db, "chat-1", "ollama", "m", [], 0, [])

    assert db.exists()
    assert staged_plans_store.get(db, "chat-1") is not None


def test_two_chats_do_not_clobber_each_other(tmp_path: Path):
    db = tmp_path / "staged_plans.db"
    staged_plans_store.save(db, "chat-a", "ollama", "m", [{"type": "ask_user", "detail": "qa"}], 0, [])
    staged_plans_store.save(db, "chat-b", "ollama", "m", [{"type": "ask_user", "detail": "qb"}], 0, [])

    staged_plans_store.delete(db, "chat-a")

    assert staged_plans_store.get(db, "chat-a") is None
    assert staged_plans_store.get(db, "chat-b") is not None
