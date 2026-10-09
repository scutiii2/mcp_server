"""Stop reaches linked delegates, including peers in another process."""

import asyncio
import json
import threading
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agents import agent_registry, delegation
from src.llm import cancellation
from src.llm import anthropic_provider, openai_provider, llm_options
from src.agents import agent_spec
from tests.test_anthropic_provider_streaming import _round_cm
from tests.test_openai_provider import _fake_stream


def test_linked_descendants_inherit_early_and_late_cancellation():
    cancellation.cancel("parent")
    try:
        cancellation.link("parent", "child")
        cancellation.link("child", "grandchild")
        assert cancellation.is_cancelled("child")
        assert cancellation.is_cancelled("grandchild")
        cancellation.clear("child")
        assert not cancellation.is_cancelled("child")
        cancellation.link("other", "fresh")
        cancellation.cancel("other")
        assert cancellation.is_cancelled("fresh")
        assert not cancellation.is_cancelled("unrelated")
    finally:
        for request in ("parent", "child", "grandchild", "other", "fresh"):
            cancellation.clear(request)


def test_delegate_sends_child_id_and_remote_cancel(monkeypatch):
    peer = {"id": "peer", "url": "http://peer/mcp"}
    monkeypatch.setattr(agent_registry, "reload", lambda: None)
    monkeypatch.setattr(agent_registry, "get_agent", lambda _: peer)
    received = []
    async def remote(url, name, arguments, on_progress=None):
        received.append((name, arguments))
        if name == "ask":
            cancellation.cancel("parent")
            while not any(name == "cancel" for name, _ in received):
                await asyncio.sleep(0.01)
            return {"response": "Stopped", "cancelled": True}
        return {"cancelled": True}
    monkeypatch.setattr(delegation, "_call_tool", remote)
    token = cancellation.bind_request("parent")
    try:
        assert delegation.call("peer", "work", 0) == "Stopped"
        child = received[0][1]["request_id"]
        assert child and child != "parent"
        assert received[1] == ("cancel", {"request_id": child})
        assert not cancellation.is_cancelled(child)
    finally:
        cancellation.reset_request(token)
        cancellation.clear("parent")


@pytest.mark.parametrize("provider", [anthropic_provider, openai_provider])
@pytest.mark.parametrize("late_start", [False, True])
def test_deadline_during_delegation_cancels_the_remote_peer(monkeypatch, provider, late_start):
    llm_options.reset_cache()
    original = agent_spec.current()
    monkeypatch.setattr(agent_spec, "current", lambda: replace(original, llm=agent_spec.LlmSpec(provider=provider.PROVIDER_ID, max_turn_seconds=0.2)))
    monkeypatch.setattr(provider.token_limits, "_config", None)
    monkeypatch.setattr(provider.agent_routing, "roster_for", AsyncMock(return_value=[]))
    monkeypatch.setattr(provider, "_tool_schemas", lambda *args: [])
    release_start = threading.Event()
    monkeypatch.setattr(agent_registry, "reload", lambda: release_start.wait(1) if late_start else None)
    monkeypatch.setattr(agent_registry, "get_agent", lambda _: {"id": "peer", "url": "http://peer/mcp"})
    arguments = {"agent_id": "peer", "question": "work"}
    if provider is anthropic_provider:
        call = SimpleNamespace(type="tool_use", name="delegate_to_agent", id="d", input=arguments)
        response = SimpleNamespace(stop_reason="tool_use", content=[call], usage=SimpleNamespace(input_tokens=10, output_tokens=5))
        cm = _round_cm([], response)
        client = SimpleNamespace(messages=SimpleNamespace(stream=lambda **kwargs: cm))
    else:
        call = SimpleNamespace(type="function_call", name="delegate_to_agent", call_id="d", arguments=json.dumps(arguments), model_dump=lambda **kwargs: {})
        response = SimpleNamespace(output=[call], output_text="", usage=SimpleNamespace(total_tokens=15, input_tokens=10, output_tokens=5))
        cm = _fake_stream([], response)
        client = SimpleNamespace(responses=SimpleNamespace(stream=lambda **kwargs: cm))
    monkeypatch.setattr(provider, "_get_client", lambda: client)
    remote_cancel = threading.Event()
    finished = threading.Event()
    async def remote(url, name, arguments, on_progress=None):
        if name == "cancel":
            remote_cancel.set()
            return {"cancelled": True}
        try:
            for _ in range(150):
                if remote_cancel.is_set():
                    return {"response": "Stopped"}
                await asyncio.sleep(0.01)
            return {"response": "Peer kept running"}
        finally:
            finished.set()
    monkeypatch.setattr(delegation, "_call_tool", remote)
    token = cancellation.bind_request("deadline-parent")
    async def run():
        result = await provider.run_chat("go", [], request_id="deadline-parent")
        cancellation.clear("deadline-parent")
        release_start.set()
        for _ in range(200):
            if finished.is_set():
                break
            await asyncio.sleep(0.01)
        assert "time budget" in result.response
        assert remote_cancel.is_set()
    try:
        asyncio.run(run())
    finally:
        cancellation.reset_request(token)
        cancellation.clear("deadline-parent")
        llm_options.reset_cache()
