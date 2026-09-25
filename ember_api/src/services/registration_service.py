"""Invite-only registration (mirrors chat_app's auth_service.register_account)."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Account, Role
from src.services.auth_service import hash_password
from src.services.otp_service import OtpService


class RegistrationError(ValueError):
    """Username or email already taken; the message is safe to show."""


class RegistrationService:
    def __init__(self, session: AsyncSession, otp: OtpService, default_role: str) -> None:
        self._session = session
        self._otp = otp
        self._default_role = default_role

    async def register(self, username: str, email: str, password: str, invite_code: str) -> Account | None:
        """The new (unverified) account, None for a bad/expired/used invite,
        or RegistrationError for a taken username/email.

        The invite is checked first, so whether a username exists is only
        revealed to invite holders. On any failure the invite stays unused.
        """
        invite = await self._otp.find_valid_invite(invite_code)
        if invite is None:
            return None

        taken = await self._taken_message(username, email)
        if taken:
            raise RegistrationError(taken)

        account = Account(username=username, email=email, password_hash=await hash_password(password))
        role = await self._session.scalar(select(Role).where(Role.name == self._default_role))
        if role is not None:
            account.roles.append(role)
        self._session.add(account)
        self._otp.mark_invite_used(invite)
        try:
            await self._session.commit()
        except IntegrityError as error:
            # Lost a race with a concurrent registration of the same name or
            # address; the rollback also restores the invite.
            await self._session.rollback()
            raise RegistrationError(
                await self._taken_message(username, email) or "Username or email is already registered"
            ) from error
        return account

    async def _taken_message(self, username: str, email: str) -> str | None:
        clash = await self._session.scalar(
            select(Account).where(or_(Account.username == username, Account.email == email))
        )
        if clash is None:
            return None
        return "Username is already taken" if clash.username == username else "Email is already registered"
