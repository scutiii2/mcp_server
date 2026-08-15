"""Local Ollama provider, via Ollama's OpenAI Chat-Completions-compatible
endpoint (``/v1/chat/completions``).

Reuses the ``openai`` package already in chat_app's dependencies (see
pyproject.toml) rather than adding an Ollama-specific SDK - Ollama's
compatibility layer is deliberately built to be a drop-in target for the
OpenAI client, just pointed at a different ``base_url``.

Deliberately uses the OLDER Chat-Completions shape, not the newer
Responses API shape openai_provider.py uses. Ollama's own documentation
describes its ``/v1/responses`` support as still preliminary as of this
writing, while ``/v1/chat/completions`` (including tool calling) is the
mature, long-documented path - this deliberately doesn't rely on the
newer one.

No API key needed - Ollama has no auth by default. The OpenAI client
still requires *some* string for ``api_key``, so this passes the literal
placeholder ``"ollama"``, matching Ollama's own documented convention.
Never a real secret, never read from an env var.

Honest caveat about small local models and tool calling: the default
model this was set up against (``llama3.2:1b``) does have Ollama's
tool-calling template support built in - that part isn't guesswork. But
every independent guide on Ollama tool-calling agrees smaller models are
the least reliable at producing well-formed ``tool_calls`` JSON, and most
already call 3B unreliable for production tool use - 1B is smaller than
that. Expect this provider to work fine for simple, low-tool-count
questions and to sometimes answer in prose instead of calling a tool, or
produce malformed arguments, as the tool surface grows. That's why
router.py deliberately leaves this OUT of AUTOMATIC_ORDER - manual-select
only, so a flaky local model never silently becomes what answers a real
question. List a larger locally-hosted model in config.json's
"providers.ollama.models" (see infra/app_config.py) if reliability
matters more than running fully local on a 1B model.

No rate-limit cooldown wiring here, unlike the two cloud providers, for
the reason it isn't needed: local inference doesn't 429.

has_api_key()/is_available() are still both unconditionally True - no
auth concept here, so neither can meaningfully fail. What DOES get a
live check now is per-model availability: MODELS is the operator's
WISH list (read once at startup, from config.json - see below), and
check_model_availability() below verifies live, via Ollama's own
/api/tags, which of those are actually pulled on the host right now.
That's a deliberate split - the model list itself only changes when
someone edits config.json and restarts (same as OLLAMA_MODELS before
it - this isn't a regression, env vars already required a restart),
but whether a given entry actually works can change any time someone
runs `ollama pull`/`ollama rm`, so that half is checked on every
/api/providers request instead of trusted from a stale list.
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.request import urlopen

from chat_app.config import settings
from chat_app.infra.app_config import load_ollama_models
from chat_app.services.llm.base import (
    SYSTEM_PROMPT,
    ChatResult,
    ModelAvailability,
    ModelAvailabilityCheck,
    ModelOption,
    ProviderSpec,
)
from chat_app.services.mcp_client import call_tool, list_tools


PROVIDER_ID = "ollama"


def _base_url() -> str:
    """Point this at your Ollama host's LAN address, not localhost,
    whenever chat_app and Ollama run on different machines (chat_app on
    your dev machine, Ollama on a homelab/NAS box on the same network).
    Ollama itself binds to 127.0.0.1 only by default on a plain install -
    if this times out or gets connection-refused, check that
    OLLAMA_HOST=0.0.0.0 (or equivalent) is set on the Ollama side, not
    just this env var on the chat_app side."""
    return os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")


def has_api_key() -> bool:
    """No real auth for Ollama - always True. Kept as a function, not a
    constant, for interface parity with every other provider."""
    return True


def is_available() -> bool:
    return has_api_key()


# Read once at startup, from config.json's "providers.ollama.models" -
# see infra/app_config.py. An empty list (no config.json, or no
# "providers.ollama" section) means no models are offered; that's a
# valid, quiet deployment state, not an error - see load_ollama_models's
# docstring.
MODELS = load_ollama_models(settings.chat_config_path)
_DEFAULT_MODEL_ID = MODELS[0].id if MODELS else ""

_client: Any = None


def _get_client() -> Any:
    global _client
    if _client is None:
        from openai import OpenAI  # already a chat_app dependency - see module docstring

        _client = OpenAI(base_url=_base_url(), api_key="ollama")
    return _client


def _tool_schemas(enabled_extensions: list[str] | None = None) -> list[dict[str, Any]]:
    """Chat-Completions function-wrapped shape - note this nests the
    schema under a "function" key, unlike openai_provider.py's flatter
    Responses API shape."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.inputSchema or {"type": "object", "properties": {}},
            },
        }
        for tool in list_tools(enabled_extensions)
    ]


