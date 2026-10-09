"""Owner-scoped delivery metadata. Never store addresses, subjects or bodies."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.utils.catalog import catalog


@catalog
def record_delivery(path: Path, owner: str, outcome: str, recipient_count: int, message_id: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path, timeout=15) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS deliveries (
            id INTEGER PRIMARY KEY, time TEXT NOT NULL, owner TEXT NOT NULL,
            outcome TEXT NOT NULL, recipient_count INTEGER NOT NULL, message_id TEXT NOT NULL
        )""")
        db.execute("INSERT INTO deliveries (time, owner, outcome, recipient_count, message_id) VALUES (?, ?, ?, ?, ?)",
                   (datetime.now(timezone.utc).isoformat(), owner, outcome, recipient_count, message_id))


@catalog
def read_audit(path: Path, owner: str, limit: int = 50) -> list[dict]:
    if not owner or not path.exists():
        return []
    if not 1 <= limit <= 200:
        raise ValueError("Audit limit must be between 1 and 200.")
    with sqlite3.connect(path, timeout=15) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("SELECT time, owner, outcome, recipient_count, message_id FROM deliveries WHERE owner = ? ORDER BY id DESC LIMIT ?",
                          (owner, limit)).fetchall()
    return [dict(row) for row in rows]
