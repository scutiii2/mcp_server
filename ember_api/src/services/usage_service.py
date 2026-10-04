"""Token usage: recording, the rolling 6-hour / weekly limits, and reports
for the Usage page (port of chat_app/src/services/usage_limits.py).

Rows are kept (limits only look at their own windows), so the Usage page
can show history. All times are naive UTC; the browser shows local time.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import UsageSettings
from src.db import utcnow
from src.models import Account, UsageRecord

SIX_HOURS = timedelta(hours=6)
WEEK = timedelta(days=7)
MAX_REPORT_DAYS = 366


@dataclass(frozen=True)
class LimitBlock:
    reason: str
    reset_at: datetime


@dataclass(frozen=True)
class Window:
    used: int
    limit: int  # 0 = unlimited
    reset_at: datetime | None


def _int(value: Any) -> int | None:
    return int(value) if isinstance(value, (int, float)) and value >= 0 else None


def _time(value: Any) -> datetime | None:
    """An ISO-8601 time from ai_agent ("...Z") as naive UTC; None when absent or unreadable."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed


def _text(value: Any, limit: int) -> str | None:
    return value[:limit] if isinstance(value, str) and value else None


# Keys of a usage row that are shown but not stored (no column).
_DISPLAY_ONLY = {"agent_label"}


def period_start(days: int, since_date: date | None = None) -> tuple[datetime, int]:
    """Where a report begins, and how many days it spans. A `since_date` (a UTC
    day, from its midnight: "this month" is the 1st) replaces `days`."""
    now = utcnow()
    if since_date is not None:
        start = datetime.combine(since_date, time.min)
        return start, max(1, min(math.ceil((now - start) / timedelta(days=1)), MAX_REPORT_DAYS))
    days = max(1, min(days, MAX_REPORT_DAYS))
    return now - timedelta(days=days), days


