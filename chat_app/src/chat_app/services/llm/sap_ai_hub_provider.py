"""SAP Generative AI Hub provider (SAP AI Core), via the sap-ai-sdk-gen package.

This is architecturally different from openai_provider.py/claude_provider.py
in two ways worth understanding before touching this file:

1. Authentication isn't a single API key - it's OAuth2 client-credentials
   auth against SAP AI Core, needing four env vars (AICORE_CLIENT_ID,
   AICORE_CLIENT_SECRET, AICORE_AUTH_URL, AICORE_BASE_URL), typically
   pulled from a BTP service key JSON, plus AICORE_RESOURCE_GROUP.

2. Model availability is tenant-specific: each usable model must already
   be provisioned as a "deployment" in your own BTP AI Core subaccount
   before it's callable here. There's no universal model-id list the way
   there is for OpenAI's or Anthropic's own public APIs, so MODELS below
   is parsed from an env var instead of hardcoded - edit SAP_AI_HUB_MODELS
   to match whatever you've actually deployed, not this file.

Package: ``sap-ai-sdk-gen`` (formerly ``generative-ai-hub-sdk`` - SAP kept
all class/module names the same across the rebrand, per their own release
notes). NOT runtime-verified against a real installed copy in the sandbox
this was built in (no network access to pip install SAP's package there).
The calling convention below - ``gen_ai_hub.proxy.native.openai.chat.completions.create``
with OpenAI Chat-Completions-shaped messages/tools (not the newer
Responses API shape openai_provider.py uses) - matches the SDK's
documented "native OpenAI client integration" pattern. Confirm the exact
import path and parameter names against your installed version before
trusting this in production; this is the first place to look if it
doesn't work as expected.

Rate-limit cooldown is deliberately NOT wired up here, unlike the other
two providers: I don't know SAP AI Core's actual rate-limit exception
type/shape, and guessing wrong risks either never triggering a cooldown
or (worse) triggering one on unrelated errors. Any failure here just
propagates as a normal error until someone confirms the real exception
class to catch.
"""

from __future__ import annotations

import json
import os
from typing import Any

from chat_app.services.llm import cooldown
from chat_app.services.llm.base import ChatResult, ModelOption, ProviderSpec
from chat_app.services.mcp_client import call_tool, list_tools


PROVIDER_ID = "sap_ai_hub"

SYSTEM_PROMPT = (
    "You are a SAP Basis administrator assistant. Use tools to get real "
    "data - never guess. Confirm before any destructive action (stop/start "
    "a system, kernel update, rename)."
)

_REQUIRED_ENV_VARS = ["AICORE_CLIENT_ID", "AICORE_CLIENT_SECRET", "AICORE_AUTH_URL", "AICORE_BASE_URL"]


def has_api_key() -> bool:
    """Named for consistency with the other providers' interface, but
    this checks all four AICORE_* env vars the SDK needs, not one key."""
    return all(os.getenv(var) for var in _REQUIRED_ENV_VARS)


def is_available() -> bool:
    return has_api_key() and not cooldown.is_in_cooldown(PROVIDER_ID)


def _parse_models_from_env() -> list[ModelOption]:
    """Format: "deployment_model_name:Label,deployment_model_name:Label".
    Falls back to a single reasonable guess if unset - which will fail at
    call time if that exact model isn't actually deployed in your BTP AI
    Core subaccount. Edit SAP_AI_HUB_MODELS to match your real deployments."""
    raw = os.getenv("SAP_AI_HUB_MODELS", "gpt-4o:GPT-4o (via SAP AI Core)")
    models: list[ModelOption] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        model_id, _, label = entry.partition(":")
        model_id = model_id.strip()
        if model_id:
            models.append(ModelOption(id=model_id, label=label.strip() or model_id))
    return models


MODELS = _parse_models_from_env()
_DEFAULT_MODEL_ID = MODELS[0].id if MODELS else ""


def _tool_schemas() -> list[dict[str, Any]]:
    """OpenAI Chat-Completions tool shape (function-wrapped, distinct
    from openai_provider.py's flatter Responses-API shape) - matches what
    the proxy's native OpenAI client integration expects."""
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
    from gen_ai_hub.proxy.native.openai import chat  # deferred - only needed if this provider is actually used

    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}, *history]
    messages.append({"role": "user", "content": question})
    tools_used: list[str] = []
    tool_schemas = _tool_schemas()
    model_name = model or _DEFAULT_MODEL_ID

    for _ in range(6):
        response = chat.completions.create(
            model_name=model_name,
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

    return ChatResult(response="Reached maximum tool-call rounds without a final answer.", tools_used=tools_used, provider_id=PROVIDER_ID)


PROVIDER = ProviderSpec(
    id=PROVIDER_ID,
    label="SAP AI Hub",
    has_api_key=has_api_key,
    is_available=is_available,
    run_chat=run_chat,
    models=MODELS,
    default_model_id=_DEFAULT_MODEL_ID,
)
