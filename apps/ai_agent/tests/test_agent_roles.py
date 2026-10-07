"""agent_roles.py tests: SYSTEM_PROMPT composition from an agent spec.

SYSTEM_PROMPT is built once at import time, so tests call
_compose_system_prompt() / system_prompt_for() directly with a spec
patched into agent_spec._current rather than reloading the module.
"""

from __future__ import annotations

from src.agents import agent_spec
from src.agents.agent_spec import AgentSpec, LlmSpec, RosterEntry
from src.llm import agent_roles


def _spec(**kwargs) -> AgentSpec:
    return AgentSpec(id="calc", label="Calculator", port=9103, llm=LlmSpec(provider="anthropic"), **kwargs)


def test_identity_uses_the_label_for_a_specialist():
    prompt = agent_roles._compose_system_prompt(_spec())

    assert prompt.startswith("Your name is Ember: Calculator, an AI Assistant.")


def test_identity_says_orchestrator_for_an_orchestrator():
    prompt = agent_roles._compose_system_prompt(_spec(orchestrator=True))

    assert prompt.startswith("Your name is Ember: Orchestrator, an AI Assistant.")


def test_prompt_orders_identity_persona_instructions():
    prompt = agent_roles._compose_system_prompt(_spec(persona="You are a precise mathematician.", instructions="Only use calc tools."))

    assert prompt.index("Your name is") < prompt.index("You are a precise mathematician.") < prompt.index("Only use calc tools.")
    assert agent_roles.DEFAULT_INSTRUCTIONS not in prompt


def test_empty_instructions_fall_back_to_the_default():
    prompt = agent_roles._compose_system_prompt(_spec(persona="P."))

    assert prompt.endswith(agent_roles.DEFAULT_INSTRUCTIONS)


def test_system_prompt_for_appends_caveman_instructions_only_when_asked():
    assert agent_roles.system_prompt_for(False) == agent_roles.SYSTEM_PROMPT
    on = agent_roles.system_prompt_for(True)
    assert on.startswith(agent_roles.SYSTEM_PROMPT)
    assert agent_roles.CAVEMAN_INSTRUCTIONS in on


def test_system_prompt_for_adds_the_roster_before_instructions(monkeypatch):
    monkeypatch.setattr(agent_spec, "_current", _spec(orchestrator=True))
    roster = [RosterEntry("calc", "Calculator", "Arithmetic."), RosterEntry("explainer", "Explainer", "")]

    prompt = agent_roles.system_prompt_for(roster=roster)

    assert "- calc - Calculator: Arithmetic." in prompt
    assert "- explainer - Explainer: (no focus given)" in prompt
    assert prompt.index("calc - Calculator") < prompt.index(agent_roles.DEFAULT_INSTRUCTIONS)


def test_system_prompt_for_without_roster_is_unchanged():
    assert agent_roles.system_prompt_for() == agent_roles.SYSTEM_PROMPT
