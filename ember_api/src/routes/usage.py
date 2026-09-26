"""/api/usage: the logged-in account's token usage and limits (chat.use),
and /api/admin/usage: every account's totals (admin.manage)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings
from src.deps import get_db_session, get_settings, require_permission
from src.models import Account
from src.services.permissions import ADMIN_MANAGE, CHAT_USE
from src.services.usage_service import UsageService, Window

router = APIRouter(tags=["usage"])

require_chat = require_permission(CHAT_USE)
require_admin = require_permission(ADMIN_MANAGE)


def get_usage_service(
    session: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings)
) -> UsageService:
    return UsageService(session, settings.usage)


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


@router.get("/api/usage")
async def my_usage(
    days: int = Query(default=30, ge=1, le=366),
    account: Account = Depends(require_chat),
    usage: UsageService = Depends(get_usage_service),
) -> UsageOut:
    windows = await usage.windows(account.id)
    return UsageOut(
        six_hour=WindowOut.of(windows["six_hour"]),
        weekly=WindowOut.of(windows["weekly"]),
        report=await usage.report(account.id, days),
    )


@router.get("/api/admin/usage")
async def all_usage(
    days: int = Query(default=30, ge=1, le=366),
    _admin: Account = Depends(require_admin),
    usage: UsageService = Depends(get_usage_service),
) -> list[AccountUsageOut]:
    return [AccountUsageOut(**row) for row in await usage.all_accounts(days)]
