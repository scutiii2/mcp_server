"""FastAPI dependencies: database session, current account, permission gates."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings
from src.db import Database
from src.models import Account
from src.services.agent_gateway import AgentGateway
from src.services.email_service import EmailSender
from src.services.log_service import LogWriter
from src.services.otp_service import OtpService
from src.services.session_service import SessionService
from src.services.turns import TurnRegistry


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


def get_agent_gateway(request: Request) -> AgentGateway:
    return request.app.state.agent_gateway


def get_turns(request: Request) -> TurnRegistry:
    return request.app.state.turns


def get_log_writer(request: Request) -> LogWriter:
    return request.app.state.logs


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
    # For the error log, should this request fail unexpectedly.
    request.state.account_id = account.id
    return account


def require_permission(name: str) -> Callable[..., Awaitable[Account]]:
    """Dependency factory: the logged-in account if it holds `name`, else 403.
    An unverified email counts as holding no permissions at all."""
    return require_any_permission(name)


def require_any_permission(*names: str) -> Callable[..., Awaitable[Account]]:
    """Like require_permission, satisfied by any one of `names`."""

    async def dependency(account: Account = Depends(current_account)) -> Account:
        if not account.email_verified:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Email not verified")
        if not account.permission_names.intersection(names):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {' or '.join(names)}")
        return account

    return dependency
