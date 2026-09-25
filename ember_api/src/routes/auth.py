"""/api/auth: login, logout, and who-am-I."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings
from src.deps import current_account, get_db_session, get_session_service, get_settings
from src.models import Account
from src.services.auth_service import AuthService
from src.services.session_service import SessionService

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=1024)


class AccountOut(BaseModel):
    id: int
    username: str
    email: str
    email_verified: bool
    roles: list[str]
    permissions: list[str]

    @classmethod
    def of(cls, account: Account) -> AccountOut:
        return cls(
            id=account.id,
            username=account.username,
            email=account.email,
            email_verified=account.email_verified,
            roles=sorted(r.name for r in account.roles),
            permissions=sorted(account.permission_names),
        )


@router.post("/login")
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
    sessions: SessionService = Depends(get_session_service),
    settings: Settings = Depends(get_settings),
) -> AccountOut:
    auth = AuthService(db)
    check = await auth.verify_credentials(body.username, body.password)
    account = check.account
    ip_address = request.client.host if request.client else "unknown"
    await auth.record_login_attempt(ip_address, check.account_id, account is not None)
    if account is None:
        # One message for every failure reason, so usernames can't be probed.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")

    token = await sessions.create(account)
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_hours * 3600,
        httponly=True,  # page JavaScript can never read it
        samesite="strict",  # never sent on requests started by other sites
        secure=settings.cookie_secure,
        path="/",
    )
    return AccountOut.of(account)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    sessions: SessionService = Depends(get_session_service),
    settings: Settings = Depends(get_settings),
) -> None:
    """Always succeeds: logging out while already logged out is a no-op."""
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        await sessions.revoke(token)
    response.delete_cookie(settings.session_cookie_name, path="/")


@router.get("/me")
async def me(account: Account = Depends(current_account)) -> AccountOut:
    return AccountOut.of(account)
