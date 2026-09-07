"""server.py tests: the ask/status/cancel tool contracts, with
agent_config mocked - FastMCP's @mcp.tool() decorator returns the
wrapped function unchanged, so these are called directly as plain
Python functions, no MCP transport involved.
"""

from __future__ import annotations

from unittest.mock import patch

from src import server
from src.llm.base import ChatCancelled, ChatResult, ToolCallRecord


def test_ask_returns_the_result_shape_chat_app_expects():
    fake_result = ChatResult(
        response="hi there",
        tools_used=["get_status_tool"],
        tool_calls=[ToolCallRecord(name="get_status_tool", arguments={}, result="ok")],
        provider_id="claude",
        model="claude-sonnet-5",
        total_tokens=42,
    )
    with patch("src.server.agent_config.run_chat", return_value=fake_result) as fake_run_chat:
        result = server.ask(
            "hello", history=[{"role": "user", "content": "prior"}], enabled_extensions=["reference"],
            request_id="req-1", depth=1,
        )

    fake_run_chat.assert_called_once_with("hello", [{"role": "user", "content": "prior"}], ["reference"], "req-1", 1)
    assert result == {
        "response": "hi there",
        "tools_used": ["get_status_tool"],
        "tool_calls": [{"name": "get_status_tool", "arguments": {}, "result": "ok"}],
        "total_tokens": 42,
        "provider_id": "claude",
        "model": "claude-sonnet-5",
        "cancelled": False,
    }


def test_ask_defaults_none_arguments_to_empty():
    with patch("src.server.agent_config.run_chat", return_value=ChatResult(response="hi")) as fake_run_chat:
        server.ask("hello")

    fake_run_chat.assert_called_once_with("hello", [], [], None, 0)


def test_ask_turns_chat_cancelled_into_a_clean_cancelled_result():
    with patch("src.server.agent_config.run_chat", side_effect=ChatCancelled()), \
         patch("src.server.agent_config.status", return_value={"model": "claude-sonnet-5"}):
        result = server.ask("hello", request_id="req-1")

    assert result["cancelled"] is True
    assert result["response"] == "⏹️ Cancelled."
    assert result["tools_used"] == []
    assert result["tool_calls"] == []
    assert result["provider_id"] == server.agent_config.PROVIDER_ID


def test_status_delegates_to_agent_config():
    fake_status = {"provider_id": "claude", "model": "claude-sonnet-5", "available": True, "reason": None, "cooldown_seconds_remaining": 0}
    with patch("src.server.agent_config.status", return_value=fake_status):
        assert server.status() == fake_status


def test_cancel_delegates_to_agent_config():
    with patch("src.server.agent_config.cancel", return_value=True) as fake_cancel:
        result = server.cancel("req-1")

    fake_cancel.assert_called_once_with("req-1")
    assert result == {"cancelled": True}
