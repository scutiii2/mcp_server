"""/api/account: the logged-in user changes their own email or password,
and sees (or forgets) the devices they logged in from.

Any logged-in account may call these, verified or not - an unverified user
who mistyped their email needs exactly this to fix it.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings
from src.deps import (
    current_account,
    get_db_session,
    get_email_sender,
    get_log_writer,
    get_otp_service,
    get_session_service,
    get_settings,
)
from src.models import Account
from src.security import client_ip
from src.routes.auth import AccountOut, device_signals, raise_if_verification_too_soon, send_verification_code
from src.services.account_service import AccountChangeError, AccountService, WrongPasswordError
from src.services.auth_service import AuthService
from src.services.device_service import DeviceService, describe
from src.services.email_service import EmailSender
from src.services.log_service import LogWriter
from src.services.otp_service import OtpService
from src.services.rate_limiter import LoginRateLimiter
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


class DeviceOut(BaseModel):
    id: int
    # "Firefox on Windows"
    label: str
    user_agent: str
    ip_subnet: str
    first_seen_at: datetime
    last_seen_at: datetime
    # The device this request comes from.
    current: bool


def get_account_service(session: AsyncSession = Depends(get_db_session)) -> AccountService:
    return AccountService(session)


def get_device_service(
    session: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings)
) -> DeviceService:
    return DeviceService(session, settings.security.fingerprint_signals)


async def _guard_password_checks(request: Request, db: AsyncSession, settings: Settings, account: Account) -> None:
    """The login lockout also covers the "current password" these routes ask
    for: a stolen session must not be able to guess the password here, where
    the login route's limit would never see it."""
    retry_after = await LoginRateLimiter(db, settings.security).retry_after(client_ip(request), account.id)
    if retry_after is not None:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many wrong passwords. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )


async def _record_wrong_password(request: Request, db: AsyncSession, account: Account) -> None:
    await AuthService(db).record_login_attempt(client_ip(request), account.id, False)


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, WrongPasswordError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(error))
    return HTTPException(status.HTTP_409_CONFLICT, str(error))


@router.post("/email")
async def change_email(
    body: ChangeEmailRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    account: Account = Depends(current_account),
    accounts: AccountService = Depends(get_account_service),
    otp: OtpService = Depends(get_otp_service),
    email: EmailSender = Depends(get_email_sender),
    logs: LogWriter = Depends(get_log_writer),
) -> EmailChangedOut:
    """The new email starts unverified, so permissions are off until the
    emailed code is entered on the verify page."""
    await _guard_password_checks(request, db, settings, account)
    raise_if_verification_too_soon(await otp.verification_wait(account))
    try:
        changed = await accounts.change_email(account, body.current_password, str(body.email))
    except WrongPasswordError as error:
        await _record_wrong_password(request, db, account)
        raise _http_error(error) from error
    except AccountChangeError as error:
        raise _http_error(error) from error
    if changed:
        # Codes sent to the old address must not verify the new one.
        await otp.discard_email_verification(account)
        await logs.action(account, "account.email", f"Changed email to {account.email}")
    error = await send_verification_code(account, otp, email) if changed else None
    return EmailChangedOut(
        account=AccountOut.of(account, settings),
        verification_email_sent=changed and error is None,
        email_error=error,
    )


@router.post("/password")
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    account: Account = Depends(current_account),
    accounts: AccountService = Depends(get_account_service),
    sessions: SessionService = Depends(get_session_service),
    settings: Settings = Depends(get_settings),
    logs: LogWriter = Depends(get_log_writer),
) -> AccountOut:
    """Every other session of this account is logged out; this one stays."""
    await _guard_password_checks(request, db, settings, account)
    try:
        await accounts.change_password(account, body.current_password, body.new_password)
    except WrongPasswordError as error:
        await _record_wrong_password(request, db, account)
        raise _http_error(error) from error
    except AccountChangeError as error:
        raise _http_error(error) from error
    # current_account already proved the cookie is there and valid.
    await sessions.revoke_others(account.id, request.cookies[settings.session_cookie_name])
    await logs.action(account, "account.password", "Changed password; other sessions logged out")
    return AccountOut.of(account, settings)


@router.get("/devices")
async def list_devices(
    request: Request,
    account: Account = Depends(current_account),
    devices: DeviceService = Depends(get_device_service),
) -> list[DeviceOut]:
    """Devices this account logged in from, most recently used first."""
    current = devices.fingerprint(device_signals(request))
    return [
        DeviceOut(
            id=d.id,
            label=describe(d.user_agent),
            user_agent=d.user_agent,
            ip_subnet=d.ip_subnet,
            first_seen_at=d.first_seen_at,
            last_seen_at=d.last_seen_at,
            current=d.fingerprint_hash == current,
        )
        for d in await devices.list(account.id)
    ]


@router.delete("/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def forget_device(
    device_id: int = Path(ge=1),
    account: Account = Depends(current_account),
    devices: DeviceService = Depends(get_device_service),
    logs: LogWriter = Depends(get_log_writer),
) -> Response:
    """The next login from it counts as a new device again."""
    if not await devices.forget(account.id, device_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Device not found")
    await logs.action(account, "account.device_forget", f"Forgot device {device_id}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