def usage_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per agent from an ask()/interpret() result: ask's
    `agent_usage` (own + delegated agents) when present, else its totals."""
    rows = []
    for entry in result.get("agent_usage") or []:
        if isinstance(entry, dict) and _int(entry.get("total_tokens")):
            agent_id = _text(entry.get("agent_id"), 120)
            provider_id = _text(entry.get("provider_id"), 60)
            rows.append(
                {
                    "agent": agent_id or provider_id,
                    "agent_id": agent_id,
                    "agent_label": _text(entry.get("agent_label"), 120),
                    "provider_id": provider_id,
                    "gateway": _text(entry.get("gateway"), 60),
                    "model": entry.get("model"),
                    "input_tokens": _int(entry.get("input_tokens")),
                    "output_tokens": _int(entry.get("output_tokens")),
                    "total_tokens": _int(entry.get("total_tokens")),
                    "started_at": _time(entry.get("started_at")),
                    "finished_at": _time(entry.get("finished_at")),
                    "delegated_by": _text(entry.get("delegated_by"), 120),
                }
            )
    if not rows and _int(result.get("total_tokens")):
        rows.append(
            {
                "agent": result.get("provider_id"),
                "agent_id": None,
                "agent_label": None,
                "provider_id": result.get("provider_id"),
                "gateway": None,
                "model": result.get("model"),
                "input_tokens": _int(result.get("input_tokens")),
                "output_tokens": _int(result.get("output_tokens")),
                "total_tokens": _int(result.get("total_tokens")),
                "started_at": None,
                "finished_at": None,
                "delegated_by": None,
            }
        )
    return rows


class UsageService:
    def __init__(self, session: AsyncSession, settings: UsageSettings) -> None:
        self._session = session
        self._settings = settings

    async def record(
        self, account_id: int, turn_id: str, kind: str, chat_id: str | None, result: dict[str, Any]
    ) -> int:
        """Stores the result's token usage; returns the total recorded."""
        now = utcnow()
        rows = usage_rows(result)
        for row in rows:
            stored = {k: v for k, v in row.items() if k not in _DISPLAY_ONLY}
            self._session.add(
                UsageRecord(account_id=account_id, turn_id=turn_id, kind=kind, chat_id=chat_id, created_at=now, **stored)
            )
        if rows:
            await self._session.commit()
        return sum(r["total_tokens"] for r in rows)

    async def _window(self, account_id: int, span: timedelta, limit: int) -> Window:
        since = utcnow() - span
        used, oldest = (
            await self._session.execute(
                select(func.coalesce(func.sum(UsageRecord.total_tokens), 0), func.min(UsageRecord.created_at)).where(
                    UsageRecord.account_id == account_id, UsageRecord.created_at >= since
                )
            )
        ).one()
        return Window(used=int(used), limit=limit, reset_at=oldest + span if oldest else None)

    async def windows(self, account_id: int) -> dict[str, Window]:
        s = self._settings
        return {
            "six_hour": await self._window(account_id, SIX_HOURS, s.six_hour_token_limit),
            "weekly": await self._window(account_id, WEEK, s.weekly_token_limit),
        }

    async def check(self, account_id: int) -> LimitBlock | None:
        """The tighter 6-hour window first, then the weekly backstop."""
        windows = await self.windows(account_id)
        for key, label in (("six_hour", "6-hour"), ("weekly", "weekly")):
            window = windows[key]
            if window.limit and window.used >= window.limit and window.reset_at:
                return LimitBlock(reason=f"{label} token limit reached", reset_at=window.reset_at)
        return None

    async def report(self, account_id: int, days: int, since_date: date | None = None) -> dict[str, Any]:
        since, days = period_start(days, since_date)
        rows = (
            await self._session.execute(
                select(
                    UsageRecord.created_at,
                    UsageRecord.turn_id,
                    UsageRecord.kind,
                    UsageRecord.chat_id,
                    UsageRecord.agent,
                    UsageRecord.model,
                    UsageRecord.input_tokens,
                    UsageRecord.output_tokens,
                    UsageRecord.total_tokens,
                )
                .where(UsageRecord.account_id == account_id, UsageRecord.created_at >= since)
                .order_by(UsageRecord.created_at)
            )
        ).all()

        daily: dict[str, int] = {}
        # Tokens by UTC hour of day, for the busiest hour.
        hourly = [0] * 24
        agents: dict[tuple[str, str], int] = {}
        turns: set[str] = set()
        chats: set[str] = set()
        total = input_total = output_total = summary_total = 0
        for created_at, turn_id, kind, chat_id, agent, model, input_tokens, output_tokens, tokens in rows:
            day = created_at.date().isoformat()
            daily[day] = daily.get(day, 0) + tokens
            hourly[created_at.hour] += tokens
            key = (agent or "unknown", model or "")
            agents[key] = agents.get(key, 0) + tokens
            if kind == "summary":
                summary_total += tokens
            else:
                turns.add(turn_id)
            if chat_id:
                chats.add(chat_id)
            total += tokens
            input_total += input_tokens or 0
            output_total += output_tokens or 0

        return {
            "days": days,
            "since": since,
            "total_tokens": total,
            "input_tokens": input_total,
            "output_tokens": output_total,
            "summary_tokens": summary_total,
            "turns": len(turns),
            "chats": len(chats),
            "by_agent": [
                {"agent": agent, "model": model, "tokens": tokens}
                for (agent, model), tokens in sorted(agents.items(), key=lambda item: -item[1])
            ],
            "daily": [{"date": day, "tokens": tokens} for day, tokens in sorted(daily.items())],
            "hourly": hourly,
        }

    async def all_accounts(self, days: int, since_date: date | None = None) -> list[dict[str, Any]]:
        """Per-account totals for admins, busiest first."""
        since, _ = period_start(days, since_date)
        rows = (
            await self._session.execute(
                select(
                    Account.id,
                    Account.username,
                    func.sum(UsageRecord.total_tokens),
                    func.count(func.distinct(UsageRecord.turn_id)),
                    func.max(UsageRecord.created_at),
                )
                .join(UsageRecord, UsageRecord.account_id == Account.id)
                .where(UsageRecord.created_at >= since)
                .group_by(Account.id, Account.username)
                .order_by(func.sum(UsageRecord.total_tokens).desc())
            )
        ).all()
        return [
            {"account_id": aid, "username": name, "tokens": int(tokens or 0), "turns": turns, "last_used_at": last}
            for aid, name, tokens, turns, last in rows
        ]
