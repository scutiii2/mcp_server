"""JSON file cache for the scanned catalog entries.

Writes are atomic (temp file + os.replace) so a concurrent GET /catalog
never observes a half-written file - see Global Constraints in
docs/superpowers/plans/2026-09-13-catalog-service.md.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def load_cache(path: Path) -> list[dict] | None:
    """Returns the cached entry-dicts, or None if no cache file exists yet
    (first run), the file is unreadable/corrupt, or its content isn't a
    list of entry-dicts (e.g. valid JSON that's an object, or a list with
    a non-dict element). Treating that shape mismatch as "corrupt" (rather
    than assigning it straight into the registry) keeps the "corrupt cache
    = None = registry stays in scanning state until first real refresh"
    contract intact instead of serving garbage as "ready"."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        return None
    return data


def save_cache_atomic(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
            json.dump(entries, tmp_file)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        os.unlink(tmp_name)
        raise
