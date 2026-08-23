"""Ephemeral storage bridging one paused chat turn to the next.

A staged-pipeline plan (see staged_pipeline.py) that pauses on an
`ask_user` step needs to survive between one HTTP request and the next -
longer than an in-memory dict should live, but not as long as a real
record (a chat transcript, an account). Mirrors
mcp_server/infra/pending_requests.py's shape exactly: SQLite, opaque JSON
payload, TTL-based expiry, one row per key - chosen because it's already
this project's answer to exactly this "state that must outlive one
request but shouldn't be an in-memory dict, and shouldn't be permanent"
shape.

One row per chat_id - present only while a plan is paused on `ask_user`.
Written at the pause, deleted the moment Conclude finishes.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


@dataclass
class StagedPlan:
    chat_id: str
    provider_id: str
    model: str
    plan: list[dict[str, Any]]
    step_index: int
    results: list[dict[str, Any]]
    created_at: str
    expires_at: str

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > datetime.fromisoformat(self.expires_at)


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS staged_plans (
            chat_id     TEXT PRIMARY KEY,
            provider_id TEXT NOT NULL,
            model       TEXT NOT NULL,
            plan        TEXT NOT NULL,
            step_index  INTEGER NOT NULL,
            results     TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            expires_at  TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def save(
    db_path: Path,
    chat_id: str,
    provider_id: str,
    model: str,
    plan: list[dict[str, Any]],
    step_index: int,
    results: list[dict[str, Any]],
    *,
    ttl_hours: float = 24,
) -> None:
    """Create or overwrite this chat_id's paused plan. A second save() for
    the same chat_id (the step_index advancing across resumes) replaces
    the row rather than erroring - "one row per chat_id" is the whole
    point (see module docstring), and INSERT OR REPLACE is the plain
    SQLite way to express that without a separate exists-check."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=ttl_hours)
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO staged_plans "
            "(chat_id, provider_id, model, plan, step_index, results, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                chat_id,
                provider_id,
                model,
                json.dumps(plan),
                step_index,
                json.dumps(results),
                now.isoformat(),
                expires_at.isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get(db_path: Path, chat_id: str) -> StagedPlan | None:
    """None for a missing row *or* an expired one - expiry is opaque to
    callers here (unlike pending_requests.py, which exposes is_expired for
    its callers to report separately - an emailed-link approval needs to
    tell someone "this link expired" rather than pretending it never
    existed; staged_pipeline.py has no such need, an expired plan and no
    plan at all mean exactly the same thing to it: start fresh)."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT chat_id, provider_id, model, plan, step_index, results, created_at, expires_at "
            "FROM staged_plans WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    record = StagedPlan(
        chat_id=row[0],
        provider_id=row[1],
        model=row[2],
        plan=json.loads(row[3]),
        step_index=row[4],
        results=json.loads(row[5]),
        created_at=row[6],
        expires_at=row[7],
    )
    if record.is_expired:
        return None
    return record


def delete(db_path: Path, chat_id: str) -> None:
    conn = _connect(db_path)
    try:
        conn.execute("DELETE FROM staged_plans WHERE chat_id = ?", (chat_id,))
        conn.commit()
    finally:
        conn.close()
