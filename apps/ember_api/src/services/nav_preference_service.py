"""Per-account nav rail arrangement: page order, pinned pages, hidden pages.

Every lookup filters by account. The service holds only ids and does not know
which pages exist; it keeps the lists small and consistent.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from src.db import utcnow
from src.models import NavPreference

MAX_PAGES = 50
PAGE_ID_MAX = 64


@dataclass(frozen=True)
class NavLayout:
    order: list[str] = field(default_factory=list)
    pinned: list[str] = field(default_factory=list)
    hidden: list[str] = field(default_factory=list)


def _unique(ids: list[str]) -> list[str]:
    return list(dict.fromkeys(ids))


def normalize(layout: NavLayout) -> NavLayout:
    """Drops repeats; pinned and hidden may only name pages in the order, and a
    page cannot be both (hiding wins, since a hidden page is not in the rail)."""
    order = _unique(layout.order)
    known = set(order)
    hidden = [p for p in _unique(layout.hidden) if p in known]
    pinned = [p for p in _unique(layout.pinned) if p in known and p not in hidden]
    return NavLayout(order=order, pinned=pinned, hidden=hidden)


class NavPreferenceService:
    def __init__(self, session: AsyncSession, account_id: int) -> None:
        self._session = session
        self._account_id = account_id

    async def get(self) -> NavLayout:
        row = await self._session.get(NavPreference, self._account_id)
        if row is None:
            return NavLayout()
        return NavLayout(order=list(row.page_order), pinned=list(row.pinned), hidden=list(row.hidden))

    async def replace(self, layout: NavLayout) -> NavLayout:
        layout = normalize(layout)
        row = await self._session.get(NavPreference, self._account_id)
        if row is None:
            row = NavPreference(account_id=self._account_id)
            self._session.add(row)
        row.page_order = layout.order
        row.pinned = layout.pinned
        row.hidden = layout.hidden
        row.updated_at = utcnow()
        await self._session.commit()
        return layout

    async def reset(self) -> None:
        row = await self._session.get(NavPreference, self._account_id)
        if row is not None:
            await self._session.delete(row)
            await self._session.commit()
