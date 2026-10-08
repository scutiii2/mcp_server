"""/api/usage: the logged-in account's token usage and limits (chat.use),
and /api/admin/usage: every account's totals (usage.all.view)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings
from src.deps import get_db_session, get_settings, require_permission
from src.models import Account, UsageRecord
from src.services.permissions import USAGE_ALL_VIEW, CHAT_USE
from src.db import utcnow
from src.services.usage_service import MAX_REPORT_DAYS, UsageService, Window

router = APIRouter(tags=["usage"])

require_chat = require_permission(CHAT_USE)
require_admin = require_permission(USAGE_ALL_VIEW)


def get_usage_service(
    session: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings)
) -> UsageService:
    return UsageService(session, settings.usage)


def check_since(since: date | None) -> date | None:
    """`since` (a UTC day) must not be in the future or older than the longest report."""
    if since is None:
        return None
    today = utcnow().date()
    if since > today:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "since must not be in the future")
    if today - since > timedelta(days=MAX_REPORT_DAYS):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"since must be within the last {MAX_REPORT_DAYS} days")
    return since


class WindowOut(BaseModel):
    used: int
    # 0 = unlimited.
    limit: int
    # When the oldest tokens in the window stop counting; null when empty.
    reset_at: datetime | None

    @classmethod
    def of(cls, window: Window) -> WindowOut:
        return cls(used=window.used, limit=window.limit, reset_at=window.reset_at)


class UsageOut(BaseModel):
    six_hour: WindowOut
    weekly: WindowOut
    report: dict[str, Any]


class AccountUsageOut(BaseModel):
    account_id: int
    username: str
    tokens: int
    turns: int
    last_used_at: datetime | None


class UsageRecordOut(BaseModel):
    id: int
    turn_id: str
    kind: str
    chat_id: str | None
    agent: str | None
    agent_id: str | None
    provider_id: str | None
    gateway: str | None
    model: str | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int
    started_at: datetime | None
    finished_at: datetime | None
    delegated_by: str | None
    created_at: datetime

    @classmethod
    def of(cls, row: UsageRecord) -> UsageRecordOut:
        return cls(**{name: getattr(row, name) for name in cls.model_fields})


@router.get("/api/usage")
async def my_usage(
    days: int = Query(default=30, ge=1, le=366),
    since: date | None = Query(default=None),
    group_by: Literal["agent", "provider", "gateway", "model"] = Query(default="agent"),
    agent: str | None = Query(default=None, max_length=120),
    provider: str | None = Query(default=None, max_length=60),
    account: Account = Depends(require_chat),
    usage: UsageService = Depends(get_usage_service),
) -> UsageOut:
    windows = await usage.windows(account.id)
    return UsageOut(
        six_hour=WindowOut.of(windows["six_hour"]),
        weekly=WindowOut.of(windows["weekly"]),
        report=await usage.report(
            account.id, days, check_since(since), group_by=group_by, agent=agent, provider=provider
        ),
    )


@router.get("/api/usage/records")
async def my_usage_records(
    days: int = Query(default=30, ge=1, le=366),
    since: date | None = Query(default=None),
    agent: str | None = Query(default=None, max_length=120),
    provider: str | None = Query(default=None, max_length=60),
    limit: int = Query(default=100, ge=1, le=500),
    account: Account = Depends(require_chat),
    usage: UsageService = Depends(get_usage_service),
) -> list[UsageRecordOut]:
    rows = await usage.records(account.id, days, check_since(since), agent=agent, provider=provider, limit=limit)
    return [UsageRecordOut.of(row) for row in rows]


@router.get("/api/admin/usage")
async def all_usage(
    days: int = Query(default=30, ge=1, le=366),
    since: date | None = Query(default=None),
    _admin: Account = Depends(require_admin),
    usage: UsageService = Depends(get_usage_service),
) -> list[AccountUsageOut]:
    return [AccountUsageOut(**row) for row in await usage.all_accounts(days, check_since(since))]
