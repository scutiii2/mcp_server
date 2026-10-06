"""agent_spec.py tests: defaults, every validation error, the set-level
checks (ports, exactly one entry), the env-var fallback spec, and the
env-var hand-off a child does before importing agent_config."""

from __future__ import annotations

import json
import os

import pytest

from src.agents import agent_spec
from src.agents.agent_spec import AgentSpecError, ToolScope


def _write(directory, name, data):
    path = directory / f"{name}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_load_file_applies_defaults(tmp_path):
    spec = agent_spec.load_file(_write(tmp_path, "calc", {"port": 9103, "llm": {"provider": "anthropic"}}))

    assert spec.id == "calc"
    assert spec.label == "calc"
    assert spec.port == 9103
    assert spec.enabled is True
    assert spec.entry is False
    assert spec.persona == ""
    assert spec.focus == ""
    assert spec.orchestrator is False
    assert spec.tools == ToolScope()
    assert spec.llm.provider == "anthropic"
    assert spec.llm.reasoning_effort == "off"
    assert spec.routing.top_k == 3
    assert spec.source == tmp_path / "calc.json"


def test_load_file_reads_every_field(tmp_path):
    data = {
        "label": "Ember",
        "port": 9100,
        "enabled": True,
        "entry": True,
        "llm": {
            "provider": "openai", "gateway": "azure", "model": "gpt-x", "temperature": 0.2,
            "reasoning_effort": "high", "max_tokens": 4096, "max_tool_rounds": 8,
        },
        "persona": "You coordinate.",
        "focus": "Everything.",
        "tools": {"allow": ["calc_*"], "deny": ["calc_secret"]},
        "orchestrator": True,
        "routing": {"laya": True, "top_k": 2, "allow_auto": True, "min_score": 0.3},
    }
    spec = agent_spec.load_file(_write(tmp_path, "orchestrator", data))

    assert spec.label == "Ember"
    assert spec.llm.gateway == "azure"
    assert spec.llm.temperature == 0.2
    assert spec.llm.max_tool_rounds == 8
    assert spec.tools == ToolScope(allow=("calc_*",), deny=("calc_secret",))
    assert spec.routing.laya is True
    assert spec.routing.min_score == 0.3


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"llm": {"provider": "anthropic"}}, "port"),
        ({"port": 9100}, "llm"),
        ({"port": 9100, "llm": {}}, "llm.provider"),
        ({"port": 9100, "llm": {"provider": "gemini"}}, "llm.provider"),
        ({"port": 9100, "llm": {"provider": "anthropic"}, "colour": "red"}, "colour"),
        ({"port": 9100, "llm": {"provider": "anthropic", "temp": 1}}, "llm.temp"),
        ({"port": "9100", "llm": {"provider": "anthropic"}}, "port"),
        ({"port": 0, "llm": {"provider": "anthropic"}}, "port"),
        ({"port": 9100, "llm": {"provider": "anthropic", "temperature": 3}}, "llm.temperature"),
        ({"port": 9100, "llm": {"provider": "anthropic", "reasoning_effort": "max"}}, "llm.reasoning_effort"),
        ({"port": 9100, "llm": {"provider": "anthropic", "max_tokens": 0}}, "llm.max_tokens"),
        ({"port": 9100, "llm": {"provider": "anthropic"}, "tools": {"allow": "calc_*"}}, "tools.allow"),
        ({"port": 9100, "llm": {"provider": "anthropic"}, "routing": {"laya": True}}, "routing"),
        ({"port": 9100, "llm": {"provider": "anthropic"}, "orchestrator": True, "routing": {"top_k": 0}}, "routing.top_k"),
        ({"port": 9100, "llm": {"provider": "anthropic"}, "orchestrator": True, "routing": {"min_score": 2}}, "routing.min_score"),
        ({"port": 9100, "llm": {"provider": "anthropic"}, "entry": "yes"}, "entry"),
        ({"port": None, "llm": {"provider": "anthropic"}}, "port"),
        ({"port": 9100, "llm": {"provider": "anthropic"}, "enabled": None}, "enabled"),
        ({"port": 9100, "llm": {"provider": "anthropic"}, "entry": None}, "entry"),
        ({"port": 9100, "llm": {"provider": "anthropic"}, "orchestrator": None}, "orchestrator"),
        ({"port": 9100, "llm": {"provider": "anthropic", "reasoning_effort": None}}, "llm.reasoning_effort"),
        ({"port": 9100, "llm": {"provider": "anthropic"}, "orchestrator": True, "routing": {"top_k": None}}, "routing.top_k"),
        ({"port": 9100, "llm": {"provider": "anthropic"}, "orchestrator": True, "routing": {"laya": None}}, "routing.laya"),
        ({"port": 9100, "llm": {"provider": "anthropic"}, "orchestrator": True, "routing": {"allow_auto": None}}, "routing.allow_auto"),
    ],
)
def test_load_file_rejects_bad_fields(tmp_path, data, message):
    with pytest.raises(AgentSpecError) as error:
        agent_spec.load_file(_write(tmp_path, "calc", data))
    assert "calc.json" in str(error.value)
    assert message in str(error.value)


