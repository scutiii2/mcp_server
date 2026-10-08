"""prompt_config.py and the prompt helpers in agent_store.py."""

from __future__ import annotations

import json

import pytest

from src.agents import agent_store, prompt_config
from src.agents.agent_store import AgentStoreError


def test_missing_file_means_defaults(tmp_path):
    path = tmp_path / "config_prompts.json"
    assert prompt_config.load(path) == prompt_config.DEFAULTS
    assert prompt_config.overrides(path) == {}
    assert prompt_config.signature(path) is None


def test_save_keeps_only_changed_texts_and_reset_removes_them(tmp_path):
    path = tmp_path / "config_prompts.json"
    values = prompt_config.save({"app_name": "Spark", "roster_intro": prompt_config.DEFAULTS["roster_intro"]}, path)
    assert values["app_name"] == "Spark"
    assert json.loads(path.read_text()) == {"app_name": "Spark"}
    assert prompt_config.signature(path) is not None

    values = prompt_config.save({"app_name": None}, path)
    assert values["app_name"] == "Ember"
    assert json.loads(path.read_text()) == {}
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize(
    "changes",
    [{"nope": "x"}, {"app_name": "x" * 9000}, {"identity_template": "Hi {role} {secret}"}, {"identity_template": "Hi {role"}],
)
def test_bad_changes_are_refused_and_write_nothing(tmp_path, changes):
    path = tmp_path / "config_prompts.json"
    with pytest.raises(prompt_config.PromptConfigError):
        prompt_config.save(changes, path)
    assert not path.exists()


def test_store_prompts_round_trip_and_type_check(tmp_path):
    path = tmp_path / "config_prompts.json"
    result = agent_store.set_prompts({"app_description": "A new blurb."}, path)
    assert result["values"]["app_description"] == "A new blurb."
    assert result["overridden"] == ["app_description"]
    assert result["defaults"]["app_description"] != "A new blurb."
    with pytest.raises(AgentStoreError):
        agent_store.set_prompts({"app_name": 5}, path)
    with pytest.raises(AgentStoreError, match="unknown"):
        agent_store.set_prompts({"bogus": "x"}, path)


def _agent(port, **extra):
    return {"label": "Calc", "port": port, "llm": {"provider": "anthropic"}, **extra}


def test_preview_uses_shared_texts_roster_and_agent_identity(tmp_path):
    folder = tmp_path / "agents"
    folder.mkdir()
    (folder / "calc.json").write_text(json.dumps(_agent(9103, focus="Maths")), encoding="utf-8")
    prompts = tmp_path / "config_prompts.json"
    agent_store.set_prompts({"app_name": "Spark", "roster_intro": "Delegate wisely:"}, prompts)

    draft = _agent(9100, entry=True, orchestrator=True, persona="Be kind.", instructions="Do it.")
    text = agent_store.preview_prompt("ember", draft, directory=folder, prompts_path=prompts)
    assert text.startswith("Your name is Spark: Orchestrator")
    assert "Delegate wisely:\n- calc - Calc: Maths" in text
    assert text.index("Be kind.") < text.index("Delegate wisely:") < text.index("Do it.")

    custom = agent_store.preview_prompt("ember", {**draft, "identity": "I am Boss."}, True, folder, prompts)
    assert custom.startswith("I am Boss.")
    assert custom.endswith(prompt_config.DEFAULTS["caveman_instructions"])


def test_preview_refuses_an_invalid_draft(tmp_path):
    with pytest.raises(AgentStoreError, match="llm"):
        agent_store.preview_prompt("x", {"port": 1}, directory=tmp_path, prompts_path=tmp_path / "p.json")
