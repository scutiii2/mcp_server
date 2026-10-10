"""Calls ai_agent's Laya agent over MCP: its `ask` tool takes the typed-question
JSON as `question` and returns a dict whose `response` is the answer JSON."""

from __future__ import annotations

import json
from typing import Any

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

INTERNAL_TOKEN_HEADER = "X-Internal-Token"


def parse_laya_reply(result: dict[str, Any]) -> dict[str, Any]:
    """The Laya answer object inside ai_agent's `ask` result; ValueError if it is anything else."""
    raw = result.get("response")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("Laya returned no response.")
    try:
        reply = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("Laya returned a response that is not JSON.") from error
    if not isinstance(reply, dict) or not isinstance(reply.get("answers"), dict):
        raise ValueError("Laya returned no answers.")
    return reply


class McpLayaTransport:
    def __init__(self, url: str, token: str) -> None:
        self._url = url
        self._headers = {INTERNAL_TOKEN_HEADER: token} if token else {}

    async def ask(self, payload: dict[str, Any]) -> dict[str, Any]:
        async with streamablehttp_client(self._url, headers=self._headers) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("ask", {"question": json.dumps(payload)})
        if result.isError:
            raise ValueError("Laya reported an error.")
        data = result.structuredContent
        if not isinstance(data, dict):
            text = next((block.text for block in result.content if getattr(block, "text", None)), "")
            try:
                data = json.loads(text)
            except json.JSONDecodeError as error:
                raise ValueError("Laya returned an unreadable result.") from error
        return parse_laya_reply(data)
