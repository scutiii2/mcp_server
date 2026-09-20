"""Tests for usage_limits.get_usage(): per-window totals, per-user
isolation, window boundaries and reset time."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from src.services import usage_limits


def _insert(db_path, username, tokens, age):
    usage_limits.record_usage(db_path, username, 1)  # ensures table exists
    conn = sqlite3.connect(str(db_path))
    ts = (datetime.now(timezone.utc) - age).isoformat()
    conn.execute("INSERT INTO token_usage (username, ts, tokens) VALUES (?, ?, ?)", (username, ts, tokens))
    conn.commit()
    conn.close()


def test_empty_history_reports_zero_and_no_reset(tmp_path):
    usage = usage_limits.get_usage(tmp_path / "usage.db", "alice")
    assert usage["six_hour"]["used"] == 0
    assert usage["six_hour"]["reset_at"] is None
    assert usage["weekly"]["limit"] == usage_limits.WEEKLY_TOKEN_LIMIT


def test_windows_split_by_age(tmp_path):
    db = tmp_path / "usage.db"
    _insert(db, "alice", 100, timedelta(hours=1))
    _insert(db, "alice", 200, timedelta(hours=6))
    _insert(db, "alice", 400, timedelta(days=8))
    usage = usage_limits.get_usage(db, "alice")
    # +1 from the seeding record_usage call inside _insert (3 calls).
    assert usage["six_hour"]["used"] == 100 + 3
    assert usage["weekly"]["used"] == 100 + 200 + 3


def test_users_are_isolated(tmp_path):
    db = tmp_path / "usage.db"
    usage_limits.record_usage(db, "alice", 50)
    assert usage_limits.get_usage(db, "bob")["six_hour"]["used"] == 0


def test_reset_at_is_oldest_row_plus_window(tmp_path):
    db = tmp_path / "usage.db"
    _insert(db, "alice", 10, timedelta(hours=2))
    reset = datetime.fromisoformat(usage_limits.get_usage(db, "alice")["six_hour"]["reset_at"])
    expected = datetime.now(timezone.utc) + timedelta(hours=4)
    assert abs((reset - expected).total_seconds()) < 5
