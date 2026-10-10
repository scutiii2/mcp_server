"""SQLite storage for support tickets, ticket groups and comments.

Every method is synchronous and opens its own short connection; callers on the
event loop reach it through asyncio.to_thread. Reading never creates the
database file. Ticket text is never logged. The only rules enforced here are the
atomic ones that need one transaction: the automatic-report dedupe and cap.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from src.services import ticket_rules as rules

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ticket_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'normal', priority_pinned INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT, group_id INTEGER NOT NULL REFERENCES ticket_groups(id),
    type TEXT NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open', priority TEXT NOT NULL DEFAULT 'normal',
    assignee TEXT, reporter TEXT NOT NULL, source TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '[]', context TEXT NOT NULL DEFAULT '{}',
    fingerprint TEXT, possible_group_id INTEGER,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, closed_at TEXT
);
CREATE INDEX IF NOT EXISTS tickets_reporter ON tickets (reporter, id);
CREATE INDEX IF NOT EXISTS tickets_group ON tickets (group_id);
CREATE INDEX IF NOT EXISTS tickets_fingerprint ON tickets (reporter, fingerprint, status);
CREATE TABLE IF NOT EXISTS ticket_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER NOT NULL REFERENCES tickets(id),
    author TEXT NOT NULL, author_role TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS comments_ticket ON ticket_comments (ticket_id, id);
"""

_OPEN = "status NOT IN ('resolved', 'closed')"
_SELECT = (
    "SELECT t.*, g.priority AS group_priority, g.priority_pinned AS group_pinned "
    "FROM tickets t JOIN ticket_groups g ON g.id = t.group_id"
)
_UPDATABLE = ("status", "priority", "assignee", "tags")


class AutoLimit(Exception):
    """The reporter reached the cap for automatic tickets."""


def _rank_sql(column: str) -> str:
    return f"(CASE {column} WHEN 'low' THEN 0 WHEN 'normal' THEN 1 WHEN 'high' THEN 2 ELSE 3 END)"


