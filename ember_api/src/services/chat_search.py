"""Search over one account's chats: titles and message text.

Like ChatService, every query filters by account, so another user's chats
can't turn up. Matching is case-insensitive and literal (no wildcards).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Chat
from src.services.chat_service import decode_messages

MIN_QUERY_CHARS = 2
MAX_QUERY_CHARS = 100
MAX_HITS = 50
# Characters of context kept before and after the match in a snippet.
SNIPPET_BEFORE = 40
SNIPPET_AFTER = 90

# A question's attached files travel inside its text; their bodies are not
# what someone remembers typing, so they are left out of the search.
_ATTACHMENT = re.compile(r"\[\[ATTACHMENT [^\]]*\]\]\n[\s\S]*?\n\[\[/ATTACHMENT\]\]")
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True)
class Span:
    """Where the match sits in a piece of text (characters)."""

    start: int
    length: int


@dataclass(frozen=True)
class Snippet:
    text: str
    match: Span


@dataclass(frozen=True)
class SearchHit:
    chat: Chat
    title_match: Span | None
    # The first message that matches (its text around the match), if any.
    snippet: Snippet | None
    message_index: int | None
    # How many messages contain the query.
    message_matches: int


def _prefilterable(needle: str) -> bool:
    """The stored JSON can be pre-filtered with SQL LIKE only when the needle
    is ASCII (SQLite folds case for ASCII alone) and has no character JSON
    escapes (quote, backslash, control characters)."""
    return needle.isascii() and not any(c in '"\\' or ord(c) < 32 for c in needle)


def _snippet(text: str, span: Span) -> Snippet:
    """`text` reduced to one line around the match, with ellipses at cut ends."""
    start = max(0, span.start - SNIPPET_BEFORE)
    end = min(len(text), span.start + span.length + SNIPPET_AFTER)
    before = _SPACES.sub(" ", text[start : span.start])
    matched = _SPACES.sub(" ", text[span.start : span.start + span.length])
    after = _SPACES.sub(" ", text[span.start + span.length : end])
    lead = ("…" if start > 0 else "") + before
    suffix = "…" if end < len(text) else ""
    return Snippet(text=f"{lead}{matched}{after}{suffix}", match=Span(len(lead), len(matched)))


class ChatSearch:
    def __init__(self, session: AsyncSession, account_id: int) -> None:
        self._session = session
        self._account_id = account_id

    async def search(self, query: str, limit: int = MAX_HITS) -> list[SearchHit]:
        """Chats whose title or messages contain `query`, newest first."""
        needle = query.strip()
        if len(needle) < MIN_QUERY_CHARS:
            return []
        pattern = re.compile(re.escape(needle), re.IGNORECASE)

        statement = select(Chat).where(Chat.account_id == self._account_id).order_by(Chat.updated_at.desc())
        if _prefilterable(needle):
            like = needle.lower()
            statement = statement.where(
                or_(
                    func.lower(Chat.title).contains(like, autoescape=True),
                    func.lower(Chat.messages).contains(like, autoescape=True),
                )
            )

        hits: list[SearchHit] = []
        # Streamed in batches, and stopped at `limit`: a scan over a big
        # history never holds every transcript at once.
        result = await self._session.stream_scalars(statement.execution_options(yield_per=25))
        try:
            async for chat in result:
                hit = self._match(chat, pattern)
                if hit is not None:
                    hits.append(hit)
                    if len(hits) >= limit:
                        break
        finally:
            await result.close()
        return hits

    @staticmethod
    def _match(chat: Chat, pattern: re.Pattern[str]) -> SearchHit | None:
        found = pattern.search(chat.title)
        title_match = Span(found.start(), found.end() - found.start()) if found else None

        first: tuple[int, Snippet] | None = None
        count = 0
        for index, message in enumerate(decode_messages(chat)):
            text = _ATTACHMENT.sub(" ", message.get("content", ""))
            found = pattern.search(text)
            if found is None:
                continue
            count += 1
            if first is None:
                first = (index, _snippet(text, Span(found.start(), found.end() - found.start())))
        if title_match is None and first is None:
            return None
        return SearchHit(
            chat=chat,
            title_match=title_match,
            snippet=first[1] if first else None,
            message_index=first[0] if first else None,
            message_matches=count,
        )
