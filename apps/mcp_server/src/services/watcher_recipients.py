"""Per-watcher email recipients.

One JSON file per watcher class, ``{state_dir}/{WatcherClass}/recipients.json``,
mapping watcher key -> list of addresses. Kept beside - not inside - the
class's ``instances/`` record folder so JobWatcher.resume_all()/list_watchers() (which glob
that folder for records) never mistake it for one, and so a record deleted
on stop doesn't take the recipients with it.

Runtime state, never committed (state dirs are gitignored).
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

_EMAIL_RE = re.compile(r"^[^@\s,;<>\"'&]+@[^@\s,;<>\"'&]+\.[^@\s,;<>\"'&]+$")
_lock = threading.Lock()


def parse_recipients(text: str) -> list[str]:
    """Split a comma/semicolon/whitespace separated string into unique,
    validated addresses (case-insensitive de-dupe, order kept). Raises
    ValueError naming the first malformed address."""
    seen: set[str] = set()
    result: list[str] = []
    for raw in re.split(r"[,;\s]+", text or ""):
        address = raw.strip()
        if not address or address.lower() in seen:
            continue
        if not _EMAIL_RE.match(address):
            raise ValueError(f"Not a valid email address: {address!r}")
        seen.add(address.lower())
        result.append(address)
    return result


def _path(state_dir: Path, watcher_class: str) -> Path:
    return state_dir / watcher_class / "recipients.json"


def _read(state_dir: Path, watcher_class: str) -> dict[str, list[str]]:
    try:
        data = json.loads(_path(state_dir, watcher_class).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def get_recipients(state_dir: Path, watcher_class: str, key: str) -> list[str]:
    return list(_read(state_dir, watcher_class).get(key, []))


def set_recipients(state_dir: Path, watcher_class: str, key: str, recipients: list[str]) -> None:
    with _lock:
        data = _read(state_dir, watcher_class)
        if recipients:
            data[key] = recipients
        else:
            data.pop(key, None)
        path = _path(state_dir, watcher_class)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename: a crash mid-write must not leave a truncated file,
        # which _read() would treat as "no recipients" and silently drop them all.
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, path)


def add_recipient(state_dir: Path, watcher_class: str, key: str, email: str) -> list[str]:
    """Append one address to a watcher's list (no-op if already present,
    case-insensitive). Returns the resulting list."""
    (address,) = parse_recipients(email) or [""]
    if not address or len(parse_recipients(email)) != 1:
        raise ValueError("Provide exactly one email address.")
    with _lock:
        current = _read(state_dir, watcher_class).get(key, [])
    if address.lower() not in {a.lower() for a in current}:
        current = [*current, address]
    set_recipients(state_dir, watcher_class, key, current)
    return current


def remove_recipient(state_dir: Path, watcher_class: str, key: str, email: str) -> tuple[list[str], bool]:
    """Drop one address (case-insensitive) from a watcher's list. Returns
    (resulting list, whether it was on the list)."""
    parsed = parse_recipients(email)
    if len(parsed) != 1:
        raise ValueError("Provide exactly one email address.")
    with _lock:
        current = _read(state_dir, watcher_class).get(key, [])
    remaining = [a for a in current if a.lower() != parsed[0].lower()]
    removed = len(remaining) != len(current)
    if removed:
        set_recipients(state_dir, watcher_class, key, remaining)
    return remaining, removed
