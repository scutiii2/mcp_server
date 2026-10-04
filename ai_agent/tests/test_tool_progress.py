"""A tool's live progress reaches the chat stream as step_progress events,
through the tool_progress ContextVar, before the step finishes."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from src import mcp_upstream, tool_progress
from src.llm.base_provider import dispatch_with_progress
from src.registry import McpClientRegistry


def test_dispatch_with_progress_emits_step_progress_events_in_order():
    events: list[dict] = []

    async def on_event(event):
        events.append(event)

    def dispatch(name, arguments, depth):
        sink = tool_progress.current()
        sink("connecting")
        sink("reading log")
        return f"{name}:done"

    result = asyncio.run(dispatch_with_progress(dispatch, on_event, "step-1", "tool_x", {}, 0))

    assert result == "tool_x:done"
    assert events == [
        {"type": "step_progress", "id": "step-1", "message": "connecting"},
        {"type": "step_progress", "id": "step-1", "message": "reading log"},
    ]
    assert tool_progress.current() is None  # unbound afterwards


def test_dispatch_with_progress_without_on_event_is_a_plain_call():
    seen = []

    def dispatch(name):
        seen.append(tool_progress.current())
        return name

    assert asyncio.run(dispatch_with_progress(dispatch, None, "s", "t")) == "t"
    assert seen == [None]


def test_mcp_upstream_call_tool_passes_the_bound_sink_to_the_client():
    sink = lambda message: None  # noqa: E731
    fake_result = type("R", (), {"content": [type("B", (), {"text": "ok"})()]})()
    with patch.object(mcp_upstream.client, "call_tool", return_value=fake_result) as call_tool:
        token = tool_progress.bind(sink)
        try:
            assert mcp_upstream.call_tool("main__t", {"a": 1}) == "ok"
        finally:
            tool_progress.reset(token)
        call_tool.assert_called_once_with("main__t", {"a": 1}, on_progress=sink)

        call_tool.reset_mock()
        mcp_upstream.call_tool("main__t", {"a": 1})
        call_tool.assert_called_once_with("main__t", {"a": 1})


def test_registry_call_tool_forwards_progress_messages():
    registry = McpClientRegistry()
    session = AsyncMock()

    async def fake_call_tool(name, arguments, read_timeout_seconds=None, progress_callback=None):
        await progress_callback(1, None, "step")
        await progress_callback(2, None, None)
        return "result"

    session.call_tool = fake_call_tool
    registry._sessions["main"] = session
    seen: list[str] = []

    result = asyncio.run(registry.call_tool("main__t", {}, on_progress=seen.append))

    assert result == "result"
    assert seen == ["step"]
