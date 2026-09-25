from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base, utcnow


class LoginAttempt(Base):
    """Every login try, successful or not - the audit trail and the basis
    for rate limiting later."""

    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    ip_address: Mapped[str] = mapped_column(String(64))
    # None when the username didn't match any account.
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"))
    succeeded: Mapped[bool]
    attempted_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
