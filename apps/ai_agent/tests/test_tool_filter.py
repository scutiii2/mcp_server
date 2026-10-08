"""core/tool_filter.py: tools one user switched off for their own chats - the
context variable, how list_tools()/call_tool() honour it, how ask() and
run_chat() bind it for one turn, and that a delegate is told too."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src import server
from src.agents import agent_config, delegation
from src.core import tool_filter
from src.llm.base_provider import ChatResult
from src.mcp_client import mcp_upstream


def _tool(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=f"main__{name}", description="", meta=None)


def test_nothing_is_blocked_by_default():
    assert tool_filter.blocked() == frozenset()
    assert not tool_filter.is_blocked("tool_pdf_merge")


def test_bind_blocks_until_reset():
    token = tool_filter.bind(["a", "b", "a"])
    try:
        assert tool_filter.blocked() == {"a", "b"}
        assert tool_filter.is_blocked("a")
        assert not tool_filter.is_blocked("c")
    finally:
        tool_filter.reset(token)
    assert tool_filter.blocked() == frozenset()


def test_list_tools_leaves_out_the_blocked_ones_and_keeps_the_rest():
    tools = [_tool("tool_pdf_merge"), _tool("tool_pdf_split"), _tool("tool_calc")]
    with patch.object(mcp_upstream.client, "list_tools", return_value=tools):
        token = tool_filter.bind(["tool_pdf_merge", "tool_pdf_split"])
        try:
            names = [mcp_upstream.unprefixed(t.name) for t in mcp_upstream.list_tools()]
        finally:
            tool_filter.reset(token)
        assert names == ["tool_calc"]
        # Back to normal once the turn is over.
        assert len(mcp_upstream.list_tools()) == 3


def test_call_tool_refuses_a_blocked_tool_the_model_names_anyway():
    token = tool_filter.bind(["tool_pdf_merge"])
    try:
        with patch.object(mcp_upstream.client, "call_tool") as call:
            with pytest.raises(PermissionError, match="switched off"):
                mcp_upstream.call_tool("main__tool_pdf_merge", {})
            call.assert_not_called()
    finally:
        tool_filter.reset(token)


def test_ask_hands_disabled_tools_to_run_chat():
    captured = {}

    async def fake_run_chat(question, history, enabled_extensions, request_id, depth, on_event=None, caveman=False,
                            approval_mode="off", allowed_tools=None, disabled_tools=None, ask_user=False):
        captured["disabled"] = disabled_tools
        return ChatResult(response="done")

    async def _run():
        with patch("src.server.agent_config.run_chat", new=fake_run_chat), \
             patch("src.server.agent_config.status", return_value={"model": "m", "context_window": 1}):
            await server.ask("q", disabled_tools=["tool_pdf_merge"])

    asyncio.run(_run())
    assert captured["disabled"] == ["tool_pdf_merge"]


def test_run_chat_blocks_for_the_turn_and_lets_go_afterwards():
    seen = {}

    async def fake_provider_run_chat(question, history, model, enabled_extensions, request_id, depth, on_event=None, caveman=False):
        seen["during"] = tool_filter.blocked()
        return ChatResult(response="ok")

    async def _run():
        provider = SimpleNamespace(run_chat=fake_provider_run_chat)
        with patch.object(agent_config, "_PROVIDER_MODULE", provider):
            await agent_config.run_chat("q", [], [], disabled_tools=["tool_pdf_merge"])

    asyncio.run(_run())
    assert seen["during"] == {"tool_pdf_merge"}
    assert tool_filter.blocked() == frozenset()


def test_a_delegate_is_told_what_the_user_switched_off():
    captured = {}

    async def _fake_call_tool(url, name, arguments, **kwargs):
        captured["arguments"] = arguments
        return {"response": "the answer"}

    token = tool_filter.bind(["tool_pdf_merge", "tool_calc"])
    try:
        with patch("src.agents.delegation._call_tool", side_effect=_fake_call_tool), \
             patch("src.agents.delegation.agent_registry") as registry:
            registry.get_agent.return_value = {"url": "http://127.0.0.1:9101/mcp", "label": "Sub"}
            delegation.call("openai-agent", "sub-question", depth=0)
    finally:
        tool_filter.reset(token)

    assert captured["arguments"]["disabled_tools"] == ["tool_calc", "tool_pdf_merge"]


def test_wildcard_blocks_builtin_shared_and_private_tools():
    token = tool_filter.bind(["*"])
    try:
        for name in ("tool_pdf_merge", "notes__search", "u_notes__search"):
            assert tool_filter.is_blocked(name)
            with pytest.raises(PermissionError, match="switched off"):
                mcp_upstream.call_tool(name if name.startswith("u_") else f"main__{name}", {})
        with patch.object(mcp_upstream.client, "list_tools", return_value=[_tool("tool_pdf_merge")]):
            assert mcp_upstream.list_tools() == []
    finally:
        tool_filter.reset(token)


def test_wildcard_refuses_a_delegate_without_block_all_support():
    seen = []

    async def fake_call(url, name, arguments, **kwargs):
        seen.append(name)
        return {"tool_filter": True}

    token = tool_filter.bind(["*"])
    try:
        with patch("src.agents.delegation._call_tool", side_effect=fake_call), \
             patch("src.agents.delegation.agent_registry") as registry:
            registry.get_agent.return_value = {"url": "http://127.0.0.1:9101/mcp", "label": "Sub"}
            with pytest.raises(PermissionError, match="block all tools"):
                delegation.call("openai-agent", "sub-question", depth=0)
    finally:
        tool_filter.reset(token)
    assert seen == ["status"]
