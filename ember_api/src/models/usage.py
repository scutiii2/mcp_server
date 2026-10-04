from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base, utcnow


class UsageRecord(Base):
    """Tokens one agent spent on one turn (or one summarization call) for
    an account - the basis of the usage limits and the Usage page (port of
    chat_app's token_usage table). A turn that delegated to other agents
    writes one row per agent, all sharing `turn_id`."""

    __tablename__ = "usage_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    turn_id: Mapped[str] = mapped_column(String(64))
    # "chat" or "summary".
    kind: Mapped[str] = mapped_column(String(20), default="chat")
    chat_id: Mapped[str | None] = mapped_column(String(64))
    agent: Mapped[str | None] = mapped_column(String(120))
    model: Mapped[str | None] = mapped_column(String(120))
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    total_tokens: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