def test_load_file_rejects_bad_json(tmp_path):
    path = tmp_path / "calc.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(AgentSpecError, match="calc.json"):
        agent_spec.load_file(path)


def test_load_file_rejects_a_bad_id(tmp_path):
    with pytest.raises(AgentSpecError, match="id"):
        agent_spec.load_file(_write(tmp_path, "Calc_Agent", {"port": 9100, "llm": {"provider": "anthropic"}}))


def test_load_dir_requires_exactly_one_entry(tmp_path):
    _write(tmp_path, "a", {"port": 9100, "llm": {"provider": "anthropic"}})
    _write(tmp_path, "b", {"port": 9101, "llm": {"provider": "anthropic"}})
    with pytest.raises(AgentSpecError, match="entry"):
        agent_spec.load_dir(tmp_path)

    _write(tmp_path, "a", {"port": 9100, "entry": True, "llm": {"provider": "anthropic"}})
    _write(tmp_path, "b", {"port": 9101, "entry": True, "llm": {"provider": "anthropic"}})
    with pytest.raises(AgentSpecError, match="a.json, b.json"):
        agent_spec.load_dir(tmp_path)


def test_load_dir_ignores_disabled_files_for_set_checks(tmp_path):
    _write(tmp_path, "a", {"port": 9100, "entry": True, "llm": {"provider": "anthropic"}})
    _write(tmp_path, "b", {"port": 9100, "entry": True, "enabled": False, "llm": {"provider": "anthropic"}})

    specs = agent_spec.load_dir(tmp_path)

    assert [s.id for s in specs] == ["a", "b"]


def test_load_dir_rejects_duplicate_ports(tmp_path):
    _write(tmp_path, "a", {"port": 9100, "entry": True, "llm": {"provider": "anthropic"}})
    _write(tmp_path, "b", {"port": 9100, "llm": {"provider": "anthropic"}})
    with pytest.raises(AgentSpecError, match="9100"):
        agent_spec.load_dir(tmp_path)


def test_load_dir_rejects_an_empty_directory(tmp_path):
    with pytest.raises(AgentSpecError, match="no agent files"):
        agent_spec.load_dir(tmp_path)


def test_tool_scope_allow_deny_and_unmatched():
    everything = ToolScope()
    assert everything.allows("anything") is True

    scope = ToolScope(allow=("calc_*", "convert_*"), deny=("calc_secret",))
    assert scope.allows("calc_add") is True
    assert scope.allows("calc_secret") is False
    assert scope.allows("weather_now") is False
    assert scope.unmatched(["calc_add", "calc_secret"]) == ["convert_*"]


def test_from_env_builds_a_legacy_orchestrator(monkeypatch):
    monkeypatch.setenv("AI_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("AI_AGENT_PORT", "9102")
    monkeypatch.setenv("AI_AGENT_MODEL", "gpt-x")
    monkeypatch.setenv("AI_AGENT_GATEWAY", "azure")

    spec = agent_spec.from_env()

    assert spec.id == "openai-agent"
    assert spec.port == 9102
    assert spec.label == ""
    assert spec.persona is None
    assert spec.orchestrator is True
    assert spec.llm.model == "gpt-x"
    assert spec.source is None
    assert spec.effective_gateway() == "azure"


@pytest.mark.parametrize("value", ["abc", "9x", "1.5"])
def test_from_env_rejects_a_non_numeric_port(monkeypatch, value):
    monkeypatch.setenv("AI_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("AI_AGENT_PORT", value)
    with pytest.raises(AgentSpecError, match="AI_AGENT_PORT must be a whole number from 1 to 65535"):
        agent_spec.from_env()


def test_effective_gateway_for_a_file_spec_ignores_the_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_AGENT_GATEWAY", "openrouter")
    spec = agent_spec.load_file(_write(tmp_path, "calc", {"port": 9103, "llm": {"provider": "anthropic"}}))
    assert spec.effective_gateway() is None


def test_current_reads_ai_agent_file_and_caches(tmp_path, monkeypatch):
    path = _write(tmp_path, "calc", {"port": 9103, "llm": {"provider": "anthropic"}})
    monkeypatch.setenv("AI_AGENT_FILE", str(path))
    monkeypatch.setattr(agent_spec, "_current", None)

    first = agent_spec.current()
    path.write_text("{broken", encoding="utf-8")

    assert first.id == "calc"
    assert agent_spec.current() is first


def test_apply_to_environ_sets_provider_gateway_model_and_port(tmp_path, monkeypatch):
    for name in ("AI_AGENT_PROVIDER", "AI_AGENT_GATEWAY", "AI_AGENT_MODEL", "AI_AGENT_PORT"):
        monkeypatch.delenv(name, raising=False)
    spec = agent_spec.load_file(_write(tmp_path, "calc", {"port": 9103, "llm": {"provider": "openai"}}))

    agent_spec.apply_to_environ(spec)

    assert os.environ["AI_AGENT_PROVIDER"] == "openai"
    # No gateway in the file: pin the provider default so .env's
    # AI_AGENT_GATEWAY (loaded later with setdefault) cannot override it.
    assert os.environ["AI_AGENT_GATEWAY"] == "gpt"
    assert os.environ["AI_AGENT_MODEL"] == ""
    assert os.environ["AI_AGENT_PORT"] == "9103"
