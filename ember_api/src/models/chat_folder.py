from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base, utcnow


class ChatFolder(Base):
    """A named group of one account's chats. One level only: a folder holds
    chats, never other folders. Deleting a folder deletes its chats (the
    foreign key on `chats.folder_id` cascades); FolderService also removes the
    chats' share links first, as ChatService.delete does."""

    __tablename__ = "chat_folders"
    __table_args__ = (UniqueConstraint("account_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    # Lower first; ties are broken by id.
    position: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