def _usage_tokens(usage: Any) -> int | None:
    """Best-effort token count for one round of the Chat Completions loop.

    Ollama doesn't always populate ``usage`` depending on version - a
    missing usage object, or one that reports zero on both fields, means
    this round contributed nothing countable (not that zero tokens were
    genuinely used), so this returns None rather than 0 for either case."""
    if usage is None:
        return None
    total = getattr(usage, "total_tokens", None)
    if not total:
        prompt = getattr(usage, "prompt_tokens", None) or 0
        completion = getattr(usage, "completion_tokens", None) or 0
        total = prompt + completion
    return total or None


def run_chat(
    question: str,
    history: list[dict[str, Any]],
    model: str | None = None,
    enabled_extensions: list[str] | None = None,
) -> ChatResult:
    client = _get_client()
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}, *history]
    messages.append({"role": "user", "content": question})
    tools_used: list[str] = []
    tool_schemas = _tool_schemas(enabled_extensions)
    model_name = model or _DEFAULT_MODEL_ID
    # Every round of this loop is a real, separately-billed API call, so a
    # multi-tool-call answer's total is the sum across all rounds, not just
    # the final one. Stays None (rather than 0) until a round actually
    # reports usage - only report a number if at least one round gave us
    # one, consistent with ChatResult.total_tokens's "unknown" semantics.
    total_tokens: int | None = None

    for _ in range(6):
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            tools=tool_schemas if tool_schemas else None,
        )
        round_tokens = _usage_tokens(getattr(response, "usage", None))
        if round_tokens is not None:
            total_tokens = (total_tokens or 0) + round_tokens

        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None) or []

        if not tool_calls:
            return ChatResult(response=message.content or "", tools_used=tools_used, provider_id=PROVIDER_ID, total_tokens=total_tokens)

        messages.append({"role": "assistant", "content": message.content, "tool_calls": tool_calls})
        for call in tool_calls:
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except Exception:
                arguments = {}
            tools_used.append(call.function.name)
            try:
                result_text = call_tool(call.function.name, arguments)
            except Exception as error:
                result_text = f"Tool '{call.function.name}' failed: {error}"
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result_text})

    return ChatResult(
        response="Reached maximum tool-call rounds without a final answer.",
        tools_used=tools_used,
        provider_id=PROVIDER_ID,
        total_tokens=total_tokens,
    )


# Short enough that a hung/unreachable Ollama host doesn't make the
# /api/providers poll (every 15s, from every open chat tab) noticeably
# laggy. A real LAN round-trip to a host that's actually up is
# millisecond-scale; this is sized for "host is off/unreachable", not
# for a slow-but-working one.
_AVAILABILITY_TIMEOUT_SECONDS = 2.0


def _tags_url() -> str:
    """Ollama's native model-listing endpoint - GET /api/tags - lives at
    the ROOT of the Ollama host, unlike /v1/chat/completions. _base_url()
    defaults to ".../11434/v1"; strip a trailing "/v1" (or "/v1/") to get
    back to the root before appending "/api/tags"."""
    base = _base_url().rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    return f"{base}/api/tags"


def check_model_availability() -> ModelAvailabilityCheck:
    """Live check of which of MODELS (the operator's desired list, read
    once at startup - see above) are actually pulled on the Ollama host
    right now.

    Ollama's documented /api/tags response shape (docs/api.md, "List
    Local Models") is::

        {"models": [{"name": "qwen2.5:7b", "model": "qwen2.5:7b", ...}]}

    "name" is already in the same name:tag form as a configured model id,
    so this is a plain exact-string match - no normalization needed.

    Fails closed: connection refused, timeout, non-2xx (urlopen raises
    for those), invalid JSON, or a payload missing the "models" list -
    all collapse to the same "unreachable" outcome, with every configured
    model marked unavailable too, rather than raising out of a route
    that's polled every 15 seconds by every open chat tab.
    """
    configured_ids = [model.id for model in MODELS]
    if not configured_ids:
        # Nothing configured to verify - config.json has no
        # "providers.ollama.models" entries (or no config.json at all),
        # which is a valid quiet deployment state, not a failure. Skips
        # the network call entirely rather than probing a host nobody
        # asked this deployment to use.
        return ModelAvailabilityCheck(reachable=True, reason=None, models={})

    try:
        with urlopen(_tags_url(), timeout=_AVAILABILITY_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
        pulled_names = {str(entry["name"]) for entry in payload["models"]}
    except Exception:
        return ModelAvailabilityCheck(
            reachable=False,
            reason="unreachable",
            models={
                model_id: ModelAvailability(available=False, reason="unreachable")
                for model_id in configured_ids
            },
        )

    models = {
        model_id: (
            ModelAvailability(available=True, reason=None)
            if model_id in pulled_names
            else ModelAvailability(available=False, reason="not_pulled")
        )
        for model_id in configured_ids
    }
    return ModelAvailabilityCheck(reachable=True, reason=None, models=models)


PROVIDER = ProviderSpec(
    id=PROVIDER_ID,
    label="Local (Ollama)",
    has_api_key=has_api_key,
    is_available=is_available,
    run_chat=run_chat,
    models=MODELS,
    default_model_id=_DEFAULT_MODEL_ID,
    check_models=check_model_availability,
)