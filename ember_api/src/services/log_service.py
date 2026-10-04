"""The Logs page's entries (port of chat_app/src/services/log_service.py).

LogWriter opens its own session per write, so a log line is committed on
its own - it can be written from a route (after that route's own commit),
from a background chat turn, or from the error handler - and a failure to
write it is only logged, never raised: logging must not break the thing
being logged.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Literal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import Database, utcnow
from src.models import Account, LogEntry

logger = logging.getLogger(__name__)

LogKind = Literal["action", "error", "chat_trace"]

SOURCE_MAX = 100
MESSAGE_MAX = 500
DETAILS_MAX = 20_000
# Older entries are deleted on startup.
RETENTION_DAYS = 90
LIST_LIMIT = 200


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


class LogWriter:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def write(
        self, kind: LogKind, account_id: int | None, source: str, message: str, details: str | None = None
    ) -> None:
        try:
            async with self._database.sessions() as session:
                session.add(
                    LogEntry(
                        kind=kind,
                        account_id=account_id,
                        source=_clip(source, SOURCE_MAX),
                        message=_clip(message, MESSAGE_MAX),
                        details=_clip(details, DETAILS_MAX) if details else None,
                    )
                )
                await session.commit()
        except Exception:  # noqa: BLE001 - see the module docstring
            logger.exception("writing a %s log entry (%s) failed", kind, source)

    async def action(self, account: Account, source: str, message: str) -> None:
        """Something an account did (login, a change it made)."""
        await self.write("action", account.id, source, message)

    async def error(self, account_id: int | None, source: str, message: str, details: str | None = None) -> None:
        await self.write("error", account_id, source, message, details)

    async def chat_trace(self, account_id: int, message: str, details: str) -> None:
        await self.write("chat_trace", account_id, "chat.turn", message, details)

    async def purge_old(self) -> int:
        cutoff = utcnow() - timedelta(days=RETENTION_DAYS)
        async with self._database.sessions() as session:
            result = await session.execute(delete(LogEntry).where(LogEntry.created_at < cutoff))
            await session.commit()
            return result.rowcount or 0


async def list_entries(
    session: AsyncSession, kind: LogKind, account_id: int | None, limit: int = LIST_LIMIT
) -> list[LogEntry]:
    """Newest first; account_id None = the server's own entries."""
    query = select(LogEntry).where(LogEntry.kind == kind)
    query = query.where(LogEntry.account_id.is_(None) if account_id is None else LogEntry.account_id == account_id)
    return list(await session.scalars(query.order_by(LogEntry.created_at.desc(), LogEntry.id.desc()).limit(limit)))
