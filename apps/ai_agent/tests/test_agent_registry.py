"""agent_registry.py tests: config loading/lookup, and the
register()/deregister() self-registration this instance runs at
startup/shutdown (see server.py's main())."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agents import agent_registry
from src.agents.agent_spec import AgentSpec, LlmSpec


def _configure(monkeypatch, tmp_path, agents):
    config_path = tmp_path / "agent_registry.json"
    config_path.write_text(json.dumps({"agents": agents}), encoding="utf-8")
    monkeypatch.setattr(agent_registry, "_CONFIG_PATH", config_path)

    agent_registry.reload()
    return config_path


def test_agent_id_for_uses_the_pre_rename_provider_names():
    # PROVIDER_ID is "anthropic"/"openai" (see agent_config.py), but the
    # agent id predates that rename and must stay "claude-agent" - see
    # the module docstring's note on delegate_to_agent/chat history/
    # cancel all already referencing it.
    assert agent_registry.agent_id_for("anthropic") == "claude-agent"
    assert agent_registry.agent_id_for("openai") == "openai-agent"


def test_register_adds_this_instance_to_the_config_file(monkeypatch, tmp_path):
    config_path = _configure(monkeypatch, tmp_path, [])

    agent_registry.register("claude-agent", "Claude Agent", "http://127.0.0.1:9100/mcp")

    expected = [{
        "id": "claude-agent", "label": "Claude Agent", "url": "http://127.0.0.1:9100/mcp",
        "entry": False, "orchestrator": False, "focus": "",
    }]
    assert json.loads(config_path.read_text(encoding="utf-8"))["agents"] == expected
    assert agent_registry.get_agent("claude-agent") == expected[0]


def test_register_creates_the_missing_data_folder(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path, [])
    target = tmp_path / "fresh" / "agent_registry.json"
    monkeypatch.setattr(agent_registry, "_CONFIG_PATH", target)

    agent_registry.register("claude-agent", "Claude Agent", "http://127.0.0.1:9100/mcp")

    assert agent_registry.list_agent_ids() == ["claude-agent"]
    assert target.exists()


def test_register_upserts_rather_than_duplicating_an_existing_id(monkeypatch, tmp_path):
    existing = [{"id": "claude-agent", "label": "Stale Label", "url": "http://127.0.0.1:9999/mcp"}]
    _configure(monkeypatch, tmp_path, existing)

    agent_registry.register("claude-agent", "Claude Agent", "http://127.0.0.1:9100/mcp")

    assert agent_registry.all_agents() == [
        {
            "id": "claude-agent", "label": "Claude Agent", "url": "http://127.0.0.1:9100/mcp",
            "entry": False, "orchestrator": False, "focus": "",
        }
    ]


def test_register_leaves_other_agents_untouched(monkeypatch, tmp_path):
    other = {"id": "openai-agent", "label": "OpenAI Agent", "url": "http://127.0.0.1:9101/mcp"}
    _configure(monkeypatch, tmp_path, [other])

    agent_registry.register("claude-agent", "Claude Agent", "http://127.0.0.1:9100/mcp")

    ids = set(agent_registry.list_agent_ids())
    assert ids == {"claude-agent", "openai-agent"}
    assert agent_registry.get_agent("openai-agent") == other


def test_deregister_removes_only_the_matching_id(monkeypatch, tmp_path):
    agents = [
        {"id": "claude-agent", "label": "Claude Agent", "url": "http://127.0.0.1:9100/mcp"},
        {"id": "openai-agent", "label": "OpenAI Agent", "url": "http://127.0.0.1:9101/mcp"},
    ]
    config_path = _configure(monkeypatch, tmp_path, agents)

    agent_registry.deregister("claude-agent")

    assert agent_registry.list_agent_ids() == ["openai-agent"]
    assert json.loads(config_path.read_text(encoding="utf-8"))["agents"] == [agents[1]]


def test_deregister_unknown_id_is_a_no_op(monkeypatch, tmp_path):
    agents = [{"id": "claude-agent", "label": "Claude Agent", "url": "http://127.0.0.1:9100/mcp"}]
    _configure(monkeypatch, tmp_path, agents)

    agent_registry.deregister("nope")

    assert agent_registry.all_agents() == agents


def test_all_agents_returns_every_configured_entry(monkeypatch, tmp_path):
    agents = [
        {"id": "claude-agent", "label": "Claude Agent", "url": "http://127.0.0.1:9100/mcp"},
        {"id": "openai-agent", "label": "OpenAI Agent", "url": "http://127.0.0.1:9101/mcp"},
    ]
    _configure(monkeypatch, tmp_path, agents)

    assert agent_registry.all_agents() == agents
    assert agent_registry.list_agent_ids() == ["claude-agent", "openai-agent"]


def test_get_agent_returns_none_for_unknown_id(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path, [])

    assert agent_registry.get_agent("nope") is None


def test_get_agent_returns_none_for_falsy_id(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path, [])

    assert agent_registry.get_agent(None) is None
    assert agent_registry.get_agent("") is None


def test_missing_config_file_yields_no_agents(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_registry, "_CONFIG_PATH", tmp_path / "does_not_exist.json")

    assert agent_registry._load() == []


def test_register_writes_entry_orchestrator_and_focus(monkeypatch, tmp_path):
    config_path = _configure(monkeypatch, tmp_path, [])

    agent_registry.register(
        "calc", "Calculator", "http://127.0.0.1:9103/mcp",
        entry=False, orchestrator=False, focus="Arithmetic and unit conversion.",
    )
    agent_registry.register("orchestrator", "Ember", "http://127.0.0.1:9100/mcp", entry=True, orchestrator=True)

    agents = {a["id"]: a for a in json.loads(config_path.read_text(encoding="utf-8"))["agents"]}
    assert agents["calc"]["focus"] == "Arithmetic and unit conversion."
    assert agents["orchestrator"]["entry"] is True
    assert agents["orchestrator"]["orchestrator"] is True


def test_old_entries_without_new_keys_still_load(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path, [{"id": "claude-agent", "label": "Claude Agent", "url": "http://x/mcp"}])

    agent = agent_registry.get_agent("claude-agent")

    assert agent["url"] == "http://x/mcp"
    assert agent.get("orchestrator", False) is False


def test_write_writes_the_file_and_leaves_no_temp_file(tmp_path):
    target = tmp_path / "agent_registry.json"

    agent_registry._write(target, [{"id": "a", "label": "A", "url": "u"}])

    assert json.loads(target.read_text(encoding="utf-8"))["agents"][0]["id"] == "a"
    assert [p.name for p in tmp_path.iterdir()] == ["agent_registry.json"]


def test_write_swaps_a_temp_file_in_with_os_replace(monkeypatch, tmp_path):
    target = tmp_path / "agent_registry.json"
    target.write_text('{"agents": []}', encoding="utf-8")
    real_replace = agent_registry.os.replace
    calls = []

    def spy(source, destination):
        # The new content is complete in the temp file BEFORE the swap, and
        # the target still holds the old content until it happens.
        calls.append((Path(source).parent, Path(destination)))
        assert json.loads(Path(source).read_text(encoding="utf-8"))["agents"][0]["id"] == "a"
        assert json.loads(target.read_text(encoding="utf-8"))["agents"] == []
        real_replace(source, destination)

    monkeypatch.setattr(agent_registry.os, "replace", spy)

    agent_registry._write(target, [{"id": "a", "label": "A", "url": "u"}])

    assert calls == [(tmp_path, target)]
    assert json.loads(target.read_text(encoding="utf-8"))["agents"][0]["id"] == "a"


def test_failed_swap_keeps_the_old_file_and_removes_the_temp_file(monkeypatch, tmp_path):
    target = tmp_path / "agent_registry.json"
    target.write_text('{"agents": []}', encoding="utf-8")

    def boom(source, destination):
        raise OSError("disk gone")

    monkeypatch.setattr(agent_registry.os, "replace", boom)

    with pytest.raises(OSError, match="disk gone"):
        agent_registry._write(target, [{"id": "a", "label": "A", "url": "u"}])

    assert json.loads(target.read_text(encoding="utf-8"))["agents"] == []
    assert [p.name for p in tmp_path.iterdir()] == ["agent_registry.json"]


def test_swap_is_retried_when_a_reader_holds_the_file(monkeypatch, tmp_path):
    target = tmp_path / "agent_registry.json"
    real_replace = agent_registry.os.replace
    attempts = []

    def flaky(source, destination):
        attempts.append(1)
        if len(attempts) < 3:
            raise PermissionError("in use")
        real_replace(source, destination)

    monkeypatch.setattr(agent_registry.os, "replace", flaky)
    monkeypatch.setattr(agent_registry.time, "sleep", lambda seconds: None)

    agent_registry._write(target, [{"id": "a", "label": "A", "url": "u"}])

    assert len(attempts) == 3
    assert json.loads(target.read_text(encoding="utf-8"))["agents"][0]["id"] == "a"
    assert [p.name for p in tmp_path.iterdir()] == ["agent_registry.json"]


def test_swap_gives_up_after_the_last_attempt(monkeypatch, tmp_path):
    target = tmp_path / "agent_registry.json"
    attempts = []

    def locked(source, destination):
        attempts.append(1)
        raise PermissionError("in use")

    monkeypatch.setattr(agent_registry.os, "replace", locked)
    monkeypatch.setattr(agent_registry.time, "sleep", lambda seconds: None)

    with pytest.raises(PermissionError):
        agent_registry._write(target, [{"id": "a", "label": "A", "url": "u"}])

    assert len(attempts) == agent_registry._REPLACE_ATTEMPTS
    assert list(tmp_path.iterdir()) == []


def test_reload_keeps_previous_agents_when_the_file_is_corrupt(monkeypatch, tmp_path):
    agents = [{"id": "claude-agent", "label": "Claude Agent", "url": "http://x/mcp"}]
    config_path = _configure(monkeypatch, tmp_path, agents)
    config_path.write_text('{"agents": [{"id": "cla', encoding="utf-8")

    agent_registry.reload()

    assert agent_registry.all_agents() == agents
    assert agent_registry.get_agent("claude-agent") == agents[0]


def test_roster_and_specialists_survive_a_corrupt_registry_file(monkeypatch, tmp_path):
    import asyncio

    from src.agents import agent_routing, agent_spec
    from src.agents.agent_spec import AgentSpec, LlmSpec

    agents = [
        {"id": "orchestrator", "label": "Ember", "url": "u", "orchestrator": True},
        {"id": "calc", "label": "Calculator", "url": "u", "focus": "arithmetic"},
    ]
    config_path = _configure(monkeypatch, tmp_path, agents)
    spec = AgentSpec(id="orchestrator", label="Ember", port=9100, llm=LlmSpec(provider="anthropic"), orchestrator=True)
    monkeypatch.setattr(agent_spec, "_current", spec)
    config_path.write_text("{", encoding="utf-8")

    assert [r.id for r in agent_routing.specialists()] == ["calc"]
    assert [r.id for r in asyncio.run(agent_routing.roster_for("q"))] == ["calc"]


def test_definitions_round_trip_and_include_disabled_agents():
    specs = [
        AgentSpec(
            id="ember", label="Ember", port=9100, entry=True, orchestrator=True, focus="General.",
            llm=LlmSpec(provider="anthropic", gateway="openrouter", model="claude-sonnet-5-5"),
        ),
        AgentSpec(id="off", label="Off", port=9101, llm=LlmSpec(provider="anthropic"), enabled=False),
    ]

    agent_registry.write_definitions(specs)

    assert agent_registry.read_definitions() == [
        {
            "id": "ember", "label": "Ember", "focus": "General.", "entry": True, "orchestrator": True, "enabled": True,
            "llm": {"provider": "anthropic", "gateway": "openrouter", "model": "claude-sonnet-5-5"},
        },
        {
            "id": "off", "label": "Off", "focus": "", "entry": False, "orchestrator": False, "enabled": False,
            "llm": {"provider": "anthropic", "gateway": None, "model": None},
        },
    ]
    # The registry itself is untouched: definitions live in their own file.
    assert agent_registry.all_agents() == []


def test_definitions_are_empty_when_nothing_was_published_or_the_file_is_broken():
    assert agent_registry.read_definitions() == []
    agent_registry._CONFIG_PATH.parent.mkdir(parents=True)
    agent_registry._definitions_path().write_text("{not json", encoding="utf-8")
    assert agent_registry.read_definitions() == []


def test_register_publishes_tiers_only_when_there_are_some(monkeypatch, tmp_path):
    config_path = _configure(monkeypatch, tmp_path, [])
    tiers = [{"tier": "light", "id": "haiku", "use_for": "quick"}]

    agent_registry.register("calc", "Calc", "http://127.0.0.1:9103/mcp", tiers=tiers)
    agent_registry.register("plain", "Plain", "http://127.0.0.1:9104/mcp", tiers=[])

    records = {a["id"]: a for a in json.loads(config_path.read_text(encoding="utf-8"))["agents"]}
    assert records["calc"]["tiers"] == tiers
    assert "tiers" not in records["plain"]
