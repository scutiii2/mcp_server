"""Per-account chat history (port of chat_app/src/services/chats_store.py).

Every lookup filters by account, so another user's chat id behaves exactly
like a nonexistent one - nothing here can be used to probe or read someone
else's chats.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from src.db import utcnow
from src.models import Chat

MAX_CHAT_BYTES = 2 * 1024 * 1024
MAX_CHATS_PER_ACCOUNT = 1000


class ChatNotFound(Exception):
    """Unknown id, or another account's (deliberately indistinguishable)."""


class ChatLimitError(Exception):
    """A chat too large, or too many chats (maps to 413)."""


# {"role": "user" | "assistant", "content": str} plus optional "kind"
# ("summary", "log_attachment", "command"), "model", "total_tokens",
# "context_tokens", "context_window" - validated by the route.
ChatMessage = dict[str, Any]


@dataclass(frozen=True)
class ImportedChat:
    chat_id: str
    title: str
    agent_id: str | None
    messages: list[ChatMessage]
    created_at: datetime
    updated_at: datetime


def _encode(messages: list[ChatMessage]) -> str:
    text = json.dumps(messages, ensure_ascii=False)
    if len(text.encode("utf-8")) > MAX_CHAT_BYTES:
        raise ChatLimitError(f"Chat is larger than {MAX_CHAT_BYTES // (1024 * 1024)} MB")
    return text


def decode_messages(chat: Chat) -> list[ChatMessage]:
    return json.loads(chat.messages)


class ChatService:
    def __init__(self, session: AsyncSession, account_id: int) -> None:
        self._session = session
        self._account_id = account_id

    async def list(self) -> list[Chat]:
        """Newest first, without transcripts (the sidebar needs only titles;
        `messages` must not be read from these rows)."""
        return list(
            await self._session.scalars(
                select(Chat)
                .options(defer(Chat.messages, raiseload=True))
                .where(Chat.account_id == self._account_id)
                .order_by(Chat.updated_at.desc())
            )
        )

    async def get(self, chat_id: str) -> Chat:
        chat = await self._find(chat_id)
        if chat is None:
            raise ChatNotFound(chat_id)
        return chat

    async def put(self, chat_id: str, title: str, agent_id: str | None, messages: list[ChatMessage]) -> Chat:
        """Creates the chat or replaces its title, agent and transcript."""
        encoded = _encode(messages)
        chat = await self._find(chat_id)
        now = utcnow()
        if chat is None:
            await self._ensure_room(1)
            chat = Chat(account_id=self._account_id, chat_id=chat_id, created_at=now)
            self._session.add(chat)
        chat.title = title
        chat.agent_id = agent_id
        chat.messages = encoded
        chat.message_count = len(messages)
        chat.updated_at = now
        await self._session.commit()
        return chat

    async def replace_messages(self, chat_id: str, messages: list[ChatMessage], agent_id: str | None = None) -> Chat:
        """New transcript for an existing chat, keeping its title (and its
        agent unless one is given). Used by server-run turns."""
        chat = await self.get(chat_id)
        chat.messages = _encode(messages)
        chat.message_count = len(messages)
        if agent_id is not None:
            chat.agent_id = agent_id
        chat.updated_at = utcnow()
        await self._session.commit()
        return chat

    async def rename(self, chat_id: str, title: str) -> Chat:
        chat = await self.get(chat_id)
        chat.title = title
        await self._session.commit()
        return chat

    async def delete(self, chat_id: str) -> None:
        chat = await self.get(chat_id)
        await self._session.delete(chat)
        await self._session.commit()

    async def delete_all(self) -> int:
        result = await self._session.execute(delete(Chat).where(Chat.account_id == self._account_id))
        await self._session.commit()
        return result.rowcount or 0

    async def import_chats(self, chats: list[ImportedChat]) -> tuple[int, int]:
        """Adds chats whose ids this account doesn't have yet, keeping their
        own timestamps; existing ones are never overwritten. Returns
        (imported, skipped). All or nothing: a chat over the size limit, or
        too many in total, rejects the whole import."""
        existing = set(
            await self._session.scalars(select(Chat.chat_id).where(Chat.account_id == self._account_id))
        )
        seen: set[str] = set()
        fresh: list[Chat] = []
        for item in chats:
            if item.chat_id in existing or item.chat_id in seen:
                continue
            seen.add(item.chat_id)
            fresh.append(
                Chat(
                    account_id=self._account_id,
                    chat_id=item.chat_id,
                    title=item.title,
                    agent_id=item.agent_id,
                    messages=_encode(item.messages),
                    message_count=len(item.messages),
                    created_at=item.created_at,
                    updated_at=item.updated_at,
                )
            )
        if fresh:
            await self._ensure_room(len(fresh))
            self._session.add_all(fresh)
            await self._session.commit()
        return len(fresh), len(chats) - len(fresh)

    async def _find(self, chat_id: str) -> Chat | None:
        return await self._session.scalar(
            select(Chat).where(Chat.account_id == self._account_id, Chat.chat_id == chat_id)
        )

    async def _ensure_room(self, adding: int) -> None:
        count = await self._session.scalar(
            select(func.count()).select_from(Chat).where(Chat.account_id == self._account_id)
        )
        if (count or 0) + adding > MAX_CHATS_PER_ACCOUNT:
            raise ChatLimitError(f"At most {MAX_CHATS_PER_ACCOUNT} chats per account - delete some first")
