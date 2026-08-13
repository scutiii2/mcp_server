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
question. Point OLLAMA_MODELS at a larger locally-hosted model if
reliability matters more than running fully local on a 1B model.

No rate-limit cooldown wiring here, unlike the two cloud providers, for
the reason it isn't needed: local inference doesn't 429.

No live reachability check here (has_api_key()/is_available() are both
unconditionally True) - matches every other provider's convention of a
cheap, synchronous check with no network call, since the provider
dropdown polls /api/providers every 15s. This means Ollama being
unreachable (host off, wrong URL, LAN down) surfaces as a normal chat-
time error rather than a greyed-out option - same as any other provider
whose key looks present but is actually unusable.
"""

from __future__ import annotations

import json
import os
from typing import Any

from chat_app.services.llm.base import SYSTEM_PROMPT, ChatResult, ModelOption, ProviderSpec
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


def _parse_models_from_env() -> list[ModelOption]:
    """Format: "model_id=Label,model_id=Label" - using "=" as the
    id/label separator, deliberately NOT the ":" that would otherwise be
    the obvious choice. Ollama model IDs almost always contain a colon
    themselves (the name:tag format, e.g. "qwen2.5:3b"), so ":" as the
    id/label separator made "qwen2.5:3b:My Label" genuinely ambiguous to
    parse: it split on the FIRST colon, silently truncating the id to
    "qwen2.5" and losing the ":3b" tag, which then 404'd against Ollama.
    "=" never appears in an Ollama model id, so there's no equivalent
    ambiguity with it."""
    raw = os.getenv("OLLAMA_MODELS", "llama3.2:1b=Llama 3.2 1B (local)")
    models: list[ModelOption] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        model_id, _, label = entry.partition("=")
        model_id = model_id.strip()
        if model_id:
            models.append(ModelOption(id=model_id, label=label.strip() or model_id))
    return models


MODELS = _parse_models_from_env()
_DEFAULT_MODEL_ID = MODELS[0].id if MODELS else "llama3.2:1b"

_client: Any = None


def _get_client() -> Any:
    global _client
    if _client is None:
        from openai import OpenAI  # already a chat_app dependency - see module docstring

        _client = OpenAI(base_url=_base_url(), api_key="ollama")
    return _client


def _tool_schemas() -> list[dict[str, Any]]:
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
        for tool in list_tools()
    ]


def run_chat(question: str, history: list[dict[str, Any]], model: str | None = None) -> ChatResult:
    client = _get_client()
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}, *history]
    messages.append({"role": "user", "content": question})
    tools_used: list[str] = []
    tool_schemas = _tool_schemas()
    model_name = model or _DEFAULT_MODEL_ID

    for _ in range(6):
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            tools=tool_schemas if tool_schemas else None,
        )
        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None) or []

        if not tool_calls:
            return ChatResult(response=message.content or "", tools_used=tools_used, provider_id=PROVIDER_ID)

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
        response="Reached maximum tool-call rounds without a final answer.", tools_used=tools_used, provider_id=PROVIDER_ID
    )


PROVIDER = ProviderSpec(
    id=PROVIDER_ID,
    label="Local (Ollama)",
    has_api_key=has_api_key,
    is_available=is_available,
    run_chat=run_chat,
    models=MODELS,
    default_model_id=_DEFAULT_MODEL_ID,
)