"""delegation.py tests: availability/description built from the
configured agent registry, the depth cap, unknown-agent handling, and
the isError -> plain-exception translation - mirroring
chat_app/tests/test_ai_agent_client.py's convention (asyncio.run() in a
plain test function, no pytest-asyncio plugin needed).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src import agent_registry, delegation


def _configure_agents(monkeypatch, agents):
    monkeypatch.setattr(agent_registry, "_AGENTS", agents)
    monkeypatch.setattr(agent_registry, "_AGENTS_BY_ID", {a["id"]: a for a in agents})


def test_is_available_false_with_no_configured_agents(monkeypatch):
    _configure_agents(monkeypatch, [])
    assert delegation.is_available() is False


def test_is_available_true_with_configured_agents(monkeypatch):
    _configure_agents(monkeypatch, [{"id": "claude-agent", "label": "Claude Agent", "url": "http://x/mcp"}])
    assert delegation.is_available() is True


def test_tool_description_lists_configured_agent_ids_and_labels(monkeypatch):
    _configure_agents(
        monkeypatch,
        [
            {"id": "claude-agent", "label": "Claude Agent", "url": "http://x/mcp"},
            {"id": "openai-agent", "label": "OpenAI Agent", "url": "http://y/mcp"},
        ],
    )
    description = delegation.tool_description()
    assert "claude-agent (Claude Agent)" in description
    assert "openai-agent (OpenAI Agent)" in description


def test_call_raises_at_the_depth_cap_without_any_network_call(monkeypatch):
    _configure_agents(monkeypatch, [{"id": "claude-agent", "label": "Claude Agent", "url": "http://x/mcp"}])

    with patch("src.delegation._call_tool") as fake_call_tool:
        try:
            delegation.call("claude-agent", "hi", depth=delegation._MAX_DELEGATION_DEPTH)
            raise AssertionError("expected ValueError")
        except ValueError as error:
            assert "max delegation depth" in str(error)

    fake_call_tool.assert_not_called()


def test_call_raises_for_an_unknown_agent_id(monkeypatch):
    _configure_agents(monkeypatch, [{"id": "claude-agent", "label": "Claude Agent", "url": "http://x/mcp"}])

    try:
        delegation.call("nope", "hi", depth=0)
        raise AssertionError("expected ValueError")
    except ValueError as error:
        assert "unknown agent_id 'nope'" in str(error)


def test_call_returns_the_sub_agents_response_on_success(monkeypatch):
    _configure_agents(monkeypatch, [{"id": "openai-agent", "label": "OpenAI Agent", "url": "http://127.0.0.1:9101/mcp"}])

    captured = {}

    async def _fake_call_tool(url, name, arguments):
        captured["url"] = url
        captured["name"] = name
        captured["arguments"] = arguments
        return {"response": "the answer", "cancelled": False}

    with patch("src.delegation._call_tool", side_effect=_fake_call_tool):
        result = delegation.call("openai-agent", "sub-question", depth=0)

    assert result == "the answer"
    assert captured["url"] == "http://127.0.0.1:9101/mcp"
    assert captured["name"] == "ask"
    assert captured["arguments"] == {
        "question": "sub-question",
        "history": [],
        "enabled_extensions": [],
        "request_id": None,
        "depth": 1,
    }


def _fake_session(*, is_error: bool, content: list, structured: dict | None):
    session = AsyncMock()
    session.initialize = AsyncMock(return_value=None)
    session.call_tool = AsyncMock(
        return_value=SimpleNamespace(isError=is_error, content=content, structuredContent=structured)
    )
    return session


def _cm(value):
    class _ACM:
        async def __aenter__(self):
            return value

        async def __aexit__(self, *args):
            return False

    return _ACM()


def test_call_tool_raises_plain_exception_on_iserror_result():
    session = _fake_session(is_error=True, content=[SimpleNamespace(text="openai is rate-limited")], structured=None)

    with patch("src.delegation.streamablehttp_client", return_value=_cm((None, None, None))), \
         patch("src.delegation.ClientSession", return_value=_cm(session)):
        try:
            asyncio.run(delegation._call_tool("http://127.0.0.1:9101/mcp", "ask", {}))
            raise AssertionError("expected RuntimeError")
        except RuntimeError as error:
            assert "rate-limited" in str(error)
