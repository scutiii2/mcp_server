from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base, utcnow


class LogEntry(Base):
    """One line of the Logs page (port of chat_app's log_entries table).

    kind: "action" (logins, account and admin changes), "error" (unexpected
    failures) or "chat_trace" (one per answered chat turn). account_id is
    who it concerns; NULL means the server itself. Not a foreign key: a
    deleted account's entries stay as they were (an audit log must not
    lose them, nor move them to the server's)."""

    __tablename__ = "log_entries"
    __table_args__ = (Index("ix_log_entries_kind_account_created", "kind", "account_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    account_id: Mapped[int | None]
    source: Mapped[str] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(String(500))
    details: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
