"""agent_routing.py tests: the roster is built per turn from the registry
(self and other orchestrators excluded)."""

from __future__ import annotations

import asyncio

import pytest

from src.agents import agent_registry, agent_routing, agent_spec
from src.agents.agent_spec import AgentSpec, LlmSpec

AGENTS = [
    {"id": "orchestrator", "label": "Ember", "url": "u", "orchestrator": True, "focus": "coordination"},
    {"id": "calc", "label": "Calculator", "url": "u", "focus": "arithmetic and units"},
    {"id": "explainer", "label": "Explainer", "url": "u", "focus": "plain explanations"},
    {"id": "poet", "label": "Poet", "url": "u", "focus": "poems"},
    {"id": "blank", "label": "Blank", "url": "u"},
]


@pytest.fixture
def registry(monkeypatch):
    monkeypatch.setattr(agent_registry, "reload", lambda: None)
    monkeypatch.setattr(agent_registry, "_AGENTS", AGENTS)
    monkeypatch.setattr(agent_registry, "_AGENTS_BY_ID", {a["id"]: a for a in AGENTS})


def _use(monkeypatch, orchestrator=True):
    spec = AgentSpec(id="orchestrator", label="Ember", port=9100, llm=LlmSpec(provider="anthropic"),
                     orchestrator=orchestrator)
    monkeypatch.setattr(agent_spec, "_current", spec)


def test_specialists_exclude_self_and_orchestrators(registry, monkeypatch):
    _use(monkeypatch)
    assert [r.id for r in agent_routing.specialists()] == ["calc", "explainer", "poet", "blank"]


def test_non_orchestrator_has_no_roster(registry, monkeypatch):
    _use(monkeypatch, orchestrator=False)
    assert asyncio.run(agent_routing.roster_for()) == []


def test_orchestrator_roster_is_every_specialist(registry, monkeypatch):
    _use(monkeypatch)
    assert [r.id for r in asyncio.run(agent_routing.roster_for())] == ["calc", "explainer", "poet", "blank"]


def test_specialists_carry_their_published_tiers(monkeypatch):
    agents = [
        {"id": "orchestrator", "label": "Ember", "url": "u", "orchestrator": True},
        {"id": "calc", "label": "Calculator", "url": "u", "focus": "math", "tiers": [
            {"tier": "light", "id": "haiku", "use_for": "quick"},
            {"tier": "bogus", "id": "x", "use_for": "y"},
        ]},
        {"id": "poet", "label": "Poet", "url": "u", "focus": "poems"},
    ]
    monkeypatch.setattr(agent_registry, "reload", lambda: None)
    monkeypatch.setattr(agent_registry, "_AGENTS", agents)
    _use(monkeypatch)

    calc, poet = agent_routing.specialists()

    assert calc.tiers == (agent_spec.TierInfo("light", "haiku", "quick"),)
    assert poet.tiers == ()
