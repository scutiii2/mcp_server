"""Durable store for approval-gated / resumable multi-step requests.

Some capabilities can't complete inside a single synchronous tool call -
user_provisioning's SAP user creation should only execute after a human
approver clicks a link in an email, which might happen hours or days
after the original chat request. That gap has to survive independently
of any chat session and any process restart, so it can't be an in-memory
dict the way cooldown.py's rate-limit state can (see that file's
docstring for why losing that on restart is fine - losing a pending
approval on restart is not).

Deliberately generic, not user_provisioning-specific: the README already
flags that Rename needs its own "checkpoint/resume job runner" - same
underlying need. One shared store here means that's cheaper to build
later, not more entangled with this feature.

SQLite (stdlib ``sqlite3``) rather than a new dependency - same
"reach for stdlib first" choice already made for infra/email.py. Not
built for high concurrency (an approval workflow is a low write-rate
workload); if that ever changes, swap the backing store, not the call
sites - every function here takes/returns plain dataclasses, no SQL
leaks upward into domain.py.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


@dataclass
class PendingRequest:
    token: str
    capability: str
    payload: dict[str, Any]
    status: str  # "pending" | "executed"
    created_at: str
    expires_at: str
    approved_by: str | None = None
    executed_at: str | None = None

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > datetime.fromisoformat(self.expires_at)


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pending_requests (
            token TEXT PRIMARY KEY,
            capability TEXT NOT NULL,
            payload TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            approved_by TEXT,
            executed_at TEXT
        )
        """
    )
    return conn


def create(db_path: Path, capability: str, payload: dict[str, Any], *, ttl_hours: int = 72) -> str:
    """Persist a new pending request and return its (unguessable) token.

    ``secrets.token_urlsafe`` - not ``uuid4`` - deliberately: this token
    is the entire access control for the approval link (see
    approval_routes.py's module docstring for why execution is gated on
    "possession of this token", not any real auth), so it needs to be
    cryptographically unguessable, not just statistically unique.
    """
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=ttl_hours)

    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO pending_requests (token, capability, payload, status, created_at, expires_at) "
            "VALUES (?, ?, ?, 'pending', ?, ?)",
            (token, capability, json.dumps(payload), now.isoformat(), expires_at.isoformat()),
        )
        conn.commit()
    finally:
        conn.close()
    return token


def get(db_path: Path, token: str) -> PendingRequest | None:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT token, capability, payload, status, created_at, expires_at, approved_by, executed_at "
            "FROM pending_requests WHERE token = ?",
            (token,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None
    return PendingRequest(
        token=row[0],
        capability=row[1],
        payload=json.loads(row[2]),
        status=row[3],
        created_at=row[4],
        expires_at=row[5],
        approved_by=row[6],
        executed_at=row[7],
    )


def mark_executed(db_path: Path, token: str, *, approved_by: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE pending_requests SET status = 'executed', approved_by = ?, executed_at = ? WHERE token = ?",
            (approved_by, now, token),
        )
        conn.commit()
    finally:
        conn.close()