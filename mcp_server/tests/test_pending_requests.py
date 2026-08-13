"""Tests for infra/pending_requests.py - pure stdlib sqlite3, no pydantic
or mcp import needed, unlike almost everything else in this test suite.
Uses pytest's built-in ``tmp_path`` fixture for real file I/O, same
approach test_kernel_domain.py and health/domain.py's maintenance-mode
tests already use for their own file-backed state.
"""

from __future__ import annotations

from pathlib import Path

from mcp_server.infra import pending_requests


def test_create_returns_an_unguessable_token(tmp_path: Path):
    token = pending_requests.create(tmp_path / "pending.db", "user_provisioning", {"sid": "E4G"})
    assert len(token) > 20


def test_create_then_get_roundtrips_the_payload(tmp_path: Path):
    db = tmp_path / "pending.db"
    token = pending_requests.create(db, "user_provisioning", {"sid": "E4G", "user_id": "JDOE"})

    record = pending_requests.get(db, token)

    assert record is not None
    assert record.capability == "user_provisioning"
    assert record.payload == {"sid": "E4G", "user_id": "JDOE"}
    assert record.status == "pending"
    assert record.is_expired is False


def test_get_unknown_token_returns_none(tmp_path: Path):
    assert pending_requests.get(tmp_path / "pending.db", "not-a-real-token") is None


def test_mark_executed_updates_status_and_approver(tmp_path: Path):
    db = tmp_path / "pending.db"
    token = pending_requests.create(db, "user_provisioning", {"sid": "E4G"})

    pending_requests.mark_executed(db, token, approved_by="alice@example.com")
    record = pending_requests.get(db, token)

    assert record.status == "executed"
    assert record.approved_by == "alice@example.com"
    assert record.executed_at is not None


def test_negative_ttl_is_already_expired(tmp_path: Path):
    db = tmp_path / "pending.db"
    token = pending_requests.create(db, "user_provisioning", {"sid": "E4G"}, ttl_hours=-1)

    assert pending_requests.get(db, token).is_expired is True


def test_db_file_created_in_a_nonexistent_parent_directory(tmp_path: Path):
    """create() shouldn't require the caller to pre-create the parent dir -
    mirrors the same convenience infra/db.py and infra/ssh.py give their
    own callers."""
    db = tmp_path / "does" / "not" / "exist" / "pending.db"

    token = pending_requests.create(db, "user_provisioning", {"sid": "E4G"})

    assert db.exists()
    assert pending_requests.get(db, token) is not None


def test_two_records_do_not_clobber_each_other(tmp_path: Path):
    db = tmp_path / "pending.db"
    token_a = pending_requests.create(db, "user_provisioning", {"sid": "E4G"})
    token_b = pending_requests.create(db, "user_provisioning", {"sid": "P01"})

    pending_requests.mark_executed(db, token_a, approved_by="alice")

    assert pending_requests.get(db, token_a).status == "executed"
    assert pending_requests.get(db, token_b).status == "pending"