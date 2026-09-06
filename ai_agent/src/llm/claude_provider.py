"""Anthropic Messages API provider - pinned by agent_config.py when
AI_AGENT_PROVIDER=claude.

Adapted from chat_app/src/services/llm/claude_provider.py - see this
file's own module docstring vs. that one for exactly what changed
(tool calls go through src.mcp_upstream; no MODELS list or
ProviderSpec registration; DEFAULT_MODEL replaces chat_app's shared
Settings object). The tool-calling loop itself is unchanged.
"""

from __future__ import annotations

import os
from typing import Any

from anthropic import Anthropic, RateLimitError

from src.llm import cooldown
from src.llm.base import SYSTEM_PROMPT, ChatResult, ToolCallRecord
from src.mcp_upstream import call_tool, list_tools


PROVIDER_ID = "claude"

DEFAULT_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5")

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


def _tool_schemas(enabled_extensions: list[str] | None = None) -> list[dict[str, Any]]:
    return [
        {
            "name": tool.name,
            "description": tool.description or "",
            "input_schema": tool.inputSchema or {"type": "object", "properties": {}},
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
    model_name = model or DEFAULT_MODEL
    messages: list[dict[str, Any]] = [*history, {"role": "user", "content": question}]
    tools_used: list[str] = []
    tool_calls: list[ToolCallRecord] = []
    tool_schemas = _tool_schemas(enabled_extensions)
    total_tokens = 0

    try:
        for _ in range(6):
            response = client.messages.create(
                model=model_name,
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                messages=messages,
                tools=tool_schemas,
            )
            total_tokens += response.usage.input_tokens + response.usage.output_tokens

            if response.stop_reason != "tool_use":
                text = "".join(block.text for block in response.content if block.type == "text")
                return ChatResult(
                    response=text,
                    tools_used=tools_used,
                    tool_calls=tool_calls,
                    provider_id=PROVIDER_ID,
                    model=model_name,
                    total_tokens=total_tokens,
                )

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
                tool_calls.append(ToolCallRecord(name=block.name, arguments=block.input, result=result_text))
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result_text})

            messages.append({"role": "user", "content": tool_results})
    except RateLimitError as error:
        seconds = cooldown.extract_retry_after_seconds(error) or cooldown.DEFAULT_COOLDOWN_SECONDS
        cooldown.start_cooldown(PROVIDER_ID, seconds)
        raise

    return ChatResult(
        response="Reached maximum tool-call rounds without a final answer.",
        tools_used=tools_used,
        tool_calls=tool_calls,
        provider_id=PROVIDER_ID,
        model=model_name,
        total_tokens=total_tokens,
    )
