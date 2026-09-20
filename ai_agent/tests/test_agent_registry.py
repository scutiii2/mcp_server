"""agent_registry.py tests: config loading/lookup, and the
register()/deregister() self-registration this instance runs at
startup/shutdown (see server.py's main())."""

from __future__ import annotations

import json

from src import agent_registry


def _configure(monkeypatch, tmp_path, agents, chat_app_agents=None):
    config_path = tmp_path / "config_agents.json"
    config_path.write_text(json.dumps({"agents": agents}), encoding="utf-8")
    monkeypatch.setattr(agent_registry, "_CONFIG_PATH", config_path)

    chat_app_config_path = tmp_path / "chat_app_config_agents.json"
    chat_app_config_path.write_text(
        json.dumps({"agents": chat_app_agents if chat_app_agents is not None else agents}), encoding="utf-8"
    )
    monkeypatch.setattr(agent_registry, "_CHAT_APP_CONFIG_PATH", chat_app_config_path)

    agent_registry.reload()
    return config_path, chat_app_config_path


def test_agent_id_for_uses_the_pre_rename_provider_names():
    # PROVIDER_ID is "anthropic"/"openai" (see agent_config.py), but the
    # agent id predates that rename and must stay "claude-agent" - see
    # the module docstring's note on delegate_to_agent/chat history/
    # cancel all already referencing it.
    assert agent_registry.agent_id_for("anthropic") == "claude-agent"
    assert agent_registry.agent_id_for("openai") == "openai-agent"


def test_register_adds_this_instance_to_both_config_files(monkeypatch, tmp_path):
    config_path, chat_app_config_path = _configure(monkeypatch, tmp_path, [])

    agent_registry.register("claude-agent", "Claude Agent", "http://127.0.0.1:9100/mcp")

    expected = [{"id": "claude-agent", "label": "Claude Agent", "url": "http://127.0.0.1:9100/mcp"}]
    assert json.loads(config_path.read_text(encoding="utf-8"))["agents"] == expected
    assert json.loads(chat_app_config_path.read_text(encoding="utf-8"))["agents"] == expected
    assert agent_registry.get_agent("claude-agent") == expected[0]


def test_register_upserts_rather_than_duplicating_an_existing_id(monkeypatch, tmp_path):
    existing = [{"id": "claude-agent", "label": "Stale Label", "url": "http://127.0.0.1:9999/mcp"}]
    _configure(monkeypatch, tmp_path, existing)

    agent_registry.register("claude-agent", "Claude Agent", "http://127.0.0.1:9100/mcp")

    assert agent_registry.all_agents() == [
        {"id": "claude-agent", "label": "Claude Agent", "url": "http://127.0.0.1:9100/mcp"}
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
    config_path, chat_app_config_path = _configure(monkeypatch, tmp_path, agents)

    agent_registry.deregister("claude-agent")

    assert agent_registry.list_agent_ids() == ["openai-agent"]
    assert json.loads(config_path.read_text(encoding="utf-8"))["agents"] == [agents[1]]
    assert json.loads(chat_app_config_path.read_text(encoding="utf-8"))["agents"] == [agents[1]]


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
