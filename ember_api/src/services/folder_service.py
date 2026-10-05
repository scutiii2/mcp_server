"""Per-account chat folders (one level: a folder holds chats, never folders).

Every lookup filters by account, so another user's folder id behaves exactly
like a nonexistent one.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Chat, ChatFolder, SharedChat

MAX_FOLDERS_PER_ACCOUNT = 30
NAME_MAX = 60  # the chat_folders.name column


class FolderNotFound(Exception):
    """Unknown id, or another account's (deliberately indistinguishable)."""


class FolderLimitError(Exception):
    """Too many folders (maps to 409)."""


class FolderNameTaken(Exception):
    """Another folder of this account already has the name, ignoring case."""


class FolderBusy(Exception):
    """A chat in the folder has an answer being written (maps to 409)."""


@dataclass(frozen=True)
class FolderRow:
    folder: ChatFolder
    chat_count: int


class FolderService:
    def __init__(self, session: AsyncSession, account_id: int) -> None:
        self._session = session
        self._account_id = account_id

    async def list(self) -> list[FolderRow]:
        """In display order (position, then id), each with its chat count."""
        rows = await self._session.execute(
            select(ChatFolder, func.count(Chat.id))
            .outerjoin(Chat, Chat.folder_id == ChatFolder.id)
            .where(ChatFolder.account_id == self._account_id)
            .group_by(ChatFolder.id)
            .order_by(ChatFolder.position, ChatFolder.id)
        )
        return [FolderRow(folder, count) for folder, count in rows]

    async def create(self, name: str) -> ChatFolder:
        """Appended after the existing folders."""
        count = await self._session.scalar(
            select(func.count()).select_from(ChatFolder).where(ChatFolder.account_id == self._account_id)
        )
        if (count or 0) >= MAX_FOLDERS_PER_ACCOUNT:
            raise FolderLimitError(f"At most {MAX_FOLDERS_PER_ACCOUNT} folders per account - delete some first")
        await self._ensure_name_free(name, except_id=None)
        last = await self._session.scalar(
            select(func.coalesce(func.max(ChatFolder.position), -1)).where(ChatFolder.account_id == self._account_id)
        )
        folder = ChatFolder(account_id=self._account_id, name=name, position=(last or 0) + 1)
        self._session.add(folder)
        await self._commit_unique()
        return folder

    async def rename(self, folder_id: int, name: str) -> ChatFolder:
        folder = await self._get(folder_id)
        await self._ensure_name_free(name, except_id=folder.id)
        folder.name = name
        await self._commit_unique()
        return folder

    async def reorder(self, folder_id: int, position: int) -> ChatFolder:
        folder = await self._get(folder_id)
        folder.position = position
        await self._session.commit()
        return folder

    async def count_chats(self, folder: ChatFolder) -> int:
        count = await self._session.scalar(
            select(func.count()).select_from(Chat).where(Chat.folder_id == folder.id)
        )
        return count or 0

    async def _get(self, folder_id: int) -> ChatFolder:
        folder = await self._session.scalar(
            select(ChatFolder).where(ChatFolder.id == folder_id, ChatFolder.account_id == self._account_id)
        )
        if folder is None:
            raise FolderNotFound(folder_id)
        return folder

    async def _ensure_name_free(self, name: str, except_id: int | None) -> None:
        query = select(ChatFolder.id).where(
            ChatFolder.account_id == self._account_id, func.lower(ChatFolder.name) == name.lower()
        )
        if except_id is not None:
            query = query.where(ChatFolder.id != except_id)
        if await self._session.scalar(query) is not None:
            raise FolderNameTaken(name)

    async def _commit_unique(self) -> None:
        try:
            await self._session.commit()
        except IntegrityError as error:
            # Lost a race with a concurrent create or rename of the same name.
            await self._session.rollback()
            raise FolderNameTaken("name") from error
