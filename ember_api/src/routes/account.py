"""/api/account: the logged-in user changes their own email or password.

Any logged-in account may call these, verified or not - an unverified user
who mistyped their email needs exactly this to fix it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings
from src.deps import current_account, get_db_session, get_email_sender, get_otp_service, get_session_service, get_settings
from src.models import Account
from src.routes.auth import AccountOut, send_verification_code
from src.services.account_service import AccountChangeError, AccountService, WrongPasswordError
from src.services.email_service import EmailSender
from src.services.otp_service import OtpService
from src.services.session_service import SessionService

router = APIRouter(prefix="/api/account", tags=["account"])


class ChangeEmailRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    email: EmailStr


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=8, max_length=1024)


class EmailChangedOut(BaseModel):
    account: AccountOut
    # False when SMTP failed; resend on the verify page can retry.
    verification_email_sent: bool
    email_error: str | None = None


def get_account_service(session: AsyncSession = Depends(get_db_session)) -> AccountService:
    return AccountService(session)


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, WrongPasswordError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(error))
    return HTTPException(status.HTTP_409_CONFLICT, str(error))


@router.post("/email")
async def change_email(
    body: ChangeEmailRequest,
    account: Account = Depends(current_account),
    accounts: AccountService = Depends(get_account_service),
    otp: OtpService = Depends(get_otp_service),
    email: EmailSender = Depends(get_email_sender),
) -> EmailChangedOut:
    """The new email starts unverified, so permissions are off until the
    emailed code is entered on the verify page."""
    try:
        changed = await accounts.change_email(account, body.current_password, str(body.email))
    except (AccountChangeError, WrongPasswordError) as error:
        raise _http_error(error) from error
    error = await send_verification_code(account, otp, email) if changed else None
    return EmailChangedOut(
        account=AccountOut.of(account),
        verification_email_sent=changed and error is None,
        email_error=error,
    )


@router.post("/password")
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    account: Account = Depends(current_account),
    accounts: AccountService = Depends(get_account_service),
    sessions: SessionService = Depends(get_session_service),
    settings: Settings = Depends(get_settings),
) -> AccountOut:
    """Every other session of this account is logged out; this one stays."""
    try:
        await accounts.change_password(account, body.current_password, body.new_password)
    except (AccountChangeError, WrongPasswordError) as error:
        raise _http_error(error) from error
    # current_account already proved the cookie is there and valid.
    await sessions.revoke_others(account.id, request.cookies[settings.session_cookie_name])
    return AccountOut.of(account)
