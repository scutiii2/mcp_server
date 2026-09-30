from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base, utcnow


class KnownDevice(Base):
    """A device an account has logged in from (port of chat_app's
    device_fingerprints). `fingerprint_hash` is what's matched; the browser
    and network are kept only so the Account page can say which device it
    was."""

    __tablename__ = "known_devices"
    __table_args__ = (UniqueConstraint("account_id", "fingerprint_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    fingerprint_hash: Mapped[str] = mapped_column(String(64))
    user_agent: Mapped[str] = mapped_column(String(300), default="")
    ip_subnet: Mapped[str] = mapped_column(String(64), default="")
    first_seen_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(default=utcnow)
