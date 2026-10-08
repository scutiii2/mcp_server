"""Settings an administrator changes for everyone, kept in the database.

Every setting is a yes/no switch listed in `BOOLEAN_SETTINGS` with its
default. A setting nobody changed has no row and reads as its default.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import utcnow
from src.models import AppSetting

# Every account's answers ask before each tool runs, whatever its browser sends.
FORCE_TOOL_APPROVAL = "force_tool_approval"

BOOLEAN_SETTINGS: dict[str, bool] = {FORCE_TOOL_APPROVAL: False}

_TRUE, _FALSE = "1", "0"


class UnknownSetting(KeyError):
    """A name that is not in BOOLEAN_SETTINGS."""


class SettingsService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def all(self) -> dict[str, bool]:
        stored = {row.name: row.value for row in await self._session.scalars(select(AppSetting))}
        return {name: (stored[name] == _TRUE if name in stored else default) for name, default in BOOLEAN_SETTINGS.items()}

    async def get_bool(self, name: str) -> bool:
        if name not in BOOLEAN_SETTINGS:
            raise UnknownSetting(name)
        row = await self._session.get(AppSetting, name)
        return BOOLEAN_SETTINGS[name] if row is None else row.value == _TRUE

    async def set_bool(self, name: str, value: bool) -> bool:
        """Saves the setting and returns what it was before."""
        before = await self.get_bool(name)
        row = await self._session.get(AppSetting, name)
        text = _TRUE if value else _FALSE
        if row is None:
            self._session.add(AppSetting(name=name, value=text))
        else:
            row.value = text
            row.updated_at = utcnow()
        await self._session.commit()
        return before
