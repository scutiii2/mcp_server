"""Read-only access to logging_setup/errors.py/session_log.py's output,
for the Logs page (pages/logs/) - the one place in the app that reads
another user's data by design, so every entry point here is gated by
security.py's EXECUTIVE_ENDPOINTS check before a request ever reaches it.

username/chat_id/reference all arrive from the URL, so every function
here validates its own arguments against the same safe-charset rule
session_log.py already writes with - not because a value that fails the
check couldn't be resolved safely (Path.resolve() plus a prefix check
would work too), but because a strict allowlist is simpler to convince
yourself is correct than "resolve and hope the prefix check catches
everything a resolver might do differently across platforms."
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _is_safe_segment(name: str) -> bool:
    return bool(_SAFE_SEGMENT_RE.match(name))


def _mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def list_chat_log_users(log_dir: Path) -> list[str]:
    chats_dir = log_dir / "chats"
    if not chats_dir.is_dir():
        return []
    return sorted(p.name for p in chats_dir.iterdir() if p.is_dir())


def list_user_chat_logs(log_dir: Path, username: str) -> list[dict[str, Any]]:
    """One entry per chat this user has a trace for - newest activity
    first. Empty (not an error) for an unsafe or unknown username, same
    reasoning as list_chats() returning an empty list for a user with no
    chats rather than distinguishing "no chats" from "no such user"."""
    if not _is_safe_segment(username):
        return []
    user_dir = log_dir / "chats" / username
    if not user_dir.is_dir():
        return []
    entries = [
        {"chat_id": f.stem, "updated_at": _mtime_iso(f), "size": f.stat().st_size}
        for f in user_dir.glob("*.jsonl")
    ]
    entries.sort(key=lambda e: e["updated_at"], reverse=True)
    return entries


def read_chat_log(log_dir: Path, username: str, chat_id: str) -> list[dict[str, Any]] | None:
    """Parsed turns, oldest first (the file's own append order) - None
    for an unsafe/unknown username or chat_id, distinguished from "empty
    log" (an empty list) so the route can 404 correctly."""
    if not _is_safe_segment(username) or not _is_safe_segment(chat_id):
        return None
    path = log_dir / "chats" / username / f"{chat_id}.jsonl"
    if not path.is_file():
        return None
    turns = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            turns.append(json.loads(line))
        except json.JSONDecodeError:
            # A single malformed line (shouldn't happen - this file is
            # only ever appended to by session_log.record_turn) must not
            # take the rest of a real conversation's trace down with it.
            continue
    return turns


def list_error_logs(log_dir: Path) -> list[dict[str, Any]]:
    errors_dir = log_dir / "errors"
    if not errors_dir.is_dir():
        return []
    entries = [
        {"reference": f.stem, "created_at": _mtime_iso(f), "size": f.stat().st_size}
        for f in errors_dir.glob("*.log")
    ]
    entries.sort(key=lambda e: e["created_at"], reverse=True)
    return entries


def read_error_log(log_dir: Path, reference: str) -> str | None:
    if not _is_safe_segment(reference):
        return None
    path = log_dir / "errors" / f"{reference}.log"
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")
