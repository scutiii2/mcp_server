"""Login rate limiting (port of chat_app/src/services/security/rate_limit.py).

Reads the login_attempts audit rows the login route already writes: once
`max_attempts` failures fall within `window_seconds` - from this IP, for
this account, or either (scope) - login is refused until `lockout_seconds`
after the most recent failure. Refused tries aren't recorded, so hammering
during a lockout doesn't extend it.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import SecuritySettings
from src.db import utcnow
from src.models import LoginAttempt


class LoginRateLimiter:
    def __init__(self, session: AsyncSession, settings: SecuritySettings) -> None:
        self._session = session
        self._settings = settings

    async def retry_after(self, ip_address: str, account_id: int | None) -> int | None:
        """Seconds until login is allowed again, or None if it is allowed now."""
        s = self._settings
        if not s.rate_limit_enabled:
            return None
        filters = []
        if s.rate_limit_scope in ("ip", "both"):
            filters.append(LoginAttempt.ip_address == ip_address)
        if s.rate_limit_scope in ("account", "both") and account_id is not None:
            filters.append(LoginAttempt.account_id == account_id)
        if not filters:
            return None

        now = utcnow()
        failures = list(
            await self._session.scalars(
                select(LoginAttempt.attempted_at)
                .where(
                    LoginAttempt.succeeded.is_(False),
                    LoginAttempt.attempted_at >= now - timedelta(seconds=s.window_seconds),
                    or_(*filters),
                )
                .order_by(LoginAttempt.attempted_at.desc())
                .limit(s.max_attempts)
            )
        )
        if len(failures) < s.max_attempts:
            return None
        remaining = (failures[0] + timedelta(seconds=s.lockout_seconds) - now).total_seconds()
        return max(1, int(remaining) + 1) if remaining > 0 else None
