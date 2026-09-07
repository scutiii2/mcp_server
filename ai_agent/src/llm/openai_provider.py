"""OpenAI Responses API provider - pinned by agent_config.py when
AI_AGENT_PROVIDER=openai.

Adapted from chat_app/src/services/llm/openai_provider.py - see
claude_provider.py's module docstring for what changed and why.
"""

from __future__ import annotations

import json
import os
from typing import Any

from openai import OpenAI, RateLimitError

from src import delegation
from src.llm import cancellation, cooldown
from src.llm.base import ChatCancelled, SYSTEM_PROMPT, ChatResult, ToolCallRecord
from src.mcp_upstream import call_tool, list_tools


PROVIDER_ID = "openai"

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-sol")

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
    schemas = [
        {
            "type": "function",
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.inputSchema or {"type": "object", "properties": {}},
        }
        for tool in list_tools(enabled_extensions)
    ]
    if delegation.is_available():
        schemas.append(
            {
                "type": "function",
                "name": delegation.TOOL_NAME,
                "description": delegation.tool_description(),
                "parameters": delegation.TOOL_PARAMETERS,
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
    messages: list[Any] = [{"role": "system", "content": SYSTEM_PROMPT}, *history]
    messages.append({"role": "user", "content": question})
    tools_used: list[str] = []
    tool_calls: list[ToolCallRecord] = []
    tool_schemas = _tool_schemas(enabled_extensions)
    # Stays None (rather than 0) until a round actually reports usage -
    # some SDK versions leave response.usage unset, and a provider that
    # never reported usage should say "unknown" (see ChatResult.total_tokens),
    # not "zero tokens".
    total_tokens: int | None = None

    try:
        for _ in range(6):
            if cancellation.is_cancelled(request_id):
                raise ChatCancelled()
            response = client.responses.create(
                model=model_name,
                input=messages,
                tools=tool_schemas if tool_schemas else None,
            )
            usage = getattr(response, "usage", None)
            round_tokens = getattr(usage, "total_tokens", None) if usage is not None else None
            if round_tokens is not None:
                total_tokens = (total_tokens or 0) + round_tokens

            function_calls = [item for item in response.output if getattr(item, "type", "") == "function_call"]
            if not function_calls:
                return ChatResult(
                    response=response.output_text,
                    tools_used=tools_used,
                    tool_calls=tool_calls,
                    provider_id=PROVIDER_ID,
                    model=model_name,
                    total_tokens=total_tokens,
                )

            messages.extend(response.output)
            for call in function_calls:
                try:
                    arguments = json.loads(call.arguments or "{}")
                except Exception:
                    arguments = {}
                tools_used.append(call.name)
                try:
                    result_text = _dispatch(call.name, arguments, depth)
                except Exception as error:
                    result_text = f"Tool '{call.name}' failed: {error}"
                tool_calls.append(ToolCallRecord(name=call.name, arguments=arguments, result=result_text))
                messages.append({"type": "function_call_output", "call_id": call.call_id, "output": result_text})
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
