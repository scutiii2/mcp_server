"""OpenAI Responses API provider.

Owns its own tool-schema reshaping (``_tool_schemas``) rather than asking
``mcp_client`` for an OpenAI-flavored shape - each provider knows its own
wire format, ``mcp_client`` only knows the generic MCP one.
"""

from __future__ import annotations

import json
import os
from typing import Any

from openai import OpenAI, RateLimitError

from chat_app.config import settings
from chat_app.services.llm import cooldown
from chat_app.services.llm.base import SYSTEM_PROMPT, ChatResult, ModelOption, ProviderSpec
from chat_app.services.mcp_client import call_tool, list_tools


PROVIDER_ID = "openai"

# Model IDs confirmed against platform.openai.com/docs/models. Update this
# list (and, if the flagship changes, config.py's default) as new models
# ship - nothing else needs to change to pick them up.
MODELS = [
    ModelOption(id="gpt-5.6-sol", label="GPT-5.6 Sol (flagship)"),
    ModelOption(id="gpt-5.6-terra", label="GPT-5.6 Terra (balanced)"),
    ModelOption(id="gpt-5.6-luna", label="GPT-5.6 Luna (fast/cheap)"),
]

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not configured")
        _client = OpenAI(api_key=api_key)
    return _client


def has_api_key() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


def is_available() -> bool:
    return has_api_key() and not cooldown.is_in_cooldown(PROVIDER_ID)


def _tool_schemas(enabled_extensions: list[str] | None = None) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.inputSchema or {"type": "object", "properties": {}},
        }
        for tool in list_tools(enabled_extensions)
    ]


def run_chat(
    question: str,
    history: list[dict[str, Any]],
    model: str | None = None,
    enabled_extensions: list[str] | None = None,
) -> ChatResult:
    client = _get_client()
    messages: list[Any] = [{"role": "system", "content": SYSTEM_PROMPT}, *history]
    messages.append({"role": "user", "content": question})
    tools_used: list[str] = []
    tool_schemas = _tool_schemas(enabled_extensions)
    # Every round of this loop is a real, separately-billed API call, so a
    # multi-tool-call answer's total is the sum across all rounds, not just
    # the final one. Stays None (rather than 0) until a round actually
    # reports usage - some SDK versions leave response.usage unset, and a
    # provider that never reported usage should say "unknown" (see
    # ChatResult.total_tokens), not "zero tokens".
    total_tokens: int | None = None

    try:
        for _ in range(6):
            response = client.responses.create(
                model=model or settings.openai_model,
                input=messages,
                tools=tool_schemas if tool_schemas else None,
            )
            usage = getattr(response, "usage", None)
            round_tokens = getattr(usage, "total_tokens", None) if usage is not None else None
            if round_tokens is not None:
                total_tokens = (total_tokens or 0) + round_tokens

            function_calls = [item for item in response.output if getattr(item, "type", "") == "function_call"]
            if not function_calls:
                return ChatResult(response=response.output_text, tools_used=tools_used, provider_id=PROVIDER_ID, total_tokens=total_tokens)

            messages.extend(response.output)
            for call in function_calls:
                try:
                    arguments = json.loads(call.arguments or "{}")
                except Exception:
                    arguments = {}
                tools_used.append(call.name)
                try:
                    result_text = call_tool(call.name, arguments)
                except Exception as error:
                    result_text = f"Tool '{call.name}' failed: {error}"
                messages.append({"type": "function_call_output", "call_id": call.call_id, "output": result_text})
    except RateLimitError as error:
        seconds = cooldown.extract_retry_after_seconds(error) or cooldown.DEFAULT_COOLDOWN_SECONDS
        cooldown.start_cooldown(PROVIDER_ID, seconds)
        raise

    return ChatResult(
        response="Reached maximum tool-call rounds without a final answer.",
        tools_used=tools_used,
        provider_id=PROVIDER_ID,
        total_tokens=total_tokens,
    )


PROVIDER = ProviderSpec(
    id=PROVIDER_ID,
    label="ChatGPT",
    has_api_key=has_api_key,
    is_available=is_available,
    run_chat=run_chat,
    models=MODELS,
    default_model_id=settings.openai_model,
)
