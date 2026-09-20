"""Resolves this ai_agent instance's pinned LLM provider+model, once, at
import time - fails loudly if AI_AGENT_PROVIDER is missing, unknown, or
its API key isn't configured, rather than discovering that on the first
real request.
"""

from __future__ import annotations

import inspect
import os
from pathlib import Path
from typing import Any

import anyio
from dotenv import dotenv_values

_SECRETS_PATH = Path(__file__).resolve().parent.parent / "secrets" / "secret_llm.env"


def _load_secrets_into_environ() -> None:
    for key, value in dotenv_values(_SECRETS_PATH).items():
        if value:
            os.environ.setdefault(key, value)


# Must run BEFORE importing anthropic_provider/openai_provider below: each
# resolves its own DEFAULT_MODEL/VENDOR_LABEL from AI_AGENT_GATEWAY (see
# their resolve_default_model/resolve_vendor_label) once, at ITS OWN import
# time. If secret_llm.env's AI_AGENT_GATEWAY were loaded any later (e.g.
# inside _resolve(), as this used to do), a gateway chosen only via the
# file - not via server.py's --gateway CLI flag, which sets the env var
# before any import happens - would never take effect: the provider module
# would already have resolved "claude"/"gpt" (no gateway set yet) by the
# time this function's caller got around to loading the file. The same
# ordering invariant covers AI_AGENT_ROLE: it's read by src/llm/agent_roles.py,
# which anthropic_provider/openai_provider import transitively for
# SYSTEM_PROMPT, resolved once at agent_roles.py's own import time - if this
# call ran any later, a role set only in secret_llm.env would silently fall
# back to the config's default_role instead of failing loudly or applying,
# a worse failure mode than the gateway case above since it doesn't surface
# as a visible auth failure.
_load_secrets_into_environ()

from src.llm import anthropic_provider, cancellation, cooldown, openai_provider  # noqa: E402
from src.llm.base_provider import ChatCancelled, ChatResult  # noqa: E402
from src.llm.model_limits import context_window_for  # noqa: E402

_PROVIDERS = {
    "anthropic": anthropic_provider,
    "openai": openai_provider,
}


class AgentConfigError(Exception):
    """Raised at import time for a missing/unknown AI_AGENT_PROVIDER, or
    a missing API key for the selected provider."""


def _resolve() -> tuple[str, Any]:
    _load_secrets_into_environ()
    provider_id = os.getenv("AI_AGENT_PROVIDER")
    if not provider_id:
        raise AgentConfigError(
            f"AI_AGENT_PROVIDER is not set in {_SECRETS_PATH} - must be one of: {', '.join(sorted(_PROVIDERS))}"
        )
    module = _PROVIDERS.get(provider_id)
    if module is None:
        raise AgentConfigError(
            f"Unknown AI_AGENT_PROVIDER {provider_id!r} - must be one of: {', '.join(sorted(_PROVIDERS))}"
        )
    if not module.has_api_key():
        raise AgentConfigError(
            f"AI_AGENT_PROVIDER is {provider_id!r} but its API key is not configured in {_SECRETS_PATH}"
        )
    return provider_id, module


PROVIDER_ID, _PROVIDER_MODULE = _resolve()
MODEL = os.getenv("AI_AGENT_MODEL") or None


async def run_chat(
    question: str,
    history: list[dict[str, Any]],
    enabled_extensions: list[str],
    request_id: str | None = None,
    depth: int = 0,
    on_event: Any = None,
) -> ChatResult:
    """Run a chat completion request through the configured provider.

    Both anthropic_provider and openai_provider's run_chat are async
    (support streaming, forwarding on_event for live step_start/step_end/
    token events) - awaited directly here. The iscoroutinefunction check
    stays as a safety net for any future provider module that hasn't been
    converted yet: a sync run_chat would run in a worker thread via
    anyio.to_thread.run_sync so a slow completion doesn't block other
    requests this process is serving, with on_event dropped since a sync
    provider has nowhere to await it from.
    """
    cancellation.register(request_id)
    try:
        if cancellation.is_cancelled(request_id):
            raise ChatCancelled()
        if inspect.iscoroutinefunction(_PROVIDER_MODULE.run_chat):
            return await _PROVIDER_MODULE.run_chat(
                question, history, MODEL, enabled_extensions, request_id, depth,
                on_event=on_event,
            )
        # Phase 1: openai_provider is still sync - run it off the event
        # loop thread so a slow completion doesn't block other requests
        # this ai_agent process is serving. on_event is dropped here on
        # purpose: a sync provider has nowhere to await it from (Phase 3
        # converts openai_provider the same way Task 3 did anthropic_provider).
        return await anyio.to_thread.run_sync(
            lambda: _PROVIDER_MODULE.run_chat(
                question, history, MODEL, enabled_extensions, request_id, depth,
            )
        )
    finally:
        cancellation.clear(request_id)


def run_interpret(text: str) -> ChatResult:
    """A single non-agentic completion - see llm/anthropic_provider.py's
    run_interpret. Unlike run_chat, this never registers/clears
    cancellation: it's always one call, not a multi-round loop a user
    could need to interrupt mid-way."""
    return _PROVIDER_MODULE.run_interpret(text, MODEL)


def cancel(request_id: str) -> bool:
    return cancellation.cancel(request_id)


def status() -> dict[str, Any]:
    reason = None
    if not _PROVIDER_MODULE.has_api_key():
        reason = "missing_key"
    elif cooldown.is_in_cooldown(PROVIDER_ID):
        reason = "rate_limited"
    model = MODEL or _PROVIDER_MODULE.DEFAULT_MODEL
    return {
        "provider_id": PROVIDER_ID,
        "vendor_label": _PROVIDER_MODULE.VENDOR_LABEL,
        "model": model,
        "available": _PROVIDER_MODULE.is_available(),
        "reason": reason,
        "cooldown_seconds_remaining": int(cooldown.seconds_remaining(PROVIDER_ID)),
        "context_window": context_window_for(model),
    }
