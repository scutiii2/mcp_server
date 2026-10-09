"""Reasoning-effort control: the agent file's llm.max_effort cap, the pure
resolution against it, a per-turn override in llm_options, and the delegate
tool's reasoning_effort parameter. Mirrors the model-tier tests."""

from __future__ import annotations

import json

import pytest

from src.agents import agent_spec
from src.agents.agent_spec import AgentSpecError


def _write(directory, name, data):
    path = directory / f"{name}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# --- agent_spec -----------------------------------------------------------


def test_llm_max_effort_is_read_and_defaults_to_unbounded(tmp_path):
    capped = agent_spec.load_file(_write(tmp_path, "calc", {
        "port": 9103, "llm": {"provider": "anthropic", "max_effort": "medium"},
    }))
    plain = agent_spec.load_file(_write(tmp_path, "plain", {"port": 9104, "llm": {"provider": "anthropic"}}))
    assert capped.llm.max_effort == "medium"
    assert plain.llm.max_effort is None


def test_unknown_max_effort_is_rejected(tmp_path):
    path = _write(tmp_path, "calc", {"port": 9103, "llm": {"provider": "anthropic", "max_effort": "extreme"}})
    with pytest.raises(AgentSpecError, match="llm.max_effort must be one of: off, low, medium, high"):
        agent_spec.load_file(path)


def test_default_effort_above_max_effort_is_rejected(tmp_path):
    path = _write(tmp_path, "calc", {
        "port": 9103, "llm": {"provider": "anthropic", "reasoning_effort": "high", "max_effort": "low"},
    })
    with pytest.raises(AgentSpecError, match="llm.reasoning_effort 'high' is above llm.max_effort 'low'"):
        agent_spec.load_file(path)


def test_laya_rejects_max_effort(tmp_path):
    path = _write(tmp_path, "triage", {"port": 9110, "llm": {"provider": "laya", "max_effort": "low"}})
    with pytest.raises(AgentSpecError, match="Laya triage does not accept"):
        agent_spec.load_file(path)


def test_roster_entry_efforts_default_to_empty():
    assert agent_spec.RosterEntry("calc", "Calculator", "Math.").efforts == ()
    entry = agent_spec.RosterEntry("calc", "Calculator", "Math.", (), ("off", "low"))
    assert entry.efforts == ("off", "low")


# --- reasoning_effort (pure resolution) -----------------------------------

from src.agents.agent_spec import AgentSpec, LlmSpec  # noqa: E402
from src.llm import llm_options, reasoning_effort  # noqa: E402


def test_allowed_efforts_run_up_to_the_cap():
    assert reasoning_effort.allowed(None) == ("off", "low", "medium", "high")
    assert reasoning_effort.allowed("medium") == ("off", "low", "medium")
    assert reasoning_effort.allowed("off") == ("off",)


def test_resolve_without_a_request_changes_nothing():
    assert reasoning_effort.resolve(None, "low", "calc") == reasoning_effort.EffortResolution(None)


def test_resolve_within_the_cap_is_exact_and_silent():
    assert reasoning_effort.resolve("low", "medium", "calc") == reasoning_effort.EffortResolution("low")
    assert reasoning_effort.resolve("high", None, "calc") == reasoning_effort.EffortResolution("high")
    assert reasoning_effort.resolve("off", "low", "calc") == reasoning_effort.EffortResolution("off")


def test_resolve_above_the_cap_clamps_down_with_a_note():
    result = reasoning_effort.resolve("high", "low", "pdf-assistant")
    assert result.effort == "low"
    assert result.note == "high is above pdf-assistant's reasoning_effort limit; ran on low"


def test_resolve_an_invalid_name_uses_the_default_with_a_note():
    result = reasoning_effort.resolve("extreme", "low", "calc")
    assert result.effort is None
    assert "unknown reasoning_effort 'extreme'" in result.note


def test_effort_records_round_trip_and_junk_is_skipped():
    assert reasoning_effort.from_record(["off", "low", "bogus", 3]) == ("off", "low")
    assert reasoning_effort.from_record(None) == ()
    assert reasoning_effort.from_record("low") == ()


