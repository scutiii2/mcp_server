"""/api/logs: the Logs page (port of chat_app's pages/Logs).

Three kinds, each behind its own permission: "action" (logs.view),
"error" (logs.errors.view), "chat_trace" (logs.chat.view). Each is filtered
to one actor at a time - the server or one account - newest first, capped
at the 200 most recent."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.deps import get_db_session, require_any_permission
from src.models import Account, LogEntry
from src.services import log_service
from src.services.permissions import LOGS_CHAT_VIEW, LOGS_ERRORS_VIEW, LOGS_VIEW

router = APIRouter(prefix="/api/logs", tags=["logs"])

KIND_PERMISSIONS: dict[str, str] = {"action": LOGS_VIEW, "error": LOGS_ERRORS_VIEW, "chat_trace": LOGS_CHAT_VIEW}

require_any_logs = require_any_permission(*KIND_PERMISSIONS.values())


class LogEntryOut(BaseModel):
    id: int
    kind: str
    account_id: int | None
    source: str
    message: str
    details: str | None
    created_at: datetime

    @classmethod
    def of(cls, entry: LogEntry) -> LogEntryOut:
        return cls(
            id=entry.id,
            kind=entry.kind,
            account_id=entry.account_id,
            source=entry.source,
            message=entry.message,
            details=entry.details,
            created_at=entry.created_at,
        )


class ActorOut(BaseModel):
    id: int
    username: str


class LogsIndexOut(BaseModel):
    # The kinds this account may read, in tab order.
    kinds: list[str]
    accounts: list[ActorOut]


@router.get("")
async def logs_index(
    account: Account = Depends(require_any_logs),
    session: AsyncSession = Depends(get_db_session),
) -> LogsIndexOut:
    """What the page needs first: its tabs and every account to filter by
    (whether or not it has entries yet)."""
    accounts = await session.execute(select(Account.id, Account.username).order_by(Account.username))
    held = account.permission_names
    return LogsIndexOut(
        kinds=[kind for kind, permission in KIND_PERMISSIONS.items() if permission in held],
        accounts=[ActorOut(id=row.id, username=row.username) for row in accounts],
    )


@router.get("/{kind}")
async def list_logs(
    kind: Literal["action", "error", "chat_trace"],
    actor: str = Query(default="server", pattern=r"^(server|\d{1,12})$"),
    account: Account = Depends(require_any_logs),
    session: AsyncSession = Depends(get_db_session),
) -> list[LogEntryOut]:
    """actor: "server" or an account id."""
    if KIND_PERMISSIONS[kind] not in account.permission_names:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {KIND_PERMISSIONS[kind]}")
    account_id = None if actor == "server" else int(actor)
    return [LogEntryOut.of(e) for e in await log_service.list_entries(session, kind, account_id)]
