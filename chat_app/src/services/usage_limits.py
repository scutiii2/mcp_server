"""Per-user LLM token usage limits: a rolling 6-hour cap and a rolling
7-day (weekly) cap, plus a configurable soft cap on how much context a
single chat is allowed to grow to before summarization.py's phase 5
auto-summarize kicks in (see __index__.py's _maybe_auto_summarize).

Values come from configs/config_usage_limits.json, loaded once at
import - same "tuning constants in a module" treatment summarization.py
already gives SUMMARY_TOKEN_CAP/AUTO_SUMMARIZE_THRESHOLD_RATIO, just
sourced from JSON here so they're adjustable without a code change.

Storage follows chats_store.py's exact convention: plain sqlite3, a
_connect(db_path) helper that creates the table if missing, one
open/close per public call, every function takes (db_path, username,
...). Kept in its own usage.db rather than chats.db - a distinct
concern from chat transcripts, with its own retention (rows older than
the weekly window are pruned on every check).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.utils.catalog import catalog
from src.utils.config_loader import load_json_config

_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "configs" / "config_usage_limits.json"
_config = load_json_config(_CONFIG_PATH)

SIX_HOUR_TOKEN_LIMIT: int = _config["six_hour_token_limit"]
WEEKLY_TOKEN_LIMIT: int = _config["weekly_token_limit"]
MAX_CONTEXT_TOKENS_PER_CHAT: int = _config["max_context_tokens_per_chat"]
# Max model<->tool rounds ai_agent may spend on one turn (sent with each ask).

_SIX_HOUR_WINDOW = timedelta(hours=6)
_WEEKLY_WINDOW = timedelta(days=7)


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS token_usage (
            username TEXT NOT NULL,
            ts TEXT NOT NULL,
            tokens INTEGER NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_token_usage_username_ts ON token_usage(username, ts)")
    conn.commit()
    return conn


def record_usage(db_path: Path, username: str, tokens: int) -> None:
    """Logs one turn's total_tokens against username. Called after a
    successful ask() turn - a blocked or errored turn never spent
    tokens, so never records one."""
    if not tokens:
        return
    conn = _connect(db_path)
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("INSERT INTO token_usage (username, ts, tokens) VALUES (?, ?, ?)", (username, now, tokens))
        conn.commit()
    finally:
        conn.close()


def get_usage(db_path: Path, username: str) -> dict:
    """Read-only snapshot for the context popover: tokens used, limit and
    reset time (ISO, None when the window holds no usage) per window.
    Unlike check_limit it never prunes."""
    conn = _connect(db_path)
    try:
        now = datetime.now(timezone.utc)
        snapshot = {}
        for key, window, limit in (
            ("six_hour", _SIX_HOUR_WINDOW, SIX_HOUR_TOKEN_LIMIT),
            ("weekly", _WEEKLY_WINDOW, WEEKLY_TOKEN_LIMIT),
        ):
            used, oldest_ts = conn.execute(
                "SELECT COALESCE(SUM(tokens), 0), MIN(ts) FROM token_usage WHERE username = ? AND ts >= ?",
                (username, (now - window).isoformat()),
            ).fetchone()
            reset_at = datetime.fromisoformat(oldest_ts) + window if oldest_ts else None
            snapshot[key] = {
                "used": used,
                "limit": limit,
                "reset_at": reset_at.isoformat() if reset_at else None,
            }
        return snapshot
    finally:
        conn.close()


@catalog
def check_limit(db_path: Path, username: str) -> tuple[bool, str | None, datetime | None]:
    """Returns (allowed, blocked_reason, reset_at). blocked_reason/reset_at
    are None when allowed is True. The 6-hour cap is checked first - it's
    the tighter, more commonly hit window; the weekly cap is the backstop.
    Prunes rows older than the weekly window on every call, so the table
    never grows past ~7 days of history per user."""
    conn = _connect(db_path)
    try:
        now = datetime.now(timezone.utc)
        weekly_cutoff = now - _WEEKLY_WINDOW
        conn.execute("DELETE FROM token_usage WHERE ts < ?", (weekly_cutoff.isoformat(),))
        conn.commit()

        six_hour_cutoff = now - _SIX_HOUR_WINDOW
        six_hour_total = conn.execute(
            "SELECT COALESCE(SUM(tokens), 0) FROM token_usage WHERE username = ? AND ts >= ?",
            (username, six_hour_cutoff.isoformat()),
        ).fetchone()[0]
        weekly_total = conn.execute(
            "SELECT COALESCE(SUM(tokens), 0) FROM token_usage WHERE username = ? AND ts >= ?",
            (username, weekly_cutoff.isoformat()),
        ).fetchone()[0]

        if six_hour_total >= SIX_HOUR_TOKEN_LIMIT:
            oldest_ts = conn.execute(
                "SELECT MIN(ts) FROM token_usage WHERE username = ? AND ts >= ?",
                (username, six_hour_cutoff.isoformat()),
            ).fetchone()[0]
            reset_at = datetime.fromisoformat(oldest_ts) + _SIX_HOUR_WINDOW
            return False, "6-hour token limit reached", reset_at

        if weekly_total >= WEEKLY_TOKEN_LIMIT:
            oldest_ts = conn.execute(
                "SELECT MIN(ts) FROM token_usage WHERE username = ? AND ts >= ?",
                (username, weekly_cutoff.isoformat()),
            ).fetchone()[0]
            reset_at = datetime.fromisoformat(oldest_ts) + _WEEKLY_WINDOW
            return False, "weekly token limit reached", reset_at

        return True, None, None
    finally:
        conn.close()