def _use_spec(monkeypatch, provider="anthropic", **llm):
    spec = AgentSpec(id="calc", label="Calc", port=9103, llm=LlmSpec(provider=provider, **llm))
    monkeypatch.setattr(agent_spec, "_current", spec)


def test_own_efforts_follow_this_agents_cap(monkeypatch):
    _use_spec(monkeypatch, max_effort="low")
    assert reasoning_effort.own_efforts() == ("off", "low")
    _use_spec(monkeypatch)
    assert reasoning_effort.own_efforts() == ("off", "low", "medium", "high")


def test_own_efforts_of_a_laya_agent_is_empty(monkeypatch):
    _use_spec(monkeypatch, provider="laya")
    assert reasoning_effort.own_efforts() == ()


# --- llm_options: per-turn override ---------------------------------------


def _options(provider="anthropic", **llm):
    return llm_options.LlmOptions(provider, "calc", LlmSpec(provider=provider, **llm))


def test_a_bound_effort_overrides_the_agents_default_for_the_turn():
    options = _options(reasoning_effort="low")
    assert options.extra_kwargs("m") == {"output_config": {"effort": "low"}}
    token = llm_options.bind_effort("high")
    try:
        assert options.extra_kwargs("m") == {"output_config": {"effort": "high"}}
    finally:
        llm_options.reset_effort(token)
    assert options.extra_kwargs("m") == {"output_config": {"effort": "low"}}


def test_a_bound_off_sends_no_reasoning():
    options = _options(reasoning_effort="high")
    token = llm_options.bind_effort("off")
    try:
        assert options.extra_kwargs("m") == {}
    finally:
        llm_options.reset_effort(token)


def test_a_bound_effort_turns_reasoning_on_for_an_agent_that_has_it_off():
    options = _options()
    token = llm_options.bind_effort("medium")
    try:
        assert options.extra_kwargs("m") == {"output_config": {"effort": "medium"}}
    finally:
        llm_options.reset_effort(token)


def test_a_bound_effort_uses_the_openai_shape_for_openai():
    options = _options("openai")
    token = llm_options.bind_effort("high")
    try:
        assert options.extra_kwargs("m") == {"reasoning": {"effort": "high"}}
    finally:
        llm_options.reset_effort(token)


def test_a_rejected_reasoning_option_is_still_dropped_per_model_under_an_override():
    options = _options()
    token = llm_options.bind_effort("high")
    try:
        assert options.drop_rejected("output_config.effort is not supported", "model-a") is True
        assert options.extra_kwargs("model-a") == {}
        assert options.extra_kwargs("model-b") == {"output_config": {"effort": "high"}}
    finally:
        llm_options.reset_effort(token)


# --- plumbing: run_chat, ask, usage row, registry, roster -----------------

import asyncio  # noqa: E402
from unittest.mock import AsyncMock, patch  # noqa: E402

from src import server  # noqa: E402
from src.agents import agent_config, agent_registry, agent_routing, delegation  # noqa: E402
from src.agents.agent_spec import RosterEntry  # noqa: E402
from src.core import usage_log  # noqa: E402
from src.llm.base_provider import ChatResult  # noqa: E402


def _fake_provider(seen):
    async def _fake(question, history, model, enabled_extensions, request_id, depth, on_event=None, caveman=False):
        seen["effort"] = llm_options._effort_override.get()
        return ChatResult(response="x")

    return _fake


def test_run_chat_binds_the_resolved_effort_for_the_turn_only(monkeypatch):
    _use_spec(monkeypatch, max_effort="low")
    seen = {}
    monkeypatch.setattr(agent_config._PROVIDER_MODULE, "run_chat", _fake_provider(seen))

    result = asyncio.run(agent_config.run_chat("hi", [], [], reasoning_effort="high"))

    assert seen["effort"] == "low"
    assert result.reasoning_effort == "low"
    assert "above calc's reasoning_effort limit" in result.effort_note
    assert llm_options._effort_override.get() is None


