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
concern from chat transcripts, with its own retention (kept
forever: the limit checks only look at their own windows, and the usage
tracker page shows the last 12 months of it).
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

# The tracker shows only this much history; older rows stay in usage.db.
SHOWN_HISTORY_MONTHS = 12

# Columns added after the first release; existing rows keep NULL in them.
_ADDED_COLUMNS = (
    ("agent", "TEXT"),
    ("model", "TEXT"),
    ("input_tokens", "INTEGER"),
    ("output_tokens", "INTEGER"),
    ("chat_id", "TEXT"),
)


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
    existing = {row[1] for row in conn.execute("PRAGMA table_info(token_usage)")}
    for name, sql_type in _ADDED_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE token_usage ADD COLUMN {name} {sql_type}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_token_usage_username_ts ON token_usage(username, ts)")
    conn.commit()
    return conn


def record_usage(
    db_path: Path,
    username: str,
    tokens: int,
    *,
    agent: str | None = None,
    model: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    chat_id: str | None = None,
    ts: str | None = None,
) -> None:
    """Logs one agent's tokens for a turn against username. Called after a
    successful ask() turn - a blocked or errored turn never spent
    tokens, so never records one. A turn that used delegated agents is
    recorded as one row per agent, all sharing the same `ts` so the tracker
    can count them as one turn."""
    if not tokens:
        return
    conn = _connect(db_path)
    try:
        now = ts or datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO token_usage (username, ts, tokens, agent, model, input_tokens, output_tokens, chat_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (username, now, tokens, agent, model, input_tokens, output_tokens, chat_id),
        )
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
        month_start = _calendar_month_start()
        snapshot["month"] = {
            "used": conn.execute(
                "SELECT COALESCE(SUM(tokens), 0) FROM token_usage WHERE username = ? AND ts >= ?",
                (username, month_start.astimezone(timezone.utc).isoformat()),
            ).fetchone()[0],
            "starts_at": month_start.isoformat(),
        }
        return snapshot
    finally:
        conn.close()


@catalog
def check_limit(db_path: Path, username: str) -> tuple[bool, str | None, datetime | None]:
    """Returns (allowed, blocked_reason, reset_at). blocked_reason/reset_at
    are None when allowed is True. The 6-hour cap is checked first - it's
    the tighter, more commonly hit window; the weekly cap is the backstop.
    Never deletes rows - history is kept for the usage tracker."""
    conn = _connect(db_path)
    try:
        now = datetime.now(timezone.utc)
        weekly_cutoff = now - _WEEKLY_WINDOW

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


def _calendar_month_start(now: datetime | None = None) -> datetime:
    """First instant of the current calendar month, in the server's local zone."""
    local = (now or datetime.now(timezone.utc)).astimezone()
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _months_back(start: datetime, months: int) -> datetime:
    total = start.year * 12 + (start.month - 1) - months
    return start.replace(year=total // 12, month=total % 12 + 1)


def range_start(range_key: str, now: datetime | None = None) -> datetime:
    """Local-zone start for a tracker range: "month" (calendar month to date),
    "7d", "30d" or "12m". Never earlier than the 12-month shown-history floor;
    an unknown key falls back to the calendar month."""
    local = (now or datetime.now(timezone.utc)).astimezone()
    month_start = _calendar_month_start(local)
    floor = _months_back(month_start, SHOWN_HISTORY_MONTHS - 1)
    if range_key == "7d":
        start = local - timedelta(days=7)
    elif range_key == "30d":
        start = local - timedelta(days=30)
    elif range_key == "12m":
        start = floor
    else:
        start = month_start
    return max(start, floor)


def usage_users(db_path: Path) -> list[str]:
    """Every username with recorded usage, for the tracker's user picker."""
    conn = _connect(db_path)
    try:
        return [row[0] for row in conn.execute("SELECT DISTINCT username FROM token_usage ORDER BY username")]
    finally:
        conn.close()


def usage_report(db_path: Path, username: str, range_key: str = "month") -> dict:
    """Aggregates one user's usage from range_start(range_key) to now, for the
    tracker page and the markdown export. Days and the peak hour use the
    server's local time zone."""
    start = range_start(range_key)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT ts, tokens, agent, model, input_tokens, output_tokens, chat_id FROM token_usage"
            " WHERE username = ? AND ts >= ? ORDER BY ts",
            (username, start.astimezone(timezone.utc).isoformat()),
        ).fetchall()
    finally:
        conn.close()

    daily: dict[str, int] = {}
    hours: dict[int, int] = {}
    agents: dict[tuple[str, str], int] = {}
    turns: set[str] = set()
    chats: set[str] = set()
    total = input_total = output_total = 0
    for ts, tokens, agent, model, input_tokens, output_tokens, chat_id in rows:
        local = datetime.fromisoformat(ts).astimezone()
        day = local.date().isoformat()
        daily[day] = daily.get(day, 0) + tokens
        hours[local.hour] = hours.get(local.hour, 0) + tokens
        key = (agent or "unknown", model or "")
        agents[key] = agents.get(key, 0) + tokens
        turns.add(ts)
        if chat_id:
            chats.add(chat_id)
        total += tokens
        input_total += input_tokens or 0
        output_total += output_tokens or 0

    by_agent = [
        {"agent": agent, "model": model, "tokens": tokens}
        for (agent, model), tokens in sorted(agents.items(), key=lambda item: -item[1])
    ]
    return {
        "range": range_key,
        "since": start.isoformat(),
        "total_tokens": total,
        "input_tokens": input_total,
        "output_tokens": output_total,
        "turns": len(turns),
        "chats": len(chats),
        "active_days": len(daily),
        "peak_hour": max(hours, key=hours.get) if hours else None,
        "favorite": by_agent[0] if by_agent else None,
        "by_agent": by_agent,
        "daily": daily,
    }
