"""Shared fakes: a console that records, a scripted line reader and a fake EmberClient."""

from __future__ import annotations

import asyncio
import io
from collections.abc import AsyncIterator
from typing import Any

import pytest
from rich.console import Console

from src.api import Agent, ApiError, ChatDetail, ChatSummary, Usage, UsageWindow


def make_console(encoding: str = "utf-8") -> Console:
    """A console that writes to memory and can be read back with export_text()."""
    file = io.TextIOWrapper(io.BytesIO(), encoding=encoding, errors="replace")
    return Console(file=file, record=True, width=100, force_terminal=False, color_system=None)


@pytest.fixture
def console() -> Console:
    return make_console()


def screen(console: Console) -> str:
    return console.export_text(clear=False)


class Script:
    """A line reader that returns what it was given, in order. An exception class or
    instance in the list is raised instead; running out is the end of input (Ctrl+D)."""

    def __init__(self, *lines: Any) -> None:
        self.lines = list(lines)
        self.prompts: list[str] = []

    async def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self.lines:
            raise EOFError
        item = self.lines.pop(0)
        if isinstance(item, BaseException) or (isinstance(item, type) and issubclass(item, BaseException)):
            raise item
        return item


def final(content: str = "Hello!", sequence: int = 9, **extra: Any) -> dict[str, Any]:
    message = {"role": "assistant", "content": content, "agent": "a1", "model": "m-1", "total_tokens": 100,
               "input_tokens": 70, "output_tokens": 30, "duration_s": 1.5, **extra}
    return {"sequence": sequence, "type": "final", "message": message, "cancelled": False}


def token(text: str, sequence: int = 1) -> dict[str, Any]:
    return {"sequence": sequence, "type": "token", "text": text}


def summary(chat_id: str = "chat-0001", title: str = "A chat", agent_id: str | None = "a1", running: bool = False,
            count: int = 2) -> ChatSummary:
    return ChatSummary(id=chat_id, title=title, agent_id=agent_id, message_count=count,
                       updated_at="2026-10-03T09:30:00", running=running)


class FakeClient:
    """Stands in for EmberClient in the REPL tests."""

    def __init__(self) -> None:
        self.agent_list = [Agent("a1", "Agent One"), Agent("a2", "Agent Two")]
        self.chat_list: list[ChatSummary] = []
        self.details: dict[str, ChatDetail] = {}
        self.events: list[dict[str, Any]] = [token("Hi"), final("Hi")]
        self.hang_after_events = False
        self.start_error: Exception | None = None
        self.cancel_error: Exception | None = None
        self.decide_error: Exception | None = None
        self.stream_error: Exception | None = None
        self.turns: list[dict[str, Any]] = []
        self.cancelled: list[str] = []
        self.decisions: list[tuple[str, str, str]] = []
        self.streams: list[tuple[str, int]] = []
        self.usage_value = Usage(UsageWindow(1200, 5000, "2026-10-03T15:00:00"), UsageWindow(40000, 0, None))
        self.started = asyncio.Event()

    async def agents(self) -> list[Agent]:
        return self.agent_list

    async def chats(self) -> list[ChatSummary]:
        return self.chat_list

    async def chat(self, chat_id: str) -> ChatDetail:
        return self.details[chat_id]

    async def start_turn(self, chat_id, question, agent_id, title=None, ask_before_tools=False, allowed_tools=None) -> int:
        if self.start_error:
            raise self.start_error
        self.turns.append({"chat_id": chat_id, "question": question, "agent_id": agent_id, "title": title,
                           "ask_before_tools": ask_before_tools, "allowed_tools": allowed_tools})
        return 4

    async def cancel(self, chat_id: str) -> None:
        self.cancelled.append(chat_id)
        if self.cancel_error:
            raise self.cancel_error

    async def decide(self, chat_id: str, step_id: str, decision: str) -> None:
        self.decisions.append((chat_id, step_id, decision))
        if self.decide_error:
            raise self.decide_error

    async def usage(self) -> Usage:
        return self.usage_value

    async def stream_events(self, chat_id: str, after: int) -> AsyncIterator[dict[str, Any]]:
        self.streams.append((chat_id, after))
        self.started.set()
        if self.stream_error:
            raise self.stream_error
        for event in self.events:
            yield event
        if self.hang_after_events:
            await asyncio.Event().wait()


@pytest.fixture
def client() -> FakeClient:
    return FakeClient()


def api_error(status: int, detail: str) -> ApiError:
    return ApiError(status, detail)
