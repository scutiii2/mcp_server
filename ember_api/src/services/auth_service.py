"""Credential checks, login auditing and the bootstrap admin.

Mirrors chat_app/src/services/auth_service.py (same werkzeug hashes, same
bootstrap-admin rules) on ember_api's async database.
"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from werkzeug.security import check_password_hash, generate_password_hash

from src.models import Account, LoginAttempt, Permission, Role
from src.services.permissions import ADMIN_ROLE, ALL_PERMISSIONS, DEFAULT_ROLE_PERMISSIONS
from src.utils.config_loader import load_env_secrets

# Password hashing is deliberately slow (scrypt); it runs on a worker thread
# so one login never stalls the event loop for everyone else.


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(generate_password_hash, password)


async def password_matches(password_hash: str, password: str) -> bool:
    return await asyncio.to_thread(check_password_hash, password_hash, password)


_dummy_hash: str | None = None


async def _dummy_password_hash() -> str:
    """A real hash to check against when the username doesn't exist, so an
    unknown user takes as long as a wrong password (no username probing by
    timing)."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = await hash_password(secrets.token_urlsafe(16))
    return _dummy_hash


@dataclass(frozen=True)
class LoginCheck:
    """Outcome of one credential check. `account` is set only on success;
    `account_id` is set whenever the username matched, so a wrong password
    is still attributed to its account in the login audit."""

    account: Account | None
    account_id: int | None


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def verify_credentials(self, username: str, password: str) -> LoginCheck:
        """Unknown user, wrong password and inactive account all come back
        with account=None - callers must not tell these apart to the client."""
        account = await self._session.scalar(select(Account).where(Account.username == username))
        if account is None:
            await password_matches(await _dummy_password_hash(), password)
            return LoginCheck(account=None, account_id=None)
        if not await password_matches(account.password_hash, password) or not account.is_active:
            return LoginCheck(account=None, account_id=account.id)
        return LoginCheck(account=account, account_id=account.id)

    async def record_login_attempt(self, ip_address: str, account_id: int | None, succeeded: bool) -> None:
        self._session.add(LoginAttempt(ip_address=ip_address, account_id=account_id, succeeded=succeeded))
        await self._session.commit()

    async def ensure_bootstrap_admin(self, secrets_dir: Path) -> str | None:
        """Makes sure the Administrator role holds every permission and that
        the protected admin account exists and matches
        secret_bootstrap_admin.env. Returns a generated password when one had
        to be made up (the caller prints it once), else None."""
        role = await self._ensure_admin_role()

        env = load_env_secrets(secrets_dir / "secret_bootstrap_admin.env")
        username = env.get("BOOTSTRAP_ADMIN_USERNAME") or "admin"
        email = env.get("BOOTSTRAP_ADMIN_EMAIL") or "admin@example.com"
        password = env.get("BOOTSTRAP_ADMIN_PASSWORD") or ""

        existing = await self._session.scalar(select(Account).where(Account.is_protected.is_(True)))
        if existing is not None:
            await self._sync_admin(existing, username, email, password)
            return None

        if await self._session.scalar(select(func.count()).select_from(Account)):
            return None  # other accounts exist; never invent an admin next to them

        generated = None
        if not password:
            password = generated = secrets.token_urlsafe(16)
        admin = Account(
            username=username,
            email=email,
            password_hash=await hash_password(password),
            is_protected=True,
            # The operator configured this address; there's no one to send a code to yet.
            email_verified=True,
        )
        admin.roles.append(role)
        self._session.add(admin)
        await self._session.commit()
        return generated

    async def ensure_default_role(self, name: str) -> None:
        """Creates the role new registrations get, if missing, with
        DEFAULT_ROLE_PERMISSIONS. An existing role is left exactly as is."""
        if await self._session.scalar(select(Role).where(Role.name == name)) is not None:
            return
        permissions = await self._ensure_permissions()
        self._session.add(
            Role(
                name=name,
                description="Default role for newly registered accounts",
                permissions=[permissions[p] for p in DEFAULT_ROLE_PERMISSIONS],
            )
        )
        await self._session.commit()

    async def _ensure_permissions(self) -> dict[str, Permission]:
        existing = {p.name: p for p in await self._session.scalars(select(Permission))}
        for name, description in ALL_PERMISSIONS.items():
            if name not in existing:
                existing[name] = Permission(name=name, description=description)
                self._session.add(existing[name])
        return existing

    async def _ensure_admin_role(self) -> Role:
        existing = await self._ensure_permissions()

        role = await self._session.scalar(select(Role).where(Role.name == ADMIN_ROLE))
        if role is None:
            role = Role(name=ADMIN_ROLE, description="Full-access bootstrap role")
            self._session.add(role)
        role.permissions = list(existing.values())
        await self._session.commit()
        return role

    async def _sync_admin(self, admin: Account, username: str, email: str, password: str) -> None:
        admin.username = username
        admin.email = email
        # No configured password: keep the current one rather than rotating it.
        if password and not await password_matches(admin.password_hash, password):
            admin.password_hash = await hash_password(password)
        await self._session.commit()
