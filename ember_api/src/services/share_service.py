"""Share links: read-only snapshots of a chat that anyone with the link may read.

The rules that keep this safe live here, not in the browser:

* The link's token is 256 random bits and only its SHA-256 is stored, so the
  raw link exists once, in the response that creates it.
* What is shared is a copy taken at that moment, cut down to the questions
  the user typed and the assistant's plain answers. Tool steps and results,
  usage data, summaries, raw logs, slash-command results, error texts and the
  text of attached files never leave.
* Every account-side lookup filters by account, so another user's id behaves
  like a missing one. The public read answers "no such link" the same way for
  unknown, expired and revoked links.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import utcnow
from src.models import Chat, SharedChat
from src.services.chat_service import ChatMessage, decode_messages

MAX_ACTIVE_SHARES_PER_ACCOUNT = 50
ALLOWED_DAYS = (1, 7, 30)
TOKEN_BYTES = 32

# A question's attached files travel inside its text (see the chat views).
_ATTACHMENT = re.compile(r'\[\[ATTACHMENT filename="([^"]*)"[^\]]*\]\]\n[\s\S]*?\n\[\[/ATTACHMENT\]\]')
# A tool's download marker points at a file on the server side.
_DOWNLOAD = re.compile(r"\[\[DOWNLOAD [^\]]*\]\]")
# How a failed answer is saved (turns.py): provider and network errors are not for outsiders.
_ERROR_PREFIXES = ("error:", "⚠️ Interrupted:")


class ShareNotFound(Exception):
    """Unknown id, or another account's (deliberately indistinguishable)."""


class ShareLimitError(Exception):
    """The account is at its limit of active links."""


class NothingToShare(Exception):
    """The chat has no question or answer that may be shared."""


def hash_token(token: str) -> str:
    # A plain hash is enough: the token is 256 random bits, not a guessable password.
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def snapshot_messages(messages: list[ChatMessage]) -> list[ChatMessage]:
    """What a shared chat shows: the typed questions and the assistant's plain
    answers, as {role, content} only. See the module docstring for what is left out."""
    shared: list[ChatMessage] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if message.get("kind") or role not in ("user", "assistant") or not isinstance(content, str):
            continue
        if role == "assistant":
            if content.lstrip().startswith(_ERROR_PREFIXES):
                continue
            content = _DOWNLOAD.sub("", content).strip()
        else:
            content = _ATTACHMENT.sub(lambda m: f"📎 {m.group(1)}", content).strip()
        if content:
            shared.append({"role": role, "content": content})
    return shared


@dataclass(frozen=True)
class CreatedShare:
    share: SharedChat
    # The link's secret. Not stored anywhere: this is the only time it exists.
    token: str


class ShareService:
    def __init__(self, session: AsyncSession, account_id: int) -> None:
        self._session = session
        self._account_id = account_id

    async def create(self, chat: Chat, expires_in_days: int | None) -> CreatedShare:
        messages = snapshot_messages(decode_messages(chat))
        if not messages:
            raise NothingToShare(chat.chat_id)
        if await self._active_count() >= MAX_ACTIVE_SHARES_PER_ACCOUNT:
            raise ShareLimitError(
                f"At most {MAX_ACTIVE_SHARES_PER_ACCOUNT} active shared links per account - revoke some first"
            )
        token = secrets.token_urlsafe(TOKEN_BYTES)
        now = utcnow()
        share = SharedChat(
            account_id=self._account_id,
            chat_id=chat.chat_id,
            token_hash=hash_token(token),
            title=chat.title,
            messages=json.dumps(messages, ensure_ascii=False),
            message_count=len(messages),
            created_at=now,
            expires_at=now + timedelta(days=expires_in_days) if expires_in_days else None,
        )
        self._session.add(share)
        await self._session.commit()
        return CreatedShare(share, token)

    async def list(self, chat_id: str | None = None) -> list[SharedChat]:
        """Active links, newest first; expired ones are gone from the list."""
        statement = (
            select(SharedChat)
            .where(SharedChat.account_id == self._account_id, _active())
            .order_by(SharedChat.created_at.desc(), SharedChat.id.desc())
        )
        if chat_id is not None:
            statement = statement.where(SharedChat.chat_id == chat_id)
        return list(await self._session.scalars(statement))

    async def revoke(self, share_id: int) -> SharedChat:
        share = await self._session.scalar(
            select(SharedChat).where(SharedChat.account_id == self._account_id, SharedChat.id == share_id)
        )
        if share is None:
            raise ShareNotFound(share_id)
        await self._session.delete(share)
        await self._session.commit()
        return share

    async def _active_count(self) -> int:
        count = await self._session.scalar(
            select(func.count()).select_from(SharedChat).where(SharedChat.account_id == self._account_id, _active())
        )
        return count or 0


def _active():
    return or_(SharedChat.expires_at.is_(None), SharedChat.expires_at > utcnow())


async def read_shared(session: AsyncSession, token: str) -> SharedChat | None:
    """The public read: the link's snapshot, or None for a link that is
    unknown, revoked or expired (callers must not say which)."""
    return await session.scalar(
        select(SharedChat).where(SharedChat.token_hash == hash_token(token), _active())
    )


async def purge_expired_shares(session: AsyncSession) -> None:
    await session.execute(
        delete(SharedChat).where(SharedChat.expires_at.is_not(None), SharedChat.expires_at <= utcnow())
    )
    await session.commit()
