"""Shared types for ai_agent's LLM providers.

Trimmed from chat_app/src/services/llm/base.py: this project pins one
provider+model per instance (see agent_config.py) rather than routing
between several, so ProviderSpec/ModelOption/ModelAvailability* and the
Ollama-only RecursiveRoundRecord - all built for chat_app's per-request
provider dropdown - have no equivalent need here. SYSTEM_PROMPT,
ChatCancelled, ToolCallRecord and ChatResult carry over unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SYSTEM_PROMPT = (
    "You are a helpful assistant with access to tools. Use them to get "
    "real data rather than guessing, and say so plainly when no tool can "
    "answer the question. Confirm with the user before any destructive or "
    "hard-to-reverse action."
)


class ChatCancelled(Exception):
    """Raised by a provider the moment it notices (via cancellation.py,
    checked between rounds of its tool-calling loop) that the user
    cancelled this turn. Caught in server.py's ask() tool, which turns it
    into a clean {"cancelled": True} result rather than an MCP tool
    error - this is an expected user action, not a failure."""


@dataclass
class ToolCallRecord:
    """One tool invocation's full detail - name, the arguments the model
    supplied, and the result text that went back to it."""

    name: str
    arguments: dict[str, Any]
    result: str


@dataclass
class ChatResult:
    response: str
    tools_used: list[str] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    provider_id: str = ""
    model: str = ""
    total_tokens: int | None = None
