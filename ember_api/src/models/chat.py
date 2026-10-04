from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base, utcnow


class Chat(Base):
    """One conversation, its whole transcript as a JSON blob (same shape as
    chat_app's chats_store): the app always reads and writes a chat whole,
    so a blob matches the access pattern.

    `chat_id` is the id the browser generated (a UUID). It is unique per
    account, not globally, so one user's ids can never clash with - or
    reveal - another user's."""

    __tablename__ = "chats"
    __table_args__ = (UniqueConstraint("account_id", "chat_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    chat_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(120))
    agent_id: Mapped[str | None] = mapped_column(String(120))
    # JSON list of {"role": "user" | "assistant", "content": str}.
    messages: Mapped[str] = mapped_column(Text, default="[]")
    message_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
