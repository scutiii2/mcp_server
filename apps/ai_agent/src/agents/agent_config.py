"""Resolves this ai_agent instance's pinned LLM provider+model, once, at
import time - fails loudly if AI_AGENT_PROVIDER is missing, unknown, or
its API key isn't configured, rather than discovering that on the first
real request.
"""

from __future__ import annotations

import inspect
import importlib
import os
from pathlib import Path
from typing import Any

import anyio
from dotenv import dotenv_values

from src.agents import agent_spec, delegation

from src.core import approvals, internal_auth, tool_filter
from src.private_extensions import turn as private_turn
from src.llm import llm_options, model_tiers
from src.llm import reasoning_effort as effort_limits
from src.core.seed import seed_from_example

_SECRETS_PATH = Path(__file__).resolve().parent.parent.parent / ".env"


def _load_secrets_into_environ() -> None:
    seed_from_example(_SECRETS_PATH)
    for key, value in dotenv_values(_SECRETS_PATH).items():
        if value:
            os.environ.setdefault(key, value)


# Must run BEFORE importing anthropic_provider/openai_provider below: each
# resolves its own DEFAULT_MODEL/VENDOR_LABEL from AI_AGENT_GATEWAY (see
# their resolve_default_model/resolve_vendor_label) once, at ITS OWN import
# time. If .env's AI_AGENT_GATEWAY were loaded any later (e.g.
# inside _resolve(), as this used to do), a gateway chosen only via the
# file - not via server.py's --gateway CLI flag, which sets the env var
# before any import happens - would never take effect: the provider module
# would already have resolved "claude"/"gpt" (no gateway set yet) by the
# time this function's caller got around to loading the file.
_load_secrets_into_environ()

from src.llm import cancellation, cooldown  # noqa: E402
from src.llm.base_provider import ChatCancelled, ChatResult  # noqa: E402
from src.llm.model_limits import context_window_for  # noqa: E402

_PROVIDERS = {
    "anthropic": "src.llm.anthropic_provider",
    "openai": "src.llm.openai_provider",
    "laya": "src.llm.laya_provider",
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
    module_name = _PROVIDERS.get(provider_id)
    if module_name is None:
        raise AgentConfigError(
            f"Unknown AI_AGENT_PROVIDER {provider_id!r} - must be one of: {', '.join(sorted(_PROVIDERS))}"
        )
    # Import only the selected provider: a local Laya agent must not depend on
    # a cloud gateway, persona configuration or cloud SDK initialization.
    module = importlib.import_module(module_name)
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
    caveman: bool = False,
    approval_mode: str = "off",
    allowed_tools: list[str] | None = None,
    disabled_tools: list[str] | None = None,
    private_extensions: list[dict[str, Any]] | None = None,
    model_tier: str | None = None,
    reasoning_effort: str | None = None,
) -> ChatResult:
    """Run a chat completion request through the configured provider.

    reasoning_effort: the effort ("off"/"low"/"medium"/"high") the caller asks
    for (delegation.py). It is capped at this agent's llm.max_effort
    (llm/reasoning_effort.py) and applies to this turn only; the result notes
    a change. None keeps the agent's own reasoning_effort.

    model_tier: a strength tier ("light"/"standard"/"heavy") the caller asks
    for (delegation.py). It is resolved against this agent's own tiers and
    cap (llm/model_tiers.py); a request outside the cap is clamped, with a
    note on the result. None keeps the pinned model.

    disabled_tools: tools the asking user switched off for their own chats
    (see core/tool_filter.py); they are not offered and not run.

    private_extensions: the user's own MCP servers for this turn, as ember_api
    sent them (see private_extensions/turn.py). Their tools are offered after
    the user approves each one; a server that cannot be reached is reported
    in `result.private_extension_errors` and the turn goes on without it.

    approval_mode / allowed_tools: see approvals.py - with "ask" a tool runs
    only after the user allows it (tools in allowed_tools were allowed
    already); "deny" refuses any tool that would need asking.

    Both anthropic_provider and openai_provider's run_chat are async
    (support streaming, forwarding on_event for live step_start/step_end/
    token events) - awaited directly here. The iscoroutinefunction check
    stays as a safety net for any future provider module that hasn't been
    converted yet: a sync run_chat would run in a worker thread via
    anyio.to_thread.run_sync so a slow completion doesn't block other
    requests this process is serving, with on_event dropped since a sync
    provider has nowhere to await it from.
    """
    requester = internal_auth.current_requester()
    private = private_turn.PrivateTurn.from_raw(private_extensions, requester.email or requester.username)
    # Validated before anything is registered: a bad mode must not start a turn.
    policy = approvals.ApprovalPolicy(
        approval_mode, set(allowed_tools or ()), ask_prefixes=(private_turn.TOOL_PREFIX,) if private else ()
    )
    resolution = (
        model_tiers.resolve(model_tier, model_tiers.own_tiers(), MODEL, agent_spec.current().id)
        if model_tier else model_tiers.Resolution(MODEL, None)
    )
    effort = effort_limits.resolve(reasoning_effort, agent_spec.current().llm.max_effort, agent_spec.current().id)
    cancellation.register(request_id)
    delegated_usage, usage_token = delegation.bind_usage()
    approval_token = approvals.bind(policy)
    filter_token = tool_filter.bind(disabled_tools or ())
    private_token = private_turn.bind(private)
    effort_token = llm_options.bind_effort(effort.effort)
    try:
        if cancellation.is_cancelled(request_id):
            raise ChatCancelled()
        if private:
            # Imported here: laya agents never load mcp_upstream.
            from src.mcp_client import mcp_upstream

            await mcp_upstream.prefetch_private(private)
        if inspect.iscoroutinefunction(_PROVIDER_MODULE.run_chat):
            result = await _PROVIDER_MODULE.run_chat(
                question, history, resolution.model, enabled_extensions, request_id, depth,
                on_event=on_event, caveman=caveman,
            )
            result.delegated_usage = delegated_usage
        else:
            # Phase 1: openai_provider is still sync - run it off the event
            # loop thread so a slow completion doesn't block other requests
            # this ai_agent process is serving. on_event is dropped here on
            # purpose: a sync provider has nowhere to await it from (Phase 3
            # converts openai_provider the same way Task 3 did anthropic_provider).
            result = await anyio.to_thread.run_sync(
                lambda: _PROVIDER_MODULE.run_chat(
                    question, history, resolution.model, enabled_extensions, request_id, depth,
                    caveman=caveman,
                )
            )
        result.model_tier = resolution.tier
        result.model_note = resolution.note
        result.reasoning_effort = effort.effort
        result.effort_note = effort.note
        result.private_extension_errors = list(private.errors)
        return result
    finally:
        llm_options.reset_effort(effort_token)
        private_turn.reset(private_token)
        tool_filter.reset(filter_token)
        approvals.reset(approval_token)
        delegation.reset_usage(usage_token)
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
    elif not _PROVIDER_MODULE.is_available():
        reason = "unavailable"
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
