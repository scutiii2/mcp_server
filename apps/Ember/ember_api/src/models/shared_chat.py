from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base, utcnow


class SharedChat(Base):
    """A read-only, frozen copy of a chat that anyone holding its link may read.

    Only the SHA-256 of the link's token is stored (like login sessions), so a
    leaked database leaks no working link. `messages` is the sanitized
    snapshot (typed questions and plain answers only), taken when the link was
    made: later changes to the chat never reach it. `chat_id` says which chat
    it came from, so deleting that chat can revoke its links."""

    __tablename__ = "shared_chats"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    chat_id: Mapped[str] = mapped_column(String(64), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(120))
    # JSON list of {"role": "user" | "assistant", "content": str}.
    messages: Mapped[str] = mapped_column(Text)
    message_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    # None: never expires.
    expires_at: Mapped[datetime | None] = mapped_column(default=None, index=True)
