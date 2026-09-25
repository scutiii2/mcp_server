"""Self-service changes to the logged-in account: email and password.

Mirrors chat_app's Account page (current password required for every
change) with three fixes: a taken email is a clean error instead of a
database crash, a new email must be verified again before permissions come
back, and a new password logs out every other session.

The protected bootstrap admin is refused: its email and password come from
secret_bootstrap_admin.env and are reset from it on every start, so a change
here would silently undo itself.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Account
from src.services.auth_service import hash_password, password_matches


class AccountChangeError(Exception):
    """Refused change (maps to 409)."""


class WrongPasswordError(Exception):
    """The current password didn't match (maps to 400)."""


class AccountService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def change_email(self, account: Account, current_password: str, new_email: str) -> bool:
        """Sets the new email as unverified. Returns False when it equals the
        current one (nothing changed, nothing to verify)."""
        await self._check(account, current_password)
        if new_email.lower() == account.email.lower():
            return False
        taken = await self._session.scalar(
            select(Account.id).where(func.lower(Account.email) == new_email.lower(), Account.id != account.id)
        )
        if taken is not None:
            raise AccountChangeError("Email is already registered")
        account.email = new_email
        account.email_verified = False
        await self._session.commit()
        return True

    async def change_password(self, account: Account, current_password: str, new_password: str) -> None:
        """Only the hash changes here; the caller ends the other sessions."""
        await self._check(account, current_password)
        account.password_hash = await hash_password(new_password)
        await self._session.commit()

    async def _check(self, account: Account, current_password: str) -> None:
        if account.is_protected:
            raise AccountChangeError(
                "This account's email and password come from secret_bootstrap_admin.env - change them there"
            )
        if not await password_matches(account.password_hash, current_password):
            raise WrongPasswordError("Current password is incorrect")
