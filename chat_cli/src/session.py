"""ChatSession: which chat is open, and which agent answers it.

The conversation itself lives on ember_api (it saves every turn), so nothing
about the messages is kept here."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from src.api import Agent, ChatSummary

TITLE_MAX = 60


def new_chat_id() -> str:
    return str(uuid.uuid4())


def title_from(question: str) -> str:
    """A chat's title from its first question: one line, at most 60 characters."""
    flat = " ".join(question.split())
    return flat if len(flat) <= TITLE_MAX else flat[: TITLE_MAX - 1] + "…"


@dataclass
class ChatSession:
    chat_id: str = field(default_factory=new_chat_id)
    agent: Agent | None = None
    # True until the first question is sent: that turn creates the chat.
    is_new: bool = True
    # Tools the person answered "always" for in this chat (this run only).
    allowed_tools: set[str] = field(default_factory=set)

    def start_new(self) -> None:
        self.chat_id = new_chat_id()
        self.is_new = True
        self.allowed_tools = set()

    def open(self, chat: ChatSummary, agents: list[Agent]) -> None:
        """Continues a saved chat, with the agent it last used when that agent still exists."""
        self.chat_id = chat.id
        self.is_new = False
        self.allowed_tools = set()
        match = next((a for a in agents if a.id == chat.agent_id), None)
        if match is not None:
            self.agent = match
