"""Login sessions: random cookie tokens, stored only as SHA-256 hashes."""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import utcnow
from src.models import Account, AuthSession


def _hash_token(token: str) -> str:
    # A plain hash is enough here: the token is 256 random bits, not a
    # guessable password, so there's nothing for a slow hash to protect.
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class SessionService:
    def __init__(self, session: AsyncSession, lifetime_hours: int) -> None:
        self._session = session
        self._lifetime = timedelta(hours=lifetime_hours)

    async def create(self, account: Account) -> str:
        """Starts a session and returns the raw token for the cookie. The
        raw token exists only in the response; it is never stored."""
        token = secrets.token_urlsafe(32)
        self._session.add(
            AuthSession(
                token_hash=_hash_token(token),
                account_id=account.id,
                expires_at=utcnow() + self._lifetime,
            )
        )
        await self._session.commit()
        return token

    async def resolve(self, token: str) -> Account | None:
        """The logged-in account for a cookie token, or None if the token is
        unknown, expired, or its account was deactivated."""
        row = await self._session.scalar(select(AuthSession).where(AuthSession.token_hash == _hash_token(token)))
        if row is None:
            return None
        if row.expires_at <= utcnow():
            await self._session.delete(row)
            await self._session.commit()
            return None
        account = await self._session.get(Account, row.account_id)
        return account if account is not None and account.is_active else None

    async def revoke(self, token: str) -> None:
        await self._session.execute(delete(AuthSession).where(AuthSession.token_hash == _hash_token(token)))
        await self._session.commit()

    async def purge_expired(self) -> None:
        await self._session.execute(delete(AuthSession).where(AuthSession.expires_at <= utcnow()))
        await self._session.commit()
