"""/api/nav-preferences: how the logged-in account arranges its nav rail
(order, pinned and hidden pages). Any logged-in account; private to it."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from src.deps import current_account, get_db_session
from src.models import Account
from src.services.nav_preference_service import MAX_PAGES, PAGE_ID_MAX, NavLayout, NavPreferenceService

router = APIRouter(prefix="/api/nav-preferences", tags=["nav-preferences"])

PageId = Annotated[str, StringConstraints(min_length=1, max_length=PAGE_ID_MAX)]


def get_nav_service(
    account: Account = Depends(current_account),
    session: AsyncSession = Depends(get_db_session),
) -> NavPreferenceService:
    return NavPreferenceService(session, account.id)


class NavPreferencesBody(BaseModel):
    order: list[PageId] = Field(default_factory=list, max_length=MAX_PAGES)
    pinned: list[PageId] = Field(default_factory=list, max_length=MAX_PAGES)
    hidden: list[PageId] = Field(default_factory=list, max_length=MAX_PAGES)

    @classmethod
    def of(cls, layout: NavLayout) -> NavPreferencesBody:
        return cls(order=layout.order, pinned=layout.pinned, hidden=layout.hidden)


@router.get("")
async def read_nav_preferences(nav: NavPreferenceService = Depends(get_nav_service)) -> NavPreferencesBody:
    return NavPreferencesBody.of(await nav.get())


@router.put("")
async def save_nav_preferences(
    body: NavPreferencesBody, nav: NavPreferenceService = Depends(get_nav_service)
) -> NavPreferencesBody:
    """Replaces the whole arrangement; returns it as stored."""
    layout = await nav.replace(NavLayout(order=body.order, pinned=body.pinned, hidden=body.hidden))
    return NavPreferencesBody.of(layout)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def reset_nav_preferences(nav: NavPreferenceService = Depends(get_nav_service)) -> Response:
    await nav.reset()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