def test_run_chat_without_a_request_binds_nothing(monkeypatch):
    _use_spec(monkeypatch, max_effort="low")
    seen = {}
    monkeypatch.setattr(agent_config._PROVIDER_MODULE, "run_chat", _fake_provider(seen))

    result = asyncio.run(agent_config.run_chat("hi", [], []))

    assert seen["effort"] is None
    assert (result.reasoning_effort, result.effort_note) == (None, "")


def test_run_chat_within_the_cap_runs_at_the_requested_effort(monkeypatch):
    _use_spec(monkeypatch, max_effort="medium")
    seen = {}
    monkeypatch.setattr(agent_config._PROVIDER_MODULE, "run_chat", _fake_provider(seen))

    result = asyncio.run(agent_config.run_chat("hi", [], [], reasoning_effort="low"))

    assert seen["effort"] == "low"
    assert (result.reasoning_effort, result.effort_note) == ("low", "")


def test_ask_passes_reasoning_effort_and_reports_the_resolution():
    async def _run():
        fake_result = ChatResult(
            response="ok", provider_id="anthropic", model="m",
            reasoning_effort="low", effort_note="high is above calc's reasoning_effort limit; ran on low",
        )
        with patch("src.server.agent_config.run_chat", new_callable=AsyncMock, return_value=fake_result) as fake_run_chat, \
             patch("src.server.agent_config.status", return_value={"model": "m", "context_window": 1}):
            result = await server.ask("q", reasoning_effort="high")

        assert fake_run_chat.call_args.kwargs["reasoning_effort"] == "high"
        assert result["reasoning_effort"] == "low"
        assert result["effort_note"] == "high is above calc's reasoning_effort limit; ran on low"
        assert result["agent_usage"][0]["reasoning_effort"] == "low"

    asyncio.run(_run())


def test_ask_without_an_effort_adds_no_effort_keys():
    async def _run():
        with patch("src.server.agent_config.run_chat", new_callable=AsyncMock, return_value=ChatResult(response="hi")) as fake_run_chat, \
             patch("src.server.agent_config.status", return_value={"model": "m", "context_window": 1}):
            result = await server.ask("q")

        assert "reasoning_effort" not in fake_run_chat.call_args.kwargs
        assert "reasoning_effort" not in result and "effort_note" not in result
        assert "reasoning_effort" not in result["agent_usage"][0]

    asyncio.run(_run())


def test_own_row_records_reasoning_effort_only_when_given():
    result = ChatResult(response="x", provider_id="anthropic", model="m")
    common = dict(
        agent_id="calc", agent_label="Calc", gateway="claude",
        started_at="2026-10-08T09:00:00.000Z", finished_at="2026-10-08T09:00:01.000Z", delegated_by=None,
    )
    assert usage_log.own_row(result, **common, reasoning_effort="low")["reasoning_effort"] == "low"
    assert "reasoning_effort" not in usage_log.own_row(result, **common)


def test_register_publishes_efforts_only_when_there_are_some(monkeypatch, tmp_path):
    path = tmp_path / "agent_registry.json"
    path.write_text(json.dumps({"agents": []}), encoding="utf-8")
    monkeypatch.setattr(agent_registry, "_CONFIG_PATH", path)

    agent_registry.register("calc", "Calc", "http://127.0.0.1:9103/mcp", efforts=["off", "low"])
    agent_registry.register("plain", "Plain", "http://127.0.0.1:9104/mcp", efforts=[])

    records = {a["id"]: a for a in json.loads(path.read_text(encoding="utf-8"))["agents"]}
    assert records["calc"]["efforts"] == ["off", "low"]
    assert "efforts" not in records["plain"]


def test_specialists_carry_their_published_efforts(monkeypatch):
    agents = [
        {"id": "orchestrator", "label": "Ember", "url": "u", "orchestrator": True},
        {"id": "calc", "label": "Calc", "url": "u", "focus": "math", "efforts": ["off", "low", "bogus"]},
        {"id": "poet", "label": "Poet", "url": "u", "focus": "poems"},
    ]
    monkeypatch.setattr(agent_registry, "reload", lambda: None)
    monkeypatch.setattr(agent_registry, "_AGENTS", agents)
    spec = AgentSpec(id="orchestrator", label="Ember", port=9100, llm=LlmSpec(provider="anthropic"), orchestrator=True)
    monkeypatch.setattr(agent_spec, "_current", spec)

    calc, poet = agent_routing.specialists()

    assert calc.efforts == ("off", "low")
    assert poet.efforts == ()


