"""In-memory catalog state: cache-first at boot, refreshed in the
background. Module-level mutable state, single-process only - same
deliberate exception ai_agent/src/llm/cooldown.py documents for its own
module-level cooldown dict.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from src import cache, scanner

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_entries: list[dict] = []
_status: str = "scanning"


def load_initial(cache_path: Path) -> None:
    """Cache-first boot: serve whatever was on disk from the last run
    immediately. Leaves status "scanning" (the default) when no cache
    exists yet - the first refresh() call will populate it."""
    global _entries, _status
    cached = cache.load_cache(cache_path)
    if cached is not None:
        with _lock:
            _entries = cached
            _status = "ready"


def current() -> tuple[str, list[dict]]:
    with _lock:
        return _status, list(_entries)


def get_by_id(entry_id: str) -> dict | None:
    with _lock:
        return next((entry for entry in _entries if entry["id"] == entry_id), None)


def refresh(sources: list[tuple[str, Path]], cache_path: Path) -> None:
    """Fire-and-forget: marks status "scanning" immediately, then rescans
    every configured project on a background daemon thread. Returns before
    the scan finishes - callers (routes.py's POST /catalog/refresh, and
    run.py at boot) never block on it."""
    global _status
    with _lock:
        _status = "scanning"
    threading.Thread(target=_run_refresh, args=(sources, cache_path), daemon=True).start()


def _run_refresh(sources: list[tuple[str, Path]], cache_path: Path) -> None:
    """Runs on the background thread started by refresh(). Any exception
    here (a scanner bug, a cache write failure, etc.) is caught and logged
    rather than left to kill the thread silently - otherwise the registry's
    status would wedge at "scanning" forever, since nothing else ever flips
    it back. On failure, the entries already being served (from the
    previous successful scan or the initial cache load) are left alone -
    they are only replaced once a scan completes successfully - so a failed
    refresh never clears previously-served data."""
    global _entries, _status
    try:
        scanned: list[dict] = []
        for project, root in sources:
            scanned.extend(entry.to_dict() for entry in scanner.scan_project(project, root))
        cache.save_cache_atomic(cache_path, scanned)
        with _lock:
            _entries = scanned
    except Exception:
        logger.exception("catalog refresh failed; continuing to serve previous entries")
    finally:
        with _lock:
            _status = "ready"
