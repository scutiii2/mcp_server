"""agent_registry.py tests: config loading and lookup.

_AGENTS/_AGENTS_BY_ID are built once at import time from a fixed path,
so tests monkeypatch that module state directly (via _load()) rather
than reloading the module - reload() would just re-run the same
top-level code against the real _CONFIG_PATH again, undoing a
monkeypatch made before it.
"""

from __future__ import annotations

import json

from src.services import agent_registry


def _configure(monkeypatch, tmp_path, agents):
    config_path = tmp_path / "config_agents.json"
    config_path.write_text(json.dumps({"agents": agents}), encoding="utf-8")
    monkeypatch.setattr(agent_registry, "_CONFIG_PATH", config_path)

    loaded = agent_registry._load()
    monkeypatch.setattr(agent_registry, "_AGENTS", loaded)
    monkeypatch.setattr(agent_registry, "_AGENTS_BY_ID", {agent["id"]: agent for agent in loaded})


def test_all_agents_returns_every_configured_entry(monkeypatch, tmp_path):
    agents = [
        {"id": "claude-agent", "label": "Claude Agent", "url": "http://127.0.0.1:9100/mcp"},
        {"id": "openai-agent", "label": "OpenAI Agent", "url": "http://127.0.0.1:9101/mcp"},
    ]
    _configure(monkeypatch, tmp_path, agents)

    assert agent_registry.all_agents() == agents
    assert agent_registry.list_agent_ids() == ["claude-agent", "openai-agent"]


def test_get_agent_returns_the_matching_entry(monkeypatch, tmp_path):
    agents = [{"id": "claude-agent", "label": "Claude Agent", "url": "http://127.0.0.1:9100/mcp"}]
    _configure(monkeypatch, tmp_path, agents)

    assert agent_registry.get_agent("claude-agent") == agents[0]


def test_get_agent_returns_none_for_unknown_id(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path, [])

    assert agent_registry.get_agent("nope") is None


def test_get_agent_returns_none_for_falsy_id(monkeypatch, tmp_path):
    """chat_api() passes data.get("provider") straight through, which is
    None for a request that omitted it - must not raise or match
    anything."""
    _configure(monkeypatch, tmp_path, [])

    assert agent_registry.get_agent(None) is None
    assert agent_registry.get_agent("") is None


def test_missing_config_file_yields_no_agents(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_registry, "_CONFIG_PATH", tmp_path / "does_not_exist.json")

    assert agent_registry._load() == []
