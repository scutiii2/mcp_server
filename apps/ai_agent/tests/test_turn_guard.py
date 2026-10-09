"""Turn guards prevent further billed rounds and repeated tool execution."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agents import agent_spec
from src.llm import anthropic_provider, openai_provider, llm_options
from tests.test_anthropic_provider_streaming import _round_cm
from tests.test_openai_provider import _fake_stream


@pytest.mark.parametrize("provider", [anthropic_provider, openai_provider])
@pytest.mark.parametrize("reason", ["tokens", "repeat", "time"])
def test_provider_stops_before_executing_more_tools(monkeypatch, provider, reason):
    llm_options.reset_cache()
    monkeypatch.setattr(provider.token_limits, "_config", None)
    original = agent_spec.current()
    from dataclasses import replace
    limits = {"max_turn_tokens": 15} if reason == "tokens" else {"max_turn_seconds": 0.01} if reason == "time" else {}
    monkeypatch.setattr(agent_spec, "current", lambda: replace(original, llm=agent_spec.LlmSpec(provider=provider.PROVIDER_ID, **limits)))
    monkeypatch.setattr(provider.agent_routing, "roster_for", AsyncMock(return_value=[]))
    monkeypatch.setattr(provider, "_tool_schemas", lambda *args: [])
    executed = []
    monkeypatch.setattr(provider, "_dispatch", lambda name, args, depth: executed.append(args) or "ok")
    client = MagicMock()
    rounds = []
    for index in range(4):
        arguments = {"b": 2, "a": 1} if index % 2 else {"a": 1, "b": 2}
        if provider is anthropic_provider:
            call = SimpleNamespace(type="tool_use", id=str(index), name="read", input=arguments)
            response = SimpleNamespace(stop_reason="tool_use", content=[call], usage=SimpleNamespace(input_tokens=10, output_tokens=5))
            rounds.append(_round_cm([], response))
        else:
            call = SimpleNamespace(type="function_call", call_id=str(index), name="read", arguments=json.dumps(arguments), model_dump=lambda **kwargs: {})
            response = SimpleNamespace(output=[call], output_text="", usage=SimpleNamespace(total_tokens=15, input_tokens=10, output_tokens=5))
            rounds.append(_fake_stream([], response))
    stream = client.messages.stream if provider is anthropic_provider else client.responses.stream
    stream.side_effect = rounds
    if reason == "time":
        async def slow_enter():
            await asyncio.sleep(1)
        rounds[0].__aenter__.side_effect = slow_enter
    monkeypatch.setattr(provider, "_get_client", lambda: client)
    events = []
    async def emit(event):
        events.append(event)
    if reason == "time":
        from src.llm import cancellation
        cancellation.link("budgeted-turn", "budgeted-child")
    try:
        result = asyncio.run(provider.run_chat("go", [], request_id="budgeted-turn", on_event=emit))
        assert len(executed) == (2 if reason == "repeat" else 0)
        assert {"tokens": "token budget", "repeat": "repeated", "time": "time budget"}[reason] in result.response.lower()
        assert events[-1] == {"type": "token", "text": result.response}
        if reason == "time":
            assert cancellation.is_cancelled("budgeted-child")
    finally:
        llm_options.reset_cache()
        from src.llm import cancellation
        cancellation.clear("budgeted-child")
        cancellation.clear("budgeted-turn")


def test_agent_accepts_turn_caps(tmp_path):
    path = tmp_path / "bounded.json"
    path.write_text(json.dumps({"port": 9103, "llm": {"provider": "openai", "max_turn_tokens": 1000, "max_turn_seconds": 2.5}}))
    spec = agent_spec.load_file(path)
    assert spec.llm.max_turn_tokens == 1000
    assert spec.llm.max_turn_seconds == 2.5


@pytest.mark.parametrize("key,value", [("max_turn_tokens", 0), ("max_turn_tokens", True), ("max_turn_tokens", 1.5), ("max_turn_seconds", 0), ("max_turn_seconds", True), ("max_turn_seconds", float("inf"))])
def test_agent_rejects_invalid_turn_caps(tmp_path, key, value):
    path = tmp_path / "bounded.json"
    path.write_text(json.dumps({"port": 9103, "llm": {"provider": "openai", key: value}}))
    with pytest.raises(agent_spec.AgentSpecError, match=key):
        agent_spec.load_file(path)
