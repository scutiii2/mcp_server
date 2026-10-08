from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base, utcnow


class AccountCapability(Base):
    """One built-in capability or server-listed extension an account has added.
    A row means enabled; no row means disabled. Deleted with the account.

    `kind` is "capability" or "extension"; `item_id` is the capability name or
    extension id as mcp_server reports it. ember_api does not check it against
    mcp_server, so ids of things that no longer exist are kept and ignored."""

    __tablename__ = "account_capabilities"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
