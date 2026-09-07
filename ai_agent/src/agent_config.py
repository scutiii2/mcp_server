"""Resolves this ai_agent instance's pinned LLM provider+model, once, at
import time - fails loudly if AI_AGENT_PROVIDER is missing, unknown, or
its API key isn't configured, rather than discovering that on the first
real request.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from src.llm import cancellation, claude_provider, cooldown, openai_provider
from src.llm.base import ChatResult

_SECRETS_PATH = Path(__file__).resolve().parent.parent / "secrets" / "secret_llm.env"

_PROVIDERS = {
    "claude": claude_provider,
    "openai": openai_provider,
}


class AgentConfigError(Exception):
    """Raised at import time for a missing/unknown AI_AGENT_PROVIDER, or
    a missing API key for the selected provider."""


def _load_secrets_into_environ() -> None:
    for key, value in dotenv_values(_SECRETS_PATH).items():
        if value:
            os.environ.setdefault(key, value)


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


def run_chat(
    question: str,
    history: list[dict[str, Any]],
    enabled_extensions: list[str],
    request_id: str | None = None,
    depth: int = 0,
) -> ChatResult:
    cancellation.register(request_id)
    try:
        return _PROVIDER_MODULE.run_chat(question, history, MODEL, enabled_extensions, request_id, depth)
    finally:
        cancellation.clear(request_id)


def cancel(request_id: str) -> bool:
    return cancellation.cancel(request_id)


def status() -> dict[str, Any]:
    reason = None
    if not _PROVIDER_MODULE.has_api_key():
        reason = "missing_key"
    elif cooldown.is_in_cooldown(PROVIDER_ID):
        reason = "rate_limited"
    return {
        "provider_id": PROVIDER_ID,
        "model": MODEL or _PROVIDER_MODULE.DEFAULT_MODEL,
        "available": _PROVIDER_MODULE.is_available(),
        "reason": reason,
        "cooldown_seconds_remaining": int(cooldown.seconds_remaining(PROVIDER_ID)),
    }