def _ticket(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["tags"] = json.loads(data["tags"])
    data["context"] = json.loads(data["context"])
    data["group_pinned"] = bool(data["group_pinned"])
    data["effective_priority"] = rules.higher_priority(data["priority"], data["group_priority"])
    data.pop("fingerprint", None)
    return data


def _group(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["priority_pinned"] = bool(data["priority_pinned"])
    return data


class TicketStore:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self._path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.executescript(_SCHEMA)
        return db

    # ---- writes -------------------------------------------------------

    def insert_ticket(
        self, *, reporter: str, type: str, title: str, description: str, source: str, tags: list[str],
        context: dict[str, Any], fingerprint: str | None, group_id: int | None,
        possible_group_id: int | None, now: str, auto_cap: int | None = None, auto_since: str | None = None,
    ) -> tuple[int, bool, int]:
        """(ticket id, created, group id). An open automatic ticket with the same reporter and
        fingerprint is returned instead of a new one; AutoLimit when the cap is reached."""
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if source == "ai_auto":
                if fingerprint:
                    row = db.execute(
                        f"SELECT id, group_id FROM tickets WHERE reporter = ? AND fingerprint = ? AND {_OPEN} "
                        "ORDER BY id DESC LIMIT 1",
                        (reporter, fingerprint),
                    ).fetchone()
                    if row is not None:
                        return row["id"], False, row["group_id"]
                if auto_cap is not None:
                    count = db.execute(
                        "SELECT COUNT(*) FROM tickets WHERE reporter = ? AND source = 'ai_auto' AND created_at >= ?",
                        (reporter, auto_since or ""),
                    ).fetchone()[0]
                    if count >= auto_cap:
                        raise AutoLimit()
            if group_id is None:
                group_id = db.execute(
                    "INSERT INTO ticket_groups (title, priority, priority_pinned, created_at, updated_at) "
                    "VALUES (?, 'normal', 0, ?, ?)",
                    (title[:120], now, now),
                ).lastrowid
            else:
                db.execute("UPDATE ticket_groups SET updated_at = ? WHERE id = ?", (now, group_id))
            ticket_id = db.execute(
                "INSERT INTO tickets (group_id, type, title, description, reporter, source, tags, context, "
                "fingerprint, possible_group_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (group_id, type, title, description, reporter, source, json.dumps(tags), json.dumps(context),
                 fingerprint, possible_group_id, now, now),
            ).lastrowid
            return ticket_id, True, group_id

    def add_comment(self, ticket_id: int, author: str, role: str, body: str, now: str) -> int:
        with closing(self._connect()) as db, db:
            comment_id = db.execute(
                "INSERT INTO ticket_comments (ticket_id, author, author_role, body, created_at) VALUES (?, ?, ?, ?, ?)",
                (ticket_id, author, role, body, now),
            ).lastrowid
            db.execute("UPDATE tickets SET updated_at = ? WHERE id = ?", (now, ticket_id))
            return comment_id

    def update_ticket(self, ticket_id: int, changes: dict[str, Any], now: str) -> bool:
        unknown = set(changes) - set(_UPDATABLE)
        if unknown:
            raise ValueError(f"Cannot change: {', '.join(sorted(unknown))}")
        sets, args = ["updated_at = ?"], [now]
        for key, value in changes.items():
            sets.append(f"{key} = ?")
            args.append(json.dumps(value) if key == "tags" else value)
        if "status" in changes:
            sets.append("closed_at = ?")
            args.append(now if changes["status"] == "closed" else None)
        with closing(self._connect()) as db, db:
            cursor = db.execute(f"UPDATE tickets SET {', '.join(sets)} WHERE id = ?", (*args, ticket_id))
            return cursor.rowcount == 1

    def move_ticket(self, ticket_id: int, group_id: int | None, now: str) -> int | None:
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT title FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
            if row is None:
                return None
            if group_id is None:
                group_id = db.execute(
                    "INSERT INTO ticket_groups (title, priority, priority_pinned, created_at, updated_at) "
                    "VALUES (?, 'normal', 0, ?, ?)",
                    (row["title"][:120], now, now),
                ).lastrowid
            elif db.execute("SELECT 1 FROM ticket_groups WHERE id = ?", (group_id,)).fetchone() is None:
                return None
            db.execute(
                "UPDATE tickets SET group_id = ?, possible_group_id = NULL, updated_at = ? WHERE id = ?",
                (group_id, now, ticket_id),
            )
            db.execute("UPDATE ticket_groups SET updated_at = ? WHERE id = ?", (now, group_id))
            return group_id

    def update_group(self, group_id: int, *, priority: str | None = None, pinned: bool | None = None, now: str) -> bool:
        sets, args = ["updated_at = ?"], [now]
        if priority is not None:
            sets.append("priority = ?")
            args.append(priority)
        if pinned is not None:
            sets.append("priority_pinned = ?")
            args.append(int(pinned))
        with closing(self._connect()) as db, db:
            cursor = db.execute(f"UPDATE ticket_groups SET {', '.join(sets)} WHERE id = ?", (*args, group_id))
            return cursor.rowcount == 1

    # ---- reads --------------------------------------------------------

    def find_open_auto(self, reporter: str, fingerprint: str) -> int | None:
        if not self._path.exists():
            return None
        with closing(self._connect()) as db:
            row = db.execute(
                f"SELECT id FROM tickets WHERE reporter = ? AND fingerprint = ? AND {_OPEN} ORDER BY id DESC LIMIT 1",
                (reporter, fingerprint),
            ).fetchone()
        return row["id"] if row else None

    def get_ticket(self, ticket_id: int) -> dict[str, Any] | None:
        if not self._path.exists():
            return None
        with closing(self._connect()) as db:
            row = db.execute(f"{_SELECT} WHERE t.id = ?", (ticket_id,)).fetchone()
        return _ticket(row) if row else None

    def list_tickets(
        self, *, reporter: str | None = None, status: str | None = None, type: str | None = None,
        tag: str | None = None, priority: str | None = None, assignee: str | None = None,
        group_id: int | None = None, possible_only: bool = False, limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        where: list[str] = []
        args: list[Any] = []

        def add(condition: str, *values: Any) -> None:
            where.append(condition)
            args.extend(values)

        if reporter:
            add("t.reporter = ?", reporter)
        if status:
            add("t.status = ?", status)
        if type:
            add("t.type = ?", type)
        if tag:
            add("EXISTS (SELECT 1 FROM json_each(t.tags) WHERE value = ?)", tag)
        if priority:
            add(f"MAX({_rank_sql('t.priority')}, {_rank_sql('g.priority')}) = ?", rules.priority_rank(priority))
        if assignee:
            add("t.assignee = ?", assignee)
        if group_id:
            add("t.group_id = ?", group_id)
        if possible_only:
            add("t.possible_group_id IS NOT NULL")
        sql = _SELECT + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY t.id DESC LIMIT ?"
        with closing(self._connect()) as db:
            rows = db.execute(sql, (*args, limit)).fetchall()
        return [_ticket(row) for row in rows]

    def candidates(self, type: str, tags: list[str], limit: int) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        inner = f"SELECT MAX(id) FROM tickets WHERE type = ? AND {_OPEN} GROUP BY group_id"
        sql = f"{_SELECT} WHERE t.id IN ({inner})"
        args: list[Any] = [type]
        if tags:
            marks = ", ".join("?" for _ in tags)
            sql += f" AND EXISTS (SELECT 1 FROM json_each(t.tags) WHERE value IN ({marks}))"
            args.extend(tags)
        sql += " ORDER BY t.id DESC LIMIT ?"
        with closing(self._connect()) as db:
            rows = db.execute(sql, (*args, limit)).fetchall()
        return [_ticket(row) for row in rows]

    def list_comments(self, ticket_id: int) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        with closing(self._connect()) as db:
            rows = db.execute("SELECT * FROM ticket_comments WHERE ticket_id = ? ORDER BY id", (ticket_id,)).fetchall()
        return [dict(row) for row in rows]

    def get_group(self, group_id: int) -> dict[str, Any] | None:
        if not self._path.exists():
            return None
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM ticket_groups WHERE id = ?", (group_id,)).fetchone()
        return _group(row) if row else None

    def group_counts(self, group_id: int, since: str) -> tuple[int, int]:
        if not self._path.exists():
            return 0, 0
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT COUNT(*), COALESCE(SUM(created_at >= ?), 0) FROM tickets WHERE group_id = ?",
                (since, group_id),
            ).fetchone()
        return row[0], row[1]

    def list_groups(
        self, *, since: str, status: str | None = None, tag: str | None = None,
        priority: str | None = None, limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        where: list[str] = []
        args: list[Any] = []
        if status:
            where.append("EXISTS (SELECT 1 FROM tickets x WHERE x.group_id = g.id AND x.status = ?)")
            args.append(status)
        if tag:
            where.append(
                "EXISTS (SELECT 1 FROM tickets x, json_each(x.tags) j WHERE x.group_id = g.id AND j.value = ?)"
            )
            args.append(tag)
        if priority:
            where.append("g.priority = ?")
            args.append(priority)
        sql = (
            "SELECT g.*, COUNT(t.id) AS ticket_count, "
            "COALESCE(SUM(t.created_at >= ?), 0) AS recent_count, "
            f"COALESCE(SUM(t.{_OPEN}), 0) AS open_count, MAX(t.updated_at) AS last_activity "
            "FROM ticket_groups g JOIN tickets t ON t.group_id = g.id"
            + (" WHERE " + " AND ".join(where) if where else "")
            + " GROUP BY g.id ORDER BY last_activity DESC, g.id DESC LIMIT ?"
        )
        with closing(self._connect()) as db:
            rows = db.execute(sql, (since, *args, limit)).fetchall()
            groups = [_group(row) for row in rows]
            for group in groups:
                tag_rows = db.execute(
                    "SELECT DISTINCT j.value FROM tickets x, json_each(x.tags) j WHERE x.group_id = ? ORDER BY j.value",
                    (group["id"],),
                ).fetchall()
                group["tags"] = [r[0] for r in tag_rows]
        return groups

    def stats(self) -> dict[str, int]:
        if not self._path.exists():
            return {"open": 0, "urgent": 0, "groups": 0}
        with closing(self._connect()) as db:
            open_count = db.execute(f"SELECT COUNT(*) FROM tickets WHERE {_OPEN}").fetchone()[0]
            urgent = db.execute(
                f"SELECT COUNT(*) FROM tickets t JOIN ticket_groups g ON g.id = t.group_id "
                f"WHERE t.{_OPEN} AND (t.priority = 'urgent' OR g.priority = 'urgent')"
            ).fetchone()[0]
            groups = db.execute(f"SELECT COUNT(DISTINCT group_id) FROM tickets WHERE {_OPEN}").fetchone()[0]
        return {"open": open_count, "urgent": urgent, "groups": groups}
