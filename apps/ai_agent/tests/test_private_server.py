"""ask(), run_chat, status() and probe_extension with private extensions."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from mcp import types

from src import server
from src.agents import agent_config, delegation
from src.core import approvals, internal_auth
from src.llm.base_provider import ChatResult
from src.private_extensions import turn as private_turn

RAW = [{"id": "notes", "label": "Notes", "url": "https://notes.example.com/mcp", "headers": {"X-Key": "s3cret"}}]


def run(coro):
    return asyncio.run(coro)


def test_ask_passes_private_extensions_only_when_given():
    seen = []

    async def fake_run_chat(question, history, enabled_extensions, request_id, depth, on_event=None, caveman=False,
                            approval_mode="off", allowed_tools=None, disabled_tools=None, **more):
        seen.append({k: v for k, v in more.items() if k == "private_extensions"})
        return ChatResult(response="done")

    async def go():
        with patch("src.server.agent_config.run_chat", new=fake_run_chat), \
             patch("src.server.agent_config.status", return_value={"model": "m", "context_window": 1}):
            await server.ask("q")
            await server.ask("q", private_extensions=RAW)

    run(go())
    assert seen == [{}, {"private_extensions": RAW}]


def test_the_reply_carries_private_extension_errors_only_when_there_are_some():
    async def go(errors):
        async def fake_run_chat(*args, **kwargs):
            return ChatResult(response="done", private_extension_errors=errors)

        with patch("src.server.agent_config.run_chat", new=fake_run_chat), \
             patch("src.server.agent_config.status", return_value={"model": "m", "context_window": 1}):
            return await server.ask("q")

    assert "private_extension_errors" not in run(go([]))
    errors = [{"id": "notes", "label": "Notes", "error": "Timed out"}]
    assert run(go(errors))["private_extension_errors"] == errors


def test_status_reports_private_extension_support():
    fake = {"provider_id": "anthropic", "model": "m", "available": True, "reason": None, "cooldown_seconds_remaining": 0}
    with patch("src.server.agent_config.status", return_value=fake), patch.object(agent_config, "PROVIDER_ID", "anthropic"):
        assert server.status()["private_extensions"] is True
    with patch("src.server.agent_config.status", return_value=fake), patch.object(agent_config, "PROVIDER_ID", "laya"):
        assert server.status()["private_extensions"] is False


def run_with_provider(raw, *, account="a@x", prefetch=None, approval_mode="off"):
    seen = {}

    async def fake_provider(question, history, model, enabled_extensions, request_id, depth, on_event=None, caveman=False):
        seen["turn"] = private_turn.current()
        seen["prefixes"] = approvals.current().ask_prefixes
        seen["mode"] = approvals.current().mode
        return ChatResult(response="ok")

    async def fake_prefetch(turn):
        seen["prefetched"] = sorted(turn.specs)
        if prefetch:
            prefetch(turn)

    async def go():
        token = internal_auth.bind_requester(internal_auth.Requester(email=account))
        try:
            with patch.object(agent_config, "_PROVIDER_MODULE", SimpleNamespace(run_chat=fake_provider)), \
                 patch("src.mcp_client.mcp_upstream.prefetch_private", new=fake_prefetch):
                return await agent_config.run_chat("q", [], [], approval_mode=approval_mode, private_extensions=raw)
        finally:
            internal_auth.reset_requester(token)

    result = run(go())
    return result, seen


def test_run_chat_binds_the_turn_prefetches_and_makes_private_tools_ask():
    result, seen = run_with_provider(RAW)

    assert seen["prefetched"] == ["notes"]
    assert seen["turn"].account == "a@x"
    assert seen["prefixes"] == ("u_",)
    assert seen["mode"] == "off"
    assert result.private_extension_errors == []
    assert private_turn.current() is None
    assert approvals.current().ask_prefixes == ()


def test_run_chat_without_private_extensions_is_unchanged():
    result, seen = run_with_provider(None)

    assert "prefetched" not in seen
    assert seen["turn"] is not None
    assert not seen["turn"]
    assert seen["turn"].specs == {}
    assert seen["turn"].tools() == []
    assert seen["prefixes"] == ()


def test_run_chat_hands_back_what_could_not_connect():
    def fail(turn):
        turn.errors.append({"id": "notes", "label": "Notes", "error": "Timed out"})

    result, _seen = run_with_provider(RAW, prefetch=fail)

    assert result.private_extension_errors == [{"id": "notes", "label": "Notes", "error": "Timed out"}]


def test_run_chat_without_an_account_drops_the_extensions_with_an_error():
    result, seen = run_with_provider(RAW, account="")

    assert "prefetched" not in seen
    assert [e["id"] for e in result.private_extension_errors] == ["notes"]
    assert seen["prefixes"] == ()


def test_a_delegate_is_never_given_private_extensions():
    captured = {}

    async def fake_call_tool(url, name, arguments, **kwargs):
        captured["arguments"] = arguments
        return {"response": "the answer"}

    turn = private_turn.PrivateTurn.from_raw(RAW, "a@x")
    token = private_turn.bind(turn)
    try:
        with patch("src.agents.delegation._call_tool", side_effect=fake_call_tool), \
             patch("src.agents.delegation.agent_registry") as registry:
            registry.get_agent.return_value = {"url": "http://127.0.0.1:9101/mcp", "label": "Sub"}
            delegation.call("openai-agent", "sub-question", depth=0)
    finally:
        private_turn.reset(token)

    assert "private_extensions" not in captured["arguments"]


def test_probe_extension_returns_what_mcp_upstream_found():
    answer = {"status": "connected", "error": None, "tools": ["add", "search"]}
    received = []

    async def fake_probe(url, headers):
        received.append((url, headers))
        return answer

    with patch("src.server.mcp_upstream.probe_private", new=fake_probe):
        assert run(server.probe_extension("https://notes.example.com/mcp", {"X-Key": "s3cret"})) == answer
        assert run(server.probe_extension("https://notes.example.com/mcp")) == answer

    assert received == [
        ("https://notes.example.com/mcp", {"X-Key": "s3cret"}),
        ("https://notes.example.com/mcp", None),
    ]
