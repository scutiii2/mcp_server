from __future__ import annotations

from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base, utcnow


class AppSetting(Base):
    """One setting an administrator changes for everyone (see
    `services/settings_service.py` for the names and their defaults).
    A setting with no row has its default."""

    __tablename__ = "app_settings"

    name: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(String(200))
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)
