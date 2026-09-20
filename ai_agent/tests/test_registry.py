"""Regression tests for reconnecting an MCP session after it terminates."""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from types import SimpleNamespace

from src.registry import McpClientRegistry


class _Session:
    def __init__(self, result=None, error: Exception | None = None):
        self._result = result
        self._error = error

    async def call_tool(self, name, arguments, read_timeout_seconds):
        if self._error is not None:
            raise self._error
        return self._result


def test_call_tool_reconnects_once_after_a_terminated_session(monkeypatch):
    """A server restart must not require restarting the AI agent."""
    registry = McpClientRegistry()
    first = _Session(error=RuntimeError("Session terminated"))
    recovered = _Session(result="recovered")
    registry._sessions["main"] = first

    reconnects = []

    async def reconnect(server_id):
        reconnects.append(server_id)
        registry._sessions[server_id] = recovered

    monkeypatch.setattr(registry, "_reconnect", reconnect)

    result = asyncio.run(registry.call_tool("main__parse_excel_input_tool", {"file_path": "test_input.xlsx"}))

    assert result == "recovered"
    assert reconnects == ["main"]
