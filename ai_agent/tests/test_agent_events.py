"""agent_events.py tests: stamping keeps the innermost agent, specialist
events are translated for the orchestrator's stream, and the sink bound by
dispatch_with_progress carries them back to on_event in order."""

from __future__ import annotations

import asyncio
import re

from src.agents import agent_events
from src.llm.base_provider import dispatch_with_progress


def test_now_iso_is_utc_with_milliseconds():
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", agent_events.now_iso())


def test_stamp_adds_identity_but_keeps_an_inner_agent():
    assert agent_events.stamp({"type": "step_start"}, "orchestrator", "Ember") == {
        "type": "step_start", "agent_id": "orchestrator", "agent_label": "Ember",
    }
    inner = {"type": "step_start", "agent_id": "calc", "agent_label": "Calculator"}
    assert agent_events.stamp(inner, "orchestrator", "Ember") == inner


def test_forwarded_translates_tokens_and_drops_usage():
    token = {"type": "token", "text": "15%", "agent_id": "calc", "agent_label": "Calculator"}
    assert agent_events.forwarded(token, "step-9") == {
        "type": "agent_token", "agent_id": "calc", "agent_label": "Calculator", "step_id": "step-9", "text": "15%",
    }
    reset = agent_events.forwarded({"type": "token_reset", "agent_id": "calc", "agent_label": "C"}, "step-9")
    assert reset["reset"] is True and reset["text"] == ""
    step = {"type": "step_start", "id": "x", "agent_id": "calc"}
    assert agent_events.forwarded(step, "step-9") == step
    assert agent_events.forwarded({"type": "usage", "total_tokens": 5}, "step-9") is None
    assert agent_events.forwarded({"type": "approval_request"}, "step-9") is None


def test_dispatch_with_progress_carries_emitted_events_to_on_event():
    events = []

    async def on_event(event):
        events.append(event)

    def dispatch():
        assert agent_events.current_step_id() == "step-1"
        agent_events.emit({"type": "agent_start", "agent_id": "calc"})
        agent_events.emit({"type": "agent_end", "agent_id": "calc", "ok": True})
        return "done"

    assert asyncio.run(dispatch_with_progress(dispatch, on_event, "step-1")) == "done"
    assert [e["type"] for e in events] == ["agent_start", "agent_end"]
    assert agent_events.emitter() is None


def test_emit_without_a_bound_sink_is_a_noop():
    agent_events.emit({"type": "agent_start"})
