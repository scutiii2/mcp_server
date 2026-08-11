"""OpenAI Responses API loop with locally-executed MCP tool calls.

Tool schemas come from ``mcp_client.tool_schemas_for_openai()`` - the same
live catalog the capabilities page shows. There is no separate hand-written
"here's what each tool is for" prompt block to keep in sync; each tool's
own description (set once, in its contract/tools module) is what both
OpenAI and the capabilities page see.
"""

from __future__ import annotations

import json
import os
from typing import Any

from openai import OpenAI

from chat_app.config import settings
from chat_app.services.mcp_client import call_tool, tool_schemas_for_openai


SYSTEM_PROMPT = (
    "You are a SAP Basis administrator assistant. Use tools to get real "
    "data - never guess. Confirm before any destructive action (stop/start "
    "a system, kernel update, rename)."
)

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not configured")
        _client = OpenAI(api_key=api_key)
    return _client


def run_chat(question: str, history: list[dict[str, Any]]) -> dict[str, Any]:
    client = _get_client()
    messages: list[Any] = [{"role": "system", "content": SYSTEM_PROMPT}, *history]
    messages.append({"role": "user", "content": question})
    tools_used: list[str] = []
    tool_schemas = tool_schemas_for_openai()

    for _ in range(6):
        response = client.responses.create(
            model=settings.openai_model,
            input=messages,
            tools=tool_schemas if tool_schemas else None,
        )
        function_calls = [item for item in response.output if getattr(item, "type", "") == "function_call"]
        if not function_calls:
            return {"response": response.output_text, "tools_used": tools_used}

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

    return {"response": "Reached maximum tool-call rounds without a final answer.", "tools_used": tools_used}
