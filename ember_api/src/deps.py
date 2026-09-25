"""FastAPI dependencies: database session, current account, permission gates."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings
from src.db import Database
from src.models import Account
from src.services.email_service import EmailSender
from src.services.otp_service import OtpService
from src.services.session_service import SessionService


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    database: Database = request.app.state.database
    async for session in database.session():
        yield session


def get_session_service(
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> SessionService:
    return SessionService(session, settings.session_hours)


def get_otp_service(session: AsyncSession = Depends(get_db_session)) -> OtpService:
    return OtpService(session)


def get_email_sender(request: Request) -> EmailSender:
    return request.app.state.email_sender


async def current_account(
    request: Request,
    settings: Settings = Depends(get_settings),
    sessions: SessionService = Depends(get_session_service),
) -> Account:
    """The logged-in account, or 401."""
    token = request.cookies.get(settings.session_cookie_name)
    account = await sessions.resolve(token) if token else None
    if account is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not logged in")
    return account


def require_permission(name: str) -> Callable[..., Awaitable[Account]]:
    """Dependency factory: the logged-in account if it holds `name`, else 403.
    An unverified email counts as holding no permissions at all."""

    async def dependency(account: Account = Depends(current_account)) -> Account:
        if not account.email_verified:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Email not verified")
        if name not in account.permission_names:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {name}")
        return account

    return dependency
