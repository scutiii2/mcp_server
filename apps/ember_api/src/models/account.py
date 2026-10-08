from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db import Base, utcnow
from src.models.role import Role, account_role


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    # The bootstrap admin: kept in sync with BOOTSTRAP_ADMIN_* in .env.
    is_protected: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    email_verified: Mapped[bool] = mapped_column(default=False)
    # Chat shows a predicted next prompt after each answer (costs one small
    # model call per answer, so the account can switch it off).
    prompt_suggestions: Mapped[bool] = mapped_column(default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    roles: Mapped[list[Role]] = relationship(
        secondary=account_role, back_populates="accounts", lazy="selectin"
    )

    @property
    def permission_names(self) -> set[str]:
        from src.services.permissions import ALL_PERMISSIONS

        return {p.name for role in self.roles for p in role.permissions if p.name in ALL_PERMISSIONS}
