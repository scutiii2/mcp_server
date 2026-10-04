"""ai_agent_client.py tests: argument-passing for ask/status/cancel, and
the isError -> AgentToolError translation - mirroring test_mcp_client.py's
convention of mocking at the async boundary rather than hitting a real
MCP server. _call_tool's own tests drive it with a plain asyncio.run()
rather than an async test function - this suite has no pytest-asyncio
plugin installed, same as the rest of this repo.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.services import ai_agent_client


def test_ask_calls_the_ask_tool_with_every_field():
    captured = {}

    async def _fake_call_tool(url, name, arguments):
        captured["url"] = url
        captured["name"] = name
        captured["arguments"] = arguments
        return {"response": "hi", "tools_used": [], "tool_calls": [], "cancelled": False}

    with patch("src.services.ai_agent_client._call_tool", side_effect=_fake_call_tool):
        result = ai_agent_client.ask(
            "http://127.0.0.1:9100/mcp", "hello", [{"role": "user", "content": "prior"}], ["reference"], "req-1"
        )

    assert captured["url"] == "http://127.0.0.1:9100/mcp"
    assert captured["name"] == "ask"
    assert captured["arguments"] == {
        "question": "hello",
        "history": [{"role": "user", "content": "prior"}],
        "enabled_extensions": ["reference"],
        "request_id": "req-1",
        "caveman": False,
    }
    assert result["response"] == "hi"


def test_status_calls_the_status_tool_with_no_arguments():
    captured = {}

    async def _fake_call_tool(url, name, arguments):
        captured["url"] = url
        captured["name"] = name
        captured["arguments"] = arguments
        return {"provider_id": "claude", "available": True}

    with patch("src.services.ai_agent_client._call_tool", side_effect=_fake_call_tool):
        result = ai_agent_client.status("http://127.0.0.1:9100/mcp")

    assert captured == {"url": "http://127.0.0.1:9100/mcp", "name": "status", "arguments": {}}
    assert result["provider_id"] == "claude"


def test_cancel_calls_the_cancel_tool_with_request_id():
    captured = {}

    async def _fake_call_tool(url, name, arguments):
        captured["url"] = url
        captured["name"] = name
        captured["arguments"] = arguments
        return {"cancelled": True}

    with patch("src.services.ai_agent_client._call_tool", side_effect=_fake_call_tool):
        result = ai_agent_client.cancel("http://127.0.0.1:9100/mcp", "req-1")

    assert captured == {"url": "http://127.0.0.1:9100/mcp", "name": "cancel", "arguments": {"request_id": "req-1"}}
    assert result == {"cancelled": True}


def _fake_session(*, is_error: bool, content: list, structured: dict | None):
    session = AsyncMock()
    session.initialize = AsyncMock(return_value=None)
    session.call_tool = AsyncMock(
        return_value=SimpleNamespace(isError=is_error, content=content, structuredContent=structured)
    )
    return session


def test_call_tool_raises_agent_tool_error_on_iserror_result():
    session = _fake_session(is_error=True, content=[SimpleNamespace(text="claude is rate-limited")], structured=None)

    with patch("src.services.ai_agent_client.streamablehttp_client", return_value=_cm((None, None, None))), \
         patch("src.services.ai_agent_client.ClientSession", return_value=_cm(session)):
        try:
            asyncio.run(ai_agent_client._call_tool("http://127.0.0.1:9100/mcp", "ask", {}))
            raise AssertionError("expected AgentToolError")
        except ai_agent_client.AgentToolError as error:
            assert "rate-limited" in str(error)


def test_call_tool_returns_structured_content_on_success():
    session = _fake_session(is_error=False, content=[], structured={"response": "hi"})

    with patch("src.services.ai_agent_client.streamablehttp_client", return_value=_cm((None, None, None))), \
         patch("src.services.ai_agent_client.ClientSession", return_value=_cm(session)):
        result = asyncio.run(ai_agent_client._call_tool("http://127.0.0.1:9100/mcp", "ask", {"question": "hi"}))

    assert result == {"response": "hi"}


def test_ask_stream_relays_progress_then_final():
    async def fake_call_tool(name, arguments, progress_callback=None):
        if progress_callback is not None:
            await progress_callback(0, None, '{"type": "step_start", "id": "1"}')
            await progress_callback(0, None, '{"type": "token", "text": "hi"}')
        return SimpleNamespace(isError=False, content=[], structuredContent={"response": "hi", "tools_used": []})

    session = AsyncMock()
    session.initialize = AsyncMock(return_value=None)
    session.call_tool = AsyncMock(side_effect=fake_call_tool)

    async def _collect():
        events = []
        with patch("src.services.ai_agent_client.streamablehttp_client", return_value=_cm((None, None, None))), \
             patch("src.services.ai_agent_client.ClientSession", return_value=_cm(session)):
            async for event in ai_agent_client.ask_stream("http://127.0.0.1:9100/mcp", "q", [], []):
                events.append(event)
        return events

    events = asyncio.run(_collect())

    assert events[0] == {"type": "step_start", "id": "1"}
    assert events[1] == {"type": "token", "text": "hi"}
    assert events[-1] == {"type": "final", "response": "hi", "tools_used": []}


def test_ask_stream_yields_error_and_no_final_on_iserror_result():
    session = _fake_session(is_error=True, content=[SimpleNamespace(text="boom")], structured=None)

    async def _collect():
        events = []
        with patch("src.services.ai_agent_client.streamablehttp_client", return_value=_cm((None, None, None))), \
             patch("src.services.ai_agent_client.ClientSession", return_value=_cm(session)):
            async for event in ai_agent_client.ask_stream("http://127.0.0.1:9100/mcp", "q", [], []):
                events.append(event)
        return events

    events = asyncio.run(_collect())

    # isError is agent-authored - safe to show verbatim to whoever is
    # chatting, so it deliberately carries no "unplanned" key (see
    # chat_api's event_source, which branches on that key's presence).
    assert events[-1] == {"type": "error", "message": "boom"}
    assert "unplanned" not in events[-1]
    assert not any(event.get("type") == "final" for event in events)


def test_ask_stream_marks_generic_exception_as_unplanned():
    async def _collect():
        events = []
        # streamablehttp_client(url) is called synchronously (before the
        # `async with`), so a plain side_effect exception simulates a bare
        # connection/transport failure - distinct from an isError result,
        # which is raised from inside the (already-closed) connection
        # instead. See _call_tool's own comment for why isError is never
        # raised while the connection is still open.
        with patch("src.services.ai_agent_client.streamablehttp_client", side_effect=RuntimeError("connection reset")):
            async for event in ai_agent_client.ask_stream("http://127.0.0.1:9100/mcp", "q", [], []):
                events.append(event)
        return events

    events = asyncio.run(_collect())

    # A bare/transport failure (anything that isn't an explicit isError
    # result) is untrusted, unplanned text - marked so chat_api's
    # event_source knows to log it and show a generic safe message
    # instead of the raw text (see the isError-path test above, which
    # asserts the opposite: no "unplanned" key).
    assert events[-1] == {"type": "error", "message": "connection reset", "unplanned": True}
    assert not any(event.get("type") == "final" for event in events)


def _cm(value):
    """Wrap a value as an async context manager - streamablehttp_client()
    and ClientSession() are both entered with ``async with`` in the code
    under test."""

    class _ACM:
        async def __aenter__(self):
            return value

        async def __aexit__(self, *args):
            return False

    return _ACM()
