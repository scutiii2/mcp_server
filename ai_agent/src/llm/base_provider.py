"""Shared types for ai_agent's LLM providers.

Trimmed from chat_app/src/services/llm/base.py: this project pins one
provider+model per instance (see agent_config.py) rather than routing
between several, so ProviderSpec/ModelOption/ModelAvailability* and the
Ollama-only RecursiveRoundRecord - all built for chat_app's per-request
provider dropdown - have no equivalent need here. ChatCancelled,
ToolCallRecord and ChatResult carry over unchanged. SYSTEM_PROMPT moved to
agent_roles.py, which composes it from configs/config_ai_agent_roles.json
instead of a fixed string.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import anyio.to_thread

from src import tool_progress
from src.catalog import catalog
from src.llm import cooldown


OnEvent = Callable[[dict[str, Any]], Awaitable[None]]
"""Async callback a streaming-capable provider's run_chat calls once per
step_start/step_end/token event, in order, from inside its own
tool-calling loop. None when the caller (agent_config.run_chat) doesn't
want live events - every call site must no-op cleanly when this is None,
never assume it's set."""


@catalog
def step_event(kind: str, **fields: Any) -> dict[str, Any]:
    """Stamps a `type` key onto an event dict - the one place that shape
    is defined, so server.py's ctx.report_progress(message=json.dumps(...))
    and chat_app's SSE frames agree on field names without repeating the
    literal "type" key at every call site."""
    return {"type": kind, **fields}


async def dispatch_with_progress(
    dispatch: Callable[..., str], on_event: OnEvent | None, step_id: str, *args: Any
) -> str:
    """Runs a provider's blocking tool ``dispatch`` on a worker thread and,
    while it runs, turns every progress message the tool reports into a
    ``step_progress`` event for that step (see tool_progress.py). With
    ``on_event`` None it is a plain worker-thread call."""
    if on_event is None:
        return await anyio.to_thread.run_sync(dispatch, *args)
    loop = asyncio.get_running_loop()
    pending: list[Any] = []

    def sink(message: str) -> None:
        pending.append(
            asyncio.run_coroutine_threadsafe(on_event(step_event("step_progress", id=step_id, message=message)), loop)
        )

    token = tool_progress.bind(sink)
    try:
        return await anyio.to_thread.run_sync(dispatch, *args)
    finally:
        tool_progress.reset(token)
        # Deliver every queued progress event before the caller's step_end.
        await asyncio.gather(*(asyncio.wrap_future(f) for f in pending), return_exceptions=True)


class LiveUsage:
    """Emits running "usage" events so the chat can show tokens while a
    reply is still being written, not only once it completes.

    Providers only report exact usage when a round ends, so mid-round the
    figure is an estimate: the exact total of finished rounds plus about one
    token per 4 streamed characters (`estimated: True`). When a round ends
    `round_done` replaces the estimate with the exact total
    (`estimated: False`). Estimates are throttled to one event per
    `min_interval` seconds - a token event per chunk is already plenty of
    traffic. `on_event` may be None (non-streaming callers): then no-op.
    """

    def __init__(self, on_event: Callable[[dict[str, Any]], Awaitable[None]] | None, min_interval: float = 0.4) -> None:
        self._on_event = on_event
        self._min_interval = min_interval
        self._exact = 0
        self._chars = 0
        self._last = 0.0

    async def chars(self, count: int) -> None:
        self._chars += count
        now = time.monotonic()
        if self._on_event is None or now - self._last < self._min_interval:
            return
        self._last = now
        await self._on_event(step_event("usage", total_tokens=self._exact + self._chars // 4, estimated=True))

    async def round_done(self, round_tokens: int | None) -> None:
        self._chars = 0
        if round_tokens is not None:
            self._exact += round_tokens
        if self._on_event is not None:
            await self._on_event(step_event("usage", total_tokens=self._exact, estimated=False))


class ChatCancelled(Exception):
    """Raised by a provider the moment it notices (via cancellation.py,
    checked between rounds of its tool-calling loop) that the user
    cancelled this turn. Caught in server.py's ask() tool, which turns it
    into a clean {"cancelled": True} result rather than an MCP tool
    error - this is an expected user action, not a failure."""


@catalog
@dataclass
class ToolCallRecord:
    """One tool invocation's full detail - name, the arguments the model
    supplied, and the result text that went back to it."""

    name: str
    arguments: dict[str, Any]
    result: str


@catalog
@dataclass
class ChatResult:
    response: str
    tools_used: list[str] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    provider_id: str = ""
    model: str = ""
    total_tokens: int | None = None
    context_tokens: int | None = None


@catalog
class BaseProvider:
    """Shared, provider-agnostic pieces of claude_provider.py and
    openai_provider.py: key/cooldown checks, the delegate-or-call_tool
    dispatch, and default-model resolution from configs/config_llms.json's
    gateway block (so an OpenRouter-style gateway model override works the
    same way for both).

    The SDK-shaped bits (client construction, the tool-calling loop
    itself) stay in each subclass since the Anthropic Messages API and
    OpenAI Responses API are structurally different - forcing those into
    a shared method would just replace duplication with a pile of hooks.
    """

    PROVIDER_ID: str
    DEFAULT_MODEL_FALLBACK: str

    @catalog
    @classmethod
    def has_api_key(cls) -> bool:
        """Whether the CURRENTLY SELECTED gateway (see GATEWAY_ENV) has its
        required secret(s) resolved - gateway-specific, since each block in
        configs/config_llms.json points at different env var(s). Each
        subclass overrides this to check its own gateway's shape (plain
        api_key/auth_token vs bedrock's AWS triple vs vertex's project_id).
        """
        raise NotImplementedError

    @catalog
    @classmethod
    def is_available(cls) -> bool:
        return cls.has_api_key() and not cooldown.is_in_cooldown(cls.PROVIDER_ID)

    @catalog
    @classmethod
    def resolve_default_model(cls) -> str:
        return cls.DEFAULT_MODEL_FALLBACK
