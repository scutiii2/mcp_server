"""anthropic_provider.py streaming tests: run_chat's on_event callback -
step_start/step_end pairs around each tool call, token events for the
streamed final answer. Written as plain sync `def test_x():` wrapping
`asyncio.run(...)` rather than `@pytest.mark.asyncio`, since
pytest-asyncio isn't in this project's test dependencies and adding it
mid-plan isn't worth it for one test file.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.llm import anthropic_provider


def _fake_async_iter(items):
    async def gen():
        for item in items:
            yield item
    return gen()


def _round_cm(chunks, final_message):
    """One `async with client.messages.stream(...)` round: streams `chunks`,
    then hands back `final_message` (carries stop_reason/content/usage)."""
    stream = MagicMock()
    stream.text_stream = _fake_async_iter(chunks)
    stream.get_final_message = AsyncMock(return_value=final_message)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=stream)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def test_run_chat_emits_step_events_around_a_tool_call(monkeypatch):
    async def _run():
        events = []

        async def on_event(event):
            events.append(event)

        # MagicMock's own `name=` kwarg sets the mock's repr, not a `.name`
        # attribute - set it after construction so block.name reads back
        # "tool_srv_listApps" the way a real Anthropic tool_use block would.
        tool_block = MagicMock(type="tool_use", input={"system_name": "s4e"}, id="t1")
        tool_block.name = "tool_srv_listApps"
        first_response = MagicMock(stop_reason="tool_use", content=[tool_block])
        first_response.usage.input_tokens = 10
        first_response.usage.output_tokens = 5

        second_response = MagicMock(stop_reason="end_turn", content=[])
        second_response.usage.input_tokens = 3
        second_response.usage.output_tokens = 1

        client = MagicMock()
        client.messages.stream = MagicMock(side_effect=[
            _round_cm([], first_response), _round_cm(["Hello", " world"], second_response),
        ])

        monkeypatch.setattr(anthropic_provider, "_get_client", lambda: client)
        monkeypatch.setattr(anthropic_provider, "_dispatch", lambda name, args, depth: "2 apps running")
        monkeypatch.setattr(anthropic_provider, "_tool_schemas", lambda enabled_extensions=None: [])

        result = await anthropic_provider.run_chat("status?", [], on_event=on_event)
        return result, events

    result, events = asyncio.run(_run())

    assert result.response == "Hello world"
    step_starts = [e for e in events if e["type"] == "step_start"]
    step_ends = [e for e in events if e["type"] == "step_end"]
    tokens = [e for e in events if e["type"] == "token"]
    assert step_starts and step_starts[0]["tool"] == "tool_srv_listApps"
    assert step_ends and step_ends[0]["ok"] is True
    assert [t["text"] for t in tokens] == ["Hello", " world"]


def test_run_chat_thread_display_label_from_tool_schemas_into_step_start(monkeypatch):
    async def _run():
        events = []

        async def on_event(event):
            events.append(event)

        tool_block = MagicMock(type="tool_use", input={}, id="t1")
        tool_block.name = "tool_srv_listApps"
        first_response = MagicMock(stop_reason="tool_use", content=[tool_block])
        first_response.usage.input_tokens = 1
        first_response.usage.output_tokens = 1

        second_response = MagicMock(stop_reason="end_turn", content=[])
        second_response.usage.input_tokens = 1
        second_response.usage.output_tokens = 1

        client = MagicMock()
        client.messages.stream = MagicMock(side_effect=[
            _round_cm([], first_response), _round_cm(["done"], second_response),
        ])

        monkeypatch.setattr(anthropic_provider, "_get_client", lambda: client)
        monkeypatch.setattr(anthropic_provider, "_dispatch", lambda name, args, depth: "ok")
        monkeypatch.setattr(
            anthropic_provider,
            "_tool_schemas",
            lambda enabled_extensions=None: [
                {
                    "name": "tool_srv_listApps",
                    "description": "d",
                    "input_schema": {},
                    "display_label": "List Apps",
                }
            ],
        )

        await anthropic_provider.run_chat("status?", [], on_event=on_event)
        return events

    events = asyncio.run(_run())

    step_starts = [e for e in events if e["type"] == "step_start"]
    assert step_starts[0]["label"] == "List Apps"


def test_run_chat_works_with_no_on_event_callback(monkeypatch):
    async def _run():
        response = MagicMock(stop_reason="end_turn", content=[])
        response.usage.input_tokens = 1
        response.usage.output_tokens = 1

        client = MagicMock()
        client.messages.stream = MagicMock(return_value=_round_cm(["ok"], response))

        monkeypatch.setattr(anthropic_provider, "_get_client", lambda: client)
        monkeypatch.setattr(anthropic_provider, "_tool_schemas", lambda enabled_extensions=None: [])

        return await anthropic_provider.run_chat("hi", [])

    result = asyncio.run(_run())
    assert result.response == "ok"


def test_run_chat_resets_streamed_text_from_a_tool_use_round(monkeypatch):
    async def _run():
        events = []

        async def on_event(event):
            events.append(event)

        tool_block = MagicMock(type="tool_use", input={}, id="t1")
        tool_block.name = "tool_srv_listApps"
        first = MagicMock(stop_reason="tool_use", content=[tool_block])
        first.usage.input_tokens = 1
        first.usage.output_tokens = 1
        second = MagicMock(stop_reason="end_turn", content=[])
        second.usage.input_tokens = 1
        second.usage.output_tokens = 1

        client = MagicMock()
        client.messages.stream = MagicMock(side_effect=[
            _round_cm(["Let me check."], first), _round_cm(["All good."], second),
        ])
        monkeypatch.setattr(anthropic_provider, "_get_client", lambda: client)
        monkeypatch.setattr(anthropic_provider, "_dispatch", lambda name, args, depth: "ok")
        monkeypatch.setattr(anthropic_provider, "_tool_schemas", lambda enabled_extensions=None: [])

        result = await anthropic_provider.run_chat("status?", [], on_event=on_event)
        return result, events

    result, events = asyncio.run(_run())

    assert result.response == "All good."
    types = [e["type"] for e in events]
    assert types.index("token_reset") < types.index("step_start")
    assert [e["text"] for e in events if e["type"] == "token"] == ["Let me check.", "All good."]
