"""server.py tests: the ask/status/cancel tool contracts, with
agent_config mocked - FastMCP's @mcp.tool() decorator returns the
wrapped function unchanged, so these are called directly as plain
Python functions, no MCP transport involved. ask is now async,
so tests wrap the call in asyncio.run().
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from src import server
from src.llm.base_provider import ChatCancelled, ChatResult, ToolCallRecord


def test_ask_returns_the_result_shape_chat_app_expects():
    """ask is now async and forwards the ChatResult from run_chat."""
    async def _run():
        fake_result = ChatResult(
            response="hi there",
            tools_used=["get_status_tool"],
            tool_calls=[ToolCallRecord(name="get_status_tool", arguments={}, result="ok")],
            provider_id="anthropic",
            model="claude-sonnet-5",
            total_tokens=42,
            context_tokens=30,
        )
        fake_status = {"model": "claude-sonnet-5", "context_window": 200_000}
        with patch("src.server.agent_config.run_chat", new_callable=AsyncMock, return_value=fake_result) as fake_run_chat, \
             patch("src.server.agent_config.status", return_value=fake_status):
            result = await server.ask(
                "hello", history=[{"role": "user", "content": "prior"}], enabled_extensions=["reference"],
                request_id="req-1", depth=1,
            )

        # on_event is ask()'s own closure (built fresh each call, so it
        # can't be compared by equality) - check the positional args and
        # that an on_event callable was passed, separately.
        fake_run_chat.assert_awaited_once()
        call_args, call_kwargs = fake_run_chat.call_args
        assert call_args == ("hello", [{"role": "user", "content": "prior"}], ["reference"], "req-1", 1)
        assert callable(call_kwargs["on_event"])
        assert result == {
            "response": "hi there",
            "tools_used": ["get_status_tool"],
            "tool_calls": [{"name": "get_status_tool", "arguments": {}, "result": "ok"}],
            "total_tokens": 42,
            "context_tokens": 30,
            "context_window": 200_000,
            "provider_id": "anthropic",
            "model": "claude-sonnet-5",
            "cancelled": False,
        }

    asyncio.run(_run())


def test_ask_defaults_none_arguments_to_empty():
    """ask should default None history/extensions to empty lists."""
    async def _run():
        with patch("src.server.agent_config.run_chat", new_callable=AsyncMock, return_value=ChatResult(response="hi")) as fake_run_chat, \
             patch("src.server.agent_config.status", return_value={"model": "claude-sonnet-5", "context_window": 200_000}):
            await server.ask("hello")

        fake_run_chat.assert_awaited_once()
        call_args, call_kwargs = fake_run_chat.call_args
        assert call_args == ("hello", [], [], None, 0)
        assert callable(call_kwargs["on_event"])

    asyncio.run(_run())


def test_ask_turns_chat_cancelled_into_a_clean_cancelled_result():
    """ask should catch ChatCancelled and return a clean cancelled result."""
    async def _run():
        async def _raise_cancelled(*args, **kwargs):
            raise ChatCancelled()

        with patch("src.server.agent_config.run_chat", new_callable=AsyncMock, side_effect=_raise_cancelled), \
             patch("src.server.agent_config.status", return_value={"model": "claude-sonnet-5", "context_window": 200_000}):
            result = await server.ask("hello", request_id="req-1")

        assert result["cancelled"] is True
        assert result["response"] == "⏹️ Cancelled."
        assert result["tools_used"] == []
        assert result["tool_calls"] == []
        assert result["provider_id"] == server.agent_config.PROVIDER_ID

    asyncio.run(_run())


def test_ask_relays_events_via_ctx_report_progress():
    """ask should build an on_event closure that forwards each event dict
    to ctx.report_progress as a JSON string (progress/total left as
    0/None - chat_app cares only about the message payload, not a
    percentage), and pass it through to run_chat as on_event=..."""
    async def _run():
        async def fake_run_chat(question, history, enabled_extensions, request_id, depth, on_event=None):
            await on_event({"type": "step_start", "id": "1", "tool": "x"})
            return ChatResult(response="done")

        ctx = MagicMock()
        ctx.report_progress = AsyncMock()

        with patch("src.server.agent_config.run_chat", new=fake_run_chat), \
             patch("src.server.agent_config.status", return_value={"model": "claude-sonnet-5", "context_window": 200_000}):
            result = await server.ask("q", ctx=ctx)

        assert result["response"] == "done"
        ctx.report_progress.assert_awaited_once()
        _, _, message = ctx.report_progress.call_args.args
        assert json.loads(message) == {"type": "step_start", "id": "1", "tool": "x"}

    asyncio.run(_run())


def test_ask_on_event_is_a_noop_without_ctx():
    """When no ctx is supplied (e.g. a direct call/test, or an MCP
    client that doesn't support progress), on_event must not blow up -
    it should just do nothing."""
    async def _run():
        async def fake_run_chat(question, history, enabled_extensions, request_id, depth, on_event=None):
            await on_event({"type": "step_start", "id": "1", "tool": "x"})
            return ChatResult(response="done")

        with patch("src.server.agent_config.run_chat", new=fake_run_chat), \
             patch("src.server.agent_config.status", return_value={"model": "claude-sonnet-5", "context_window": 200_000}):
            result = await server.ask("q")

        assert result["response"] == "done"

    asyncio.run(_run())


def test_status_delegates_to_agent_config():
    fake_status = {"provider_id": "anthropic", "model": "claude-sonnet-5", "available": True, "reason": None, "cooldown_seconds_remaining": 0}
    with patch("src.server.agent_config.status", return_value=fake_status):
        assert server.status() == fake_status


def test_cancel_delegates_to_agent_config():
    with patch("src.server.agent_config.cancel", return_value=True) as fake_cancel:
        result = server.cancel("req-1")

    fake_cancel.assert_called_once_with("req-1")
    assert result == {"cancelled": True}


def test_role_flag_sets_env_var(monkeypatch):
    monkeypatch.delenv("AI_AGENT_ROLE", raising=False)

    args, _ = server._parser.parse_known_args(["--role", "ops_specialist"])

    assert args.role == "ops_specialist"
