from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base, utcnow


class UserExtension(Base):
    """An MCP server one account added for itself. Only that account sees it,
    and only its chats use it. Deleted with the account.

    `slug` names the extension in tool names (`u_<slug>__<tool>`). The header
    values (a token the server wants) are in `headers_encrypted`: one Fernet
    token of a JSON object, or None when there are none (see secret_box.py)."""

    __tablename__ = "user_extensions"
    __table_args__ = (UniqueConstraint("account_id", "slug"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    slug: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(60))
    description: Mapped[str] = mapped_column(String(300), default="")
    url: Mapped[str] = mapped_column(String(1000))
    headers_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)
