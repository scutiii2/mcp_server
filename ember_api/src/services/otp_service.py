"""Invite and email-verification codes (mirrors chat_app/src/services/otp_service.py).

Codes are short random strings a person types; only their SHA-256 is
stored. Lookup is by that hash, so there's no per-candidate comparison to
time. Each code expires after CODE_EXPIRY and works once.
"""

from __future__ import annotations

import hashlib
import math
import secrets
from datetime import timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import utcnow
from src.models import Account, EmailVerificationCode, InviteCode

CODE_EXPIRY = timedelta(minutes=15)
CODE_LENGTH = 10
# Verification emails per account: one every VERIFICATION_COOLDOWN, and at most
# VERIFICATION_PER_HOUR in any hour, so resend and email changes cannot be used
# to flood an address.
VERIFICATION_COOLDOWN = timedelta(seconds=30)
VERIFICATION_PER_HOUR = 5


def generate_code() -> str:
    """10 URL-safe characters (~60 bits): easy to type, infeasible to guess
    within a 15-minute, single-use window."""
    return secrets.token_urlsafe(CODE_LENGTH)[:CODE_LENGTH]


def hash_code(code: str) -> str:
    return hashlib.sha256(code.strip().encode("utf-8")).hexdigest()


class OtpService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- invites ---------------------------------------------------------

    async def create_invite(
        self, created_by: Account, invitee_email: str | None, delivery_method: str
    ) -> tuple[InviteCode, str]:
        """Returns the row and the raw code; the raw code is never stored."""
        code = generate_code()
        invite = InviteCode(
            code_hash=hash_code(code),
            created_by_account_id=created_by.id,
            invitee_email=invitee_email,
            delivery_method=delivery_method,
            expires_at=utcnow() + CODE_EXPIRY,
        )
        self._session.add(invite)
        await self._session.commit()
        return invite, code

    async def find_valid_invite(self, code: str) -> InviteCode | None:
        return await self._session.scalar(
            select(InviteCode).where(
                InviteCode.code_hash == hash_code(code),
                InviteCode.used_at.is_(None),
                InviteCode.expires_at > utcnow(),
            )
        )

    def mark_invite_used(self, invite: InviteCode) -> None:
        """Marks only; the caller commits, so registration and consuming the
        invite succeed or fail together."""
        invite.used_at = utcnow()

    async def open_invites(self) -> list[InviteCode]:
        return list(
            await self._session.scalars(
                select(InviteCode)
                .where(InviteCode.used_at.is_(None), InviteCode.expires_at > utcnow())
                .order_by(InviteCode.created_at.desc())
            )
        )

    # --- email verification ----------------------------------------------

    async def create_email_verification(self, account: Account) -> tuple[EmailVerificationCode, str]:
        """A new code; earlier unused ones stay valid until they expire, so a
        delayed first email still works after a resend."""
        code = generate_code()
        row = EmailVerificationCode(
            code_hash=hash_code(code),
            account_id=account.id,
            expires_at=utcnow() + CODE_EXPIRY,
        )
        self._session.add(row)
        await self._session.commit()
        return row, code

    async def verification_wait(self, account: Account) -> int | None:
        """Seconds until another verification email may be sent to `account`,
        or None when one may be sent now."""
        now = utcnow()
        created = list(
            await self._session.scalars(
                select(EmailVerificationCode.created_at)
                .where(
                    EmailVerificationCode.account_id == account.id,
                    EmailVerificationCode.created_at > now - timedelta(hours=1),
                )
                .order_by(EmailVerificationCode.created_at.desc())
            )
        )
        waits = []
        if created:
            waits.append((created[0] + VERIFICATION_COOLDOWN - now).total_seconds())
        if len(created) >= VERIFICATION_PER_HOUR:
            waits.append((created[VERIFICATION_PER_HOUR - 1] + timedelta(hours=1) - now).total_seconds())
        longest = max(waits, default=0)
        return math.ceil(longest) if longest > 0 else None

    async def discard_email_verification(self, account: Account) -> None:
        """Voids the account's unused codes. Called when its email changes: a
        code was sent to the old address and must not verify the new one."""
        await self._session.execute(
            delete(EmailVerificationCode).where(
                EmailVerificationCode.account_id == account.id, EmailVerificationCode.used_at.is_(None)
            )
        )
        await self._session.commit()

    async def consume_email_verification(self, account: Account, code: str) -> bool:
        """Marks the account verified if `code` is one of its valid codes."""
        row = await self._session.scalar(
            select(EmailVerificationCode).where(
                EmailVerificationCode.account_id == account.id,
                EmailVerificationCode.code_hash == hash_code(code),
                EmailVerificationCode.used_at.is_(None),
                EmailVerificationCode.expires_at > utcnow(),
            )
        )
        if row is None:
            return False
        row.used_at = utcnow()
        account.email_verified = True
        await self._session.commit()
        return True

    # --- housekeeping -----------------------------------------------------

    async def purge_stale(self) -> None:
        """Drops expired or used codes; nothing reads them afterwards."""
        now = utcnow()
        for model in (InviteCode, EmailVerificationCode):
            await self._session.execute(
                delete(model).where(or_(model.expires_at <= now, model.used_at.is_not(None)))
            )
        await self._session.commit()
