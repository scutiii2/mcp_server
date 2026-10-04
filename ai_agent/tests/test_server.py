"""server.py tests: the ask/status/cancel tool contracts, with
agent_config mocked - FastMCP's @mcp.tool() decorator returns the
wrapped function unchanged, so these are called directly as plain
Python functions, no MCP transport involved. ask is now async,
so tests wrap the call in asyncio.run().
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import ANY, AsyncMock, MagicMock, patch

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
            input_tokens=30,
            output_tokens=12,
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
            "agent_usage": ANY,
            "input_tokens": 30,
            "output_tokens": 12,
            "context_tokens": 30,
            "context_window": 200_000,
            "provider_id": "anthropic",
            "model": "claude-sonnet-5",
            "cancelled": False,
        }
        own = result["agent_usage"][0]
        assert own["agent_id"] == server._AGENT_ID
        assert own["agent_label"] == server._AGENT_LABEL
        assert (own["provider_id"], own["model"], own["input_tokens"], own["output_tokens"], own["total_tokens"]) == (
            "anthropic", "claude-sonnet-5", 30, 12, 42,
        )
        assert own["delegated_by"] is None
        assert own["started_at"] <= own["finished_at"]

    asyncio.run(_run())


def test_ask_records_delegated_by_and_appends_to_the_usage_log():
    async def _run():
        with patch("src.server.agent_config.run_chat", new_callable=AsyncMock, return_value=ChatResult(response="hi")),              patch("src.server.agent_config.status", return_value={"model": "m", "context_window": 1}),              patch("src.server.usage_log.append", new_callable=AsyncMock) as append:
            result = await server.ask("q", request_id="r-1", depth=1, delegated_by="orchestrator")

        assert result["agent_usage"][0]["delegated_by"] == "orchestrator"
        row = append.await_args.args[0]
        assert row["request_id"] == "r-1" and row["depth"] == 1 and row["delegated_by"] == "orchestrator"

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
        async def fake_run_chat(question, history, enabled_extensions, request_id, depth, on_event=None, caveman=False, approval_mode="off", allowed_tools=None):
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
        assert json.loads(message) == {
            "type": "step_start", "id": "1", "tool": "x",
            "agent_id": server._AGENT_ID, "agent_label": server._AGENT_LABEL,
        }

    asyncio.run(_run())


def test_ask_on_event_is_a_noop_without_ctx():
    """When no ctx is supplied (e.g. a direct call/test, or an MCP
    client that doesn't support progress), on_event must not blow up -
    it should just do nothing."""
    async def _run():
        async def fake_run_chat(question, history, enabled_extensions, request_id, depth, on_event=None, caveman=False, approval_mode="off", allowed_tools=None):
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
        assert server.status() == {**fake_status, "tool_approval": True}


def test_cancel_delegates_to_agent_config():
    with patch("src.server.agent_config.cancel", return_value=True) as fake_cancel:
        result = server.cancel("req-1")

    fake_cancel.assert_called_once_with("req-1")
    assert result == {"cancelled": True}


def test_role_flag_sets_env_var(monkeypatch):
    monkeypatch.delenv("AI_AGENT_ROLE", raising=False)

    args, _ = server._parser.parse_known_args(["--role", "ops_specialist"])

    assert args.role == "ops_specialist"


def test_server_uses_the_env_spec_identity_without_an_agent_file():
    # conftest sets AI_AGENT_PROVIDER=anthropic and no AI_AGENT_FILE.
    assert server.SPEC.source is None
    assert server._AGENT_ID == "claude-agent"
    assert server._AGENT_LABEL.endswith(" Agent")


def test_main_registers_with_the_spec_flags(monkeypatch):
    calls = {}
    monkeypatch.setattr(server.mcp_upstream, "connect", lambda: None)
    monkeypatch.setattr(server.mcp_upstream, "warn_unmatched_tool_globs", lambda: None)
    monkeypatch.setattr(server.mcp_upstream, "close", lambda: None)
    monkeypatch.setattr(server.agent_registry, "register", lambda *a, **k: calls.setdefault("register", (a, k)))
    monkeypatch.setattr(server.agent_registry, "deregister", lambda agent_id: calls.setdefault("deregister", agent_id))
    monkeypatch.setattr(server.uvicorn, "run", lambda *a, **k: None)

    server.main()

    args, kwargs = calls["register"]
    assert args[0] == server._AGENT_ID
    assert kwargs == {"entry": server.SPEC.entry, "orchestrator": server.SPEC.orchestrator, "focus": server.SPEC.focus}
    assert calls["deregister"] == server._AGENT_ID
