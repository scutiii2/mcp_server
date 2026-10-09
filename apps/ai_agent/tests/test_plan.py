"""Checklists are validated, streamed, and isolated to one provider turn."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest

from src.agents import plan, agent_events
from src.llm import anthropic_provider, openai_provider, llm_options
from tests.test_anthropic_provider_streaming import _round_cm
from tests.test_openai_provider import _fake_stream


def test_plan_updates_emit_snapshots_without_leaking_between_turns():
    async def run():
        events = []
        async def emit(event):
            events.append(event)
        checklist = plan.Checklist()
        pending = [{"text": "Inspect", "status": "pending"}]
        assert (await checklist.handle("update_plan", {"items": pending}, emit))[1]
        assert checklist.items == pending
        done = [{"text": "Inspect", "status": "done"}]
        await checklist.handle("update_plan", {"items": done}, emit)
        assert events == [{"type": "plan_update", "items": pending}, {"type": "plan_update", "items": done}]
        assert plan.Checklist().items == []
        assert await checklist.handle("other", {}, emit) is None
    asyncio.run(run())


@pytest.mark.parametrize("items", [None, "bad", [{"text": "", "status": "done"}], [{"text": "x", "status": "unknown"}], [{"text": "x", "status": "in_progress"}, {"text": "y", "status": "in_progress"}], [{"text": "x", "status": "done"}] * 51])
def test_invalid_plan_does_not_replace_previous_items(items):
    async def run():
        checklist = plan.Checklist()
        await checklist.handle("update_plan", {"items": [{"text": "Keep", "status": "pending"}]}, None)
        _, ok = await checklist.handle("update_plan", {"items": items}, None)
        assert not ok
        assert checklist.items == [{"text": "Keep", "status": "pending"}]
    asyncio.run(run())


@pytest.mark.parametrize("provider,schema_key", [(anthropic_provider, "input_schema"), (openai_provider, "parameters")])
def test_both_providers_offer_plan(monkeypatch, provider, schema_key):
    monkeypatch.setattr(provider, "list_tools", lambda *_: [])
    schema = next(s for s in provider._tool_schemas() if s["name"] == "update_plan")
    assert schema[schema_key]["required"] == ["items"]
    assert schema[schema_key]["properties"]["items"]["items"]["properties"]["status"]["enum"] == ["pending", "in_progress", "done"]


def test_delegate_forwards_plan_with_its_identity():
    event = {"type": "plan_update", "agent_id": "calc", "items": [{"text": "Compute", "status": "pending"}]}
    assert agent_events.forwarded(event, "delegate-step") == event


@pytest.mark.parametrize("provider", [anthropic_provider, openai_provider])
def test_plan_runs_locally_in_both_provider_loops(monkeypatch, provider):
    llm_options.reset_cache()
    monkeypatch.setattr(provider.token_limits, "_config", None)
    monkeypatch.setattr(provider.agent_routing, "roster_for", AsyncMock(return_value=[]))
    monkeypatch.setattr(provider, "list_tools", lambda *_: [])
    monkeypatch.setattr(provider, "_dispatch", lambda *args: pytest.fail("plan reached external dispatch"))
    monkeypatch.setattr(provider.approvals, "review", AsyncMock(side_effect=AssertionError("plan asked for approval")))
    items = [{"text": "Inspect", "status": "in_progress"}]
    client = MagicMock()
    if provider is anthropic_provider:
        call = SimpleNamespace(type="tool_use", id="p1", name="update_plan", input={"items": items})
        one = SimpleNamespace(stop_reason="tool_use", content=[call], usage=SimpleNamespace(input_tokens=10, output_tokens=5))
        two = SimpleNamespace(stop_reason="end_turn", content=[], usage=SimpleNamespace(input_tokens=2, output_tokens=1))
        client.messages.stream.side_effect = [_round_cm([], one), _round_cm(["Done"], two)]
    else:
        call = SimpleNamespace(type="function_call", call_id="p1", name="update_plan", arguments=json.dumps({"items": items}), model_dump=lambda **kwargs: {})
        one = SimpleNamespace(output=[call], output_text="", usage=SimpleNamespace(total_tokens=15, input_tokens=10, output_tokens=5))
        two = SimpleNamespace(output=[], output_text="Done", usage=SimpleNamespace(total_tokens=3, input_tokens=2, output_tokens=1))
        client.responses.stream.side_effect = [_fake_stream([], one), _fake_stream(["Done"], two)]
    monkeypatch.setattr(provider, "_get_client", lambda: client)
    events = []
    async def emit(event):
        events.append(event)
    try:
        result = asyncio.run(provider.run_chat("go", [], on_event=emit))
        assert result.response == "Done"
        assert json.loads(result.tool_calls[0].result) == {"items": items}
        assert [event for event in events if event["type"] == "plan_update"] == [{"type": "plan_update", "items": items}]
    finally:
        llm_options.reset_cache()
