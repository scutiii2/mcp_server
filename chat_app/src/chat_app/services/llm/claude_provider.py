"""Anthropic Messages API provider.

Deliberately mirrors ``openai_provider.py``'s structure so the two are easy
to compare, but the wire format is genuinely different in three ways:
  - tool schemas use ``input_schema`` (not ``parameters``)
  - a tool call arrives as a ``tool_use`` content block, with ``.input``
    already a parsed dict (OpenAI instead gives a JSON string you must
    ``json.loads`` yourself)
  - you reply with a ``tool_result`` block referencing ``tool_use_id``,
    inside a new user-role message - not a top-level item keyed by
    ``call_id`` the way OpenAI's Responses API expects
"""

from __future__ import annotations

import os
from typing import Any

from anthropic import Anthropic, RateLimitError

from chat_app.config import settings
from chat_app.services.llm import cooldown
from chat_app.services.llm.base import SYSTEM_PROMPT, ChatResult, ModelOption, ProviderSpec
from chat_app.services.mcp_client import call_tool, list_tools


PROVIDER_ID = "claude"

# Model IDs and labels per the current Claude lineup.
MODELS = [
    ModelOption(id="claude-opus-4-8", label="Claude Opus 4.8 (most capable)"),
    ModelOption(id="claude-sonnet-5", label="Claude Sonnet 5 (balanced)"),
    ModelOption(id="claude-haiku-4-5-20251001", label="Claude Haiku 4.5 (fast/cheap)"),
]

_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not configured")
        _client = Anthropic(api_key=api_key)
    return _client


def has_api_key() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def is_available() -> bool:
    return has_api_key() and not cooldown.is_in_cooldown(PROVIDER_ID)


def _tool_schemas() -> list[dict[str, Any]]:
    return [
        {
            "name": tool.name,
            "description": tool.description or "",
            "input_schema": tool.inputSchema or {"type": "object", "properties": {}},
        }
        for tool in list_tools()
    ]


def run_chat(question: str, history: list[dict[str, Any]], model: str | None = None) -> ChatResult:
    client = _get_client()
    messages: list[dict[str, Any]] = [*history, {"role": "user", "content": question}]
    tools_used: list[str] = []
    tool_schemas = _tool_schemas()

    try:
        for _ in range(6):
            response = client.messages.create(
                model=model or settings.claude_model,
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                messages=messages,
                tools=tool_schemas,
            )

            if response.stop_reason != "tool_use":
                text = "".join(block.text for block in response.content if block.type == "text")
                return ChatResult(response=text, tools_used=tools_used, provider_id=PROVIDER_ID)

            messages.append({"role": "assistant", "content": response.content})

            tool_results: list[dict[str, Any]] = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                tools_used.append(block.name)
                try:
                    result_text = call_tool(block.name, block.input)
                except Exception as error:
                    result_text = f"Tool '{block.name}' failed: {error}"
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result_text})

            messages.append({"role": "user", "content": tool_results})
    except RateLimitError as error:
        seconds = cooldown.extract_retry_after_seconds(error) or cooldown.DEFAULT_COOLDOWN_SECONDS
        cooldown.start_cooldown(PROVIDER_ID, seconds)
        raise

    return ChatResult(response="Reached maximum tool-call rounds without a final answer.", tools_used=tools_used, provider_id=PROVIDER_ID)


PROVIDER = ProviderSpec(
    id=PROVIDER_ID,
    label="Claude",
    has_api_key=has_api_key,
    is_available=is_available,
    run_chat=run_chat,
    models=MODELS,
    default_model_id=settings.claude_model,
)
