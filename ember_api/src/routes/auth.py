"""/api/auth: login, logout, who-am-I, invite registration, email verification."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings
from src.deps import (
    current_account,
    get_db_session,
    get_email_sender,
    get_otp_service,
    get_session_service,
    get_settings,
)
from src.models import Account
from src.services.auth_service import AuthService
from src.services.email_service import EmailDeliveryError, EmailSender
from src.services.otp_service import OtpService
from src.services.registration_service import RegistrationError, RegistrationService
from src.services.session_service import SessionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=1024)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=1024)
    invite_code: str = Field(min_length=1, max_length=64)


class VerifyEmailRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)


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


class RegisterOut(BaseModel):
    account: AccountOut
    # False when SMTP failed; the account exists anyway and resend can retry.
    verification_email_sent: bool
    email_error: str | None = None


class EmailSentOut(BaseModel):
    sent: bool


async def _start_session(response: Response, account: Account, sessions: SessionService, settings: Settings) -> None:
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


async def send_verification_code(account: Account, otp: OtpService, email: EmailSender) -> str | None:
    """Sends a fresh code; returns the error message if delivery failed."""
    row, code = await otp.create_email_verification(account)
    try:
        await email.send_email_verification(account.email, code, row.expires_at)
    except EmailDeliveryError as error:
        logger.warning("verification email to account %s failed: %s", account.id, error)
        return str(error)
    return None


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

    await _start_session(response, account, sessions, settings)
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


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
    otp: OtpService = Depends(get_otp_service),
    sessions: SessionService = Depends(get_session_service),
    email: EmailSender = Depends(get_email_sender),
    settings: Settings = Depends(get_settings),
) -> RegisterOut:
    """Creates the account, logs it in, and emails a verification code.
    Permissions stay inactive until the email is verified."""
    registration = RegistrationService(db, otp, settings.default_role)
    try:
        account = await registration.register(body.username, str(body.email), body.password, body.invite_code)
    except RegistrationError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    if account is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired invite code")

    # Logged in even if the email fails: the account is committed, and
    # resend lets the user retry once SMTP works (same as chat_app).
    await _start_session(response, account, sessions, settings)
    error = await send_verification_code(account, otp, email)
    return RegisterOut(account=AccountOut.of(account), verification_email_sent=error is None, email_error=error)


@router.post("/verify-email")
async def verify_email(
    body: VerifyEmailRequest,
    account: Account = Depends(current_account),
    otp: OtpService = Depends(get_otp_service),
) -> AccountOut:
    if account.email_verified:
        return AccountOut.of(account)
    if not await otp.consume_email_verification(account, body.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired code")
    return AccountOut.of(account)


@router.post("/verify-email/resend")
async def resend_verification(
    account: Account = Depends(current_account),
    otp: OtpService = Depends(get_otp_service),
    email: EmailSender = Depends(get_email_sender),
) -> EmailSentOut:
    if account.email_verified:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email is already verified")
    error = await send_verification_code(account, otp, email)
    if error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, error)
    return EmailSentOut(sent=True)
