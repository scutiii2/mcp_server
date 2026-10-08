"""/api/settings: what the administrator has switched on for everyone.

Read-only for any logged-in account (the browser shows what is required of
it); administrators change a setting under /api/admin/settings."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.deps import current_account, get_settings_service
from src.models import Account
from src.services.settings_service import SettingsService

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
async def read_settings(
    _account: Account = Depends(current_account),
    app_settings: SettingsService = Depends(get_settings_service),
) -> dict[str, bool]:
    return await app_settings.all()
