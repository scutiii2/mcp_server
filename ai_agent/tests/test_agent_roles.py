"""agent_roles.py tests: role resolution (including the fail-loud paths)
and SYSTEM_PROMPT composition.

ROLE_ID/SYSTEM_PROMPT are resolved once at import time, but tests don't
re-import the module fresh via importlib.reload() to exercise that: reload()
re-executes the module body top to bottom, which would re-run the
_CONFIG_PATH = Path(...) assignment and clobber the _config_file fixture's
monkeypatch of _CONFIG_PATH before _resolve()/_compose_system_prompt() ever
ran - the reloaded module would just go back to reading the real
configs/config_ai_agent_roles.json instead of the fixture's tmp_path file.
Calling agent_roles._resolve() and agent_roles._compose_system_prompt(...)
directly on the already-imported module sidesteps that: the monkeypatched
_CONFIG_PATH stays in effect for the whole test. Same underlying reasoning
as test_agent_config.py's tests calling _resolve() directly rather than
reloading - reload() there breaks exception-class identity instead, but
either way the fix is the same: exercise the already-imported module's
functions directly rather than reloading it.
"""

from __future__ import annotations

import json

import pytest

_CONFIG = {
    "default_role": "generic",
    "tool_use_instructions": "Use tools. Confirm before destructive actions.",
    "roles": {
        "generic": {"label": "Generic Assistant", "persona": ""},
        "ops_specialist": {"label": "Ops Specialist", "persona": "You are an ops specialist."},
    },
}


@pytest.fixture(autouse=True)
def _config_file(monkeypatch, tmp_path):
    path = tmp_path / "config_ai_agent_roles.json"
    path.write_text(json.dumps(_CONFIG))

    from src.llm import agent_roles

    monkeypatch.setattr(agent_roles, "_CONFIG_PATH", path)
    monkeypatch.setattr(agent_roles, "_config", None)
    return path


def _clear_env(monkeypatch):
    monkeypatch.delenv("AI_AGENT_ROLE", raising=False)


def test_default_role_used_when_env_var_unset(monkeypatch):
    _clear_env(monkeypatch)

    from src.llm import agent_roles

    role_id, role = agent_roles._resolve()

    assert role_id == "generic"
    assert role["label"] == "Generic Assistant"


def test_env_var_overrides_default_role(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_AGENT_ROLE", "ops_specialist")

    from src.llm import agent_roles

    role_id, role = agent_roles._resolve()

    assert role_id == "ops_specialist"
    assert role["label"] == "Ops Specialist"


def test_unknown_role_env_var_fails_loudly(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_AGENT_ROLE", "bogus")

    from src.llm import agent_roles

    with pytest.raises(agent_roles.AgentRoleError, match="Unknown AI_AGENT_ROLE 'bogus'"):
        agent_roles._resolve()


def test_generic_role_system_prompt_is_tool_use_instructions_only(monkeypatch):
    _clear_env(monkeypatch)

    from src.llm import agent_roles

    role_id, role = agent_roles._resolve()
    system_prompt = agent_roles._compose_system_prompt(agent_roles._load(), role)

    assert role_id == "generic"
    assert system_prompt == "Use tools. Confirm before destructive actions."


def test_ops_specialist_role_prepends_persona(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_AGENT_ROLE", "ops_specialist")

    from src.llm import agent_roles

    role_id, role = agent_roles._resolve()
    system_prompt = agent_roles._compose_system_prompt(agent_roles._load(), role)

    assert role_id == "ops_specialist"
    assert system_prompt == (
        "You are an ops specialist.\n\nUse tools. Confirm before destructive actions."
    )


def test_system_prompt_for_appends_caveman_instructions_only_when_asked():
    from src.llm import agent_roles

    assert agent_roles.system_prompt_for(False) == agent_roles.SYSTEM_PROMPT
    on = agent_roles.system_prompt_for(True)
    assert on.startswith(agent_roles.SYSTEM_PROMPT)
    assert agent_roles.CAVEMAN_INSTRUCTIONS in on
