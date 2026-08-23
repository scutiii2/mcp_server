"""Tests for infra/pending_requests.py - pure stdlib sqlite3, no pydantic
or mcp import needed. Uses pytest's built-in ``tmp_path`` fixture for real
file I/O against a real SQLite file rather than mocking sqlite3, since the
whole point of this module is that the state survives outside the process.
"""

from __future__ import annotations

from pathlib import Path

from src.infra import pending_requests


def test_create_returns_an_unguessable_token(tmp_path: Path):
    token = pending_requests.create(tmp_path / "pending.db", "example", {"target": "host-a"})
    assert len(token) > 20


def test_create_then_get_roundtrips_the_payload(tmp_path: Path):
    db = tmp_path / "pending.db"
    token = pending_requests.create(db, "example", {"target": "host-a", "action": "restart"})

    record = pending_requests.get(db, token)

    assert record is not None
    assert record.capability == "example"
    assert record.payload == {"target": "host-a", "action": "restart"}
    assert record.status == "pending"
    assert record.is_expired is False


def test_get_unknown_token_returns_none(tmp_path: Path):
    assert pending_requests.get(tmp_path / "pending.db", "not-a-real-token") is None


def test_mark_executed_updates_status_and_approver(tmp_path: Path):
    db = tmp_path / "pending.db"
    token = pending_requests.create(db, "example", {"target": "host-a"})

    pending_requests.mark_executed(db, token, approved_by="alice@example.com")
    record = pending_requests.get(db, token)

    assert record.status == "executed"
    assert record.approved_by == "alice@example.com"
    assert record.executed_at is not None


def test_negative_ttl_is_already_expired(tmp_path: Path):
    db = tmp_path / "pending.db"
    token = pending_requests.create(db, "example", {"target": "host-a"}, ttl_hours=-1)

    assert pending_requests.get(db, token).is_expired is True


def test_db_file_created_in_a_nonexistent_parent_directory(tmp_path: Path):
    """create() shouldn't require the caller to pre-create the parent dir -
    the default PENDING_REQUESTS_PATH is relative to the working
    directory, so the first write often lands somewhere that doesn't
    exist yet."""
    db = tmp_path / "does" / "not" / "exist" / "pending.db"

    token = pending_requests.create(db, "example", {"target": "host-a"})

    assert db.exists()
    assert pending_requests.get(db, token) is not None


def test_two_records_do_not_clobber_each_other(tmp_path: Path):
    db = tmp_path / "pending.db"
    token_a = pending_requests.create(db, "example", {"target": "host-a"})
    token_b = pending_requests.create(db, "example", {"target": "host-b"})

    pending_requests.mark_executed(db, token_a, approved_by="alice")

    assert pending_requests.get(db, token_a).status == "executed"
    assert pending_requests.get(db, token_b).status == "pending"