# --- delegation ------------------------------------------------------------

FULL = ("off", "low", "medium", "high")
EFFORT_ROSTER = [
    RosterEntry("calc", "Calculator", "Arithmetic.", (), ("off", "low")),
    RosterEntry("poet", "Poet", "Poems.", (), FULL),
]
NO_CHOICE = [RosterEntry("solo", "Solo", "One thing.", (), ("off",)), RosterEntry("plain", "Plain", "Nothing.")]


def _configure_agents(monkeypatch, agents):
    monkeypatch.setattr(agent_registry, "_AGENTS", agents)
    monkeypatch.setattr(agent_registry, "_AGENTS_BY_ID", {a["id"]: a for a in agents})
    monkeypatch.setattr(agent_registry, "reload", lambda: None)


def test_tool_parameters_offer_reasoning_effort_only_when_there_is_a_choice():
    prop = delegation.tool_parameters(EFFORT_ROSTER)["properties"]["reasoning_effort"]
    assert prop["enum"] == ["off", "low", "medium", "high"]
    assert "reasoning_effort" not in delegation.tool_parameters(NO_CHOICE)["properties"]


def test_tool_description_names_each_specialists_effort_limit():
    description = delegation.tool_description(EFFORT_ROSTER)
    assert "calc (Calculator): Arithmetic. [reasoning_effort: up to low]" in description
    assert "poet (Poet): Poems." in description
    assert "poet (Poet): Poems. [" not in description
    assert "lowest reasoning_effort" in description
    assert "lowest reasoning_effort" not in delegation.tool_description(NO_CHOICE)


def test_call_passes_reasoning_effort_to_ask(monkeypatch):
    _configure_agents(monkeypatch, [{"id": "calc", "label": "Calc", "url": "http://c/mcp"}])
    captured = {}

    async def _fake_call_tool(url, name, arguments, on_progress=None):
        captured["arguments"] = arguments
        return {"response": "4"}

    with patch("src.agents.delegation._call_tool", side_effect=_fake_call_tool):
        delegation.call("calc", "2+2?", depth=0, reasoning_effort="low")

    assert captured["arguments"]["reasoning_effort"] == "low"


def test_call_joins_the_model_and_effort_notes(monkeypatch):
    _configure_agents(monkeypatch, [{"id": "calc", "label": "Calc", "url": "http://c/mcp"}])

    async def _fake_call_tool(url, name, arguments, on_progress=None):
        return {"response": "4", "model_note": "heavy is not available for calc; ran on standard",
                "effort_note": "high is above calc's reasoning_effort limit; ran on low"}

    with patch("src.agents.delegation._call_tool", side_effect=_fake_call_tool):
        result = delegation.call("calc", "2+2?", depth=0, model_tier="heavy", reasoning_effort="high")

    assert result == (
        "[heavy is not available for calc; ran on standard; "
        "high is above calc's reasoning_effort limit; ran on low]\n\n4"
    )


def test_dispatch_forwards_reasoning_effort_and_ignores_non_strings():
    with patch("src.agents.delegation.call", return_value="answer") as fake_call:
        delegation.dispatch({"agent_id": "calc", "question": "q", "reasoning_effort": "low"}, 1)
        delegation.dispatch({"agent_id": "calc", "question": "q", "reasoning_effort": 3}, 1)
        delegation.dispatch({"agent_id": "calc", "question": "q", "model_tier": "light", "reasoning_effort": "off"}, 1)

    calls = fake_call.call_args_list
    assert calls[0].args == ("calc", "q", 1) and calls[0].kwargs == {"reasoning_effort": "low"}
    assert calls[1].args == ("calc", "q", 1) and calls[1].kwargs == {}
    assert calls[2].kwargs == {"model_tier": "light", "reasoning_effort": "off"}
