from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base, utcnow


class PromptTemplate(Base):
    """A saved prompt an account can put into its chat input. Private to the
    account; deleted with it.

    `name_key` is the name folded to lower case: it makes "Review" and
    "review" the same template, and the unique constraint enforces that in
    the database, so two racing requests can't both create it."""

    __tablename__ = "prompt_templates"
    __table_args__ = (UniqueConstraint("account_id", "name_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    name_key: Mapped[str] = mapped_column(String(180))  # casefold() can expand a character
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
