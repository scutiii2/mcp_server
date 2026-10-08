"""Prompt suggestion: the message the user is most likely to type next.

One plain model call (`interpret`, no tools) over the last question and
answer, made after a turn ended. It is a nicety: every failure just means "no
suggestion", and it never touches the turn itself.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from src.services.agent_gateway import AgentCallError, AgentGateway, Caller
from src.services.chat_service import ChatMessage

logger = logging.getLogger(__name__)

SUGGESTION_MAX = 120
# How much of the question (its start) and the answer (its end) the model sees.
EXCHANGE_MAX = 2000
MIN_QUESTION = 3
NO_SUGGESTION = "NONE"
CACHE_SIZE = 256
# Saved assistant messages that are not an answer to follow up on.
_NOT_ANSWERS = ("error:", "⏹️")
_CANCELLED = "Cancelled."
_INTERRUPTED = "⚠️ Interrupted"


@dataclass(frozen=True)
class SuggestionOutcome:
    """`text` is None when the model saw no natural follow-up; `result` is
    the raw interpret() result, so its tokens are still accounted for."""

    text: str | None
    result: dict[str, Any]


def build_prompt(question: str, answer: str) -> str:
    return (
        "Below is the last exchange of a chat between a user and an AI assistant. "
        "Predict the single message the user is most likely to type next, written "
        "exactly as the user would type it. Rules: at most 120 characters, one "
        "line, plain text, no quotes, no preamble, no explanation. If there is no "
        f"natural follow-up, reply with exactly {NO_SUGGESTION}.\n\n"
        f"--- USER ---\n{question[:EXCHANGE_MAX]}\n\n"
        f"--- ASSISTANT ---\n{answer[-EXCHANGE_MAX:]}"
    )


def clean(raw: str) -> str | None:
    """The first line of the model's reply, tidied; None for NONE or nothing."""
    lines = raw.strip().splitlines()
    line = " ".join(lines[0].split()) if lines else ""
    line = line.strip("\"'`“”‘’ ")
    if not line or line.rstrip(".").upper() == NO_SUGGESTION:
        return None
    return line[:SUGGESTION_MAX].rstrip()


def _is_answer(text: str) -> bool:
    return bool(text) and not text.startswith(_NOT_ANSWERS) and text != _CANCELLED and _INTERRUPTED not in text


def last_exchange(messages: list[ChatMessage]) -> tuple[str, str] | None:
    """(question, answer) of the chat's last plain user/assistant pair; None
    when the chat does not end on one (a slash command, a summary, an error or
    cancelled answer, a question too short to say anything)."""
    if len(messages) < 2:
        return None
    question, answer = messages[-2], messages[-1]
    if question.get("role") != "user" or answer.get("role") != "assistant":
        return None
    if question.get("kind") or answer.get("kind"):
        return None
    asked = str(question.get("content") or "").strip()
    replied = str(answer.get("content") or "").strip()
    if len(asked) < MIN_QUESTION or not _is_answer(replied):
        return None
    return asked, replied


async def suggest(
    gateway: AgentGateway, url: str, caller: Caller, question: str, answer: str
) -> SuggestionOutcome | None:
    """None only when the agent call failed (nothing was spent)."""
    try:
        result = await gateway.interpret(url, caller, build_prompt(question, answer))
    except AgentCallError as error:
        logger.info("prompt suggestion skipped: %s", error)
        return None
    return SuggestionOutcome(clean(str(result.get("response") or "")), result)


class SuggestionCache:
    """The last few answers, so reopening a chat (or a second tab) does not pay
    for the same suggestion again. A "no suggestion" is remembered too."""

    def __init__(self, size: int = CACHE_SIZE) -> None:
        self._size = size
        self._items: OrderedDict[Any, str | None] = OrderedDict()

    def lookup(self, key: Any) -> tuple[bool, str | None]:
        if key not in self._items:
            return False, None
        self._items.move_to_end(key)
        return True, self._items[key]

    def put(self, key: Any, text: str | None) -> None:
        self._items[key] = text
        self._items.move_to_end(key)
        while len(self._items) > self._size:
            self._items.popitem(last=False)


CACHE = SuggestionCache()


def cache_key(account_id: int, chat_id: str, message_count: int, answer: str) -> tuple[int, str, int, int]:
    return account_id, chat_id, message_count, hash(answer)
