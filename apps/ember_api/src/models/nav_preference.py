from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base, utcnow


class NavPreference(Base):
    """How one account arranges the pages in its nav rail. No row means the
    default arrangement. Deleted with the account.

    The three lists hold page ids (route paths such as "/agents"). ember_api
    does not know the page list - the browser owns it - so unknown ids are kept
    and the browser ignores them."""

    __tablename__ = "nav_preferences"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    page_order: Mapped[list[str]] = mapped_column(JSON, default=list)
    pinned: Mapped[list[str]] = mapped_column(JSON, default=list)
    hidden: Mapped[list[str]] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)
