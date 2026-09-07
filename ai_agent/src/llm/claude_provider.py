"""Anthropic Messages API provider - pinned by agent_config.py when
AI_AGENT_PROVIDER=claude.

Adapted from chat_app/src/services/llm/claude_provider.py: tool calls go
through src.mcp_upstream instead of src.services.mcp_client; no MODELS
list or ProviderSpec registration (this project pins one provider per
instance - see agent_config.py); DEFAULT_MODEL replaces chat_app's
shared Settings object. The tool-calling loop itself, including the
cancellation checkpoint between rounds, is unchanged.
"""

from __future__ import annotations

import os
from typing import Any

from anthropic import Anthropic, RateLimitError

from src import delegation
from src.llm import cancellation, cooldown
from src.llm.base import ChatCancelled, SYSTEM_PROMPT, ChatResult, ToolCallRecord
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
    schemas = [
        {
            "name": tool.name,
            "description": tool.description or "",
            "input_schema": tool.inputSchema or {"type": "object", "properties": {}},
        }
        for tool in list_tools(enabled_extensions)
    ]
    if delegation.is_available():
        schemas.append(
            {
                "name": delegation.TOOL_NAME,
                "description": delegation.tool_description(),
                "input_schema": delegation.TOOL_PARAMETERS,
            }
        )
    return schemas


def _dispatch(name: str, arguments: dict[str, Any], depth: int) -> str:
    if name == delegation.TOOL_NAME:
        return delegation.call(arguments["agent_id"], arguments["question"], depth)
    return call_tool(name, arguments)


def run_chat(
    question: str,
    history: list[dict[str, Any]],
    model: str | None = None,
    enabled_extensions: list[str] | None = None,
    request_id: str | None = None,
    depth: int = 0,
) -> ChatResult:
    client = _get_client()
    model_name = model or DEFAULT_MODEL
    messages: list[dict[str, Any]] = [*history, {"role": "user", "content": question}]
    tools_used: list[str] = []
    tool_calls: list[ToolCallRecord] = []
    tool_schemas = _tool_schemas(enabled_extensions)
    # Every round of this loop is a real, separately-billed API call, so a
    # multi-tool-call answer's total is the sum across all rounds, not just
    # the final one. Anthropic's usage object has input_tokens/output_tokens
    # but no total_tokens field of its own - always present on this API, so
    # this stays a plain int rather than the optional/"unknown" handling the
    # other providers need.
    total_tokens = 0

    try:
        for _ in range(6):
            if cancellation.is_cancelled(request_id):
                raise ChatCancelled()
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
                    result_text = _dispatch(block.name, block.input, depth)
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
