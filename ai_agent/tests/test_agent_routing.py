"""agent_routing.py tests: roster built per turn from the registry (self
and other orchestrators excluded), the Laya shortlist above top_k, the
"auto" pick with its min_score threshold, and every fallback."""

from __future__ import annotations

import asyncio

import pytest

from src import agent_registry, agent_routing, agent_spec
from src.agent_spec import AgentSpec, LlmSpec, RoutingSpec

AGENTS = [
    {"id": "orchestrator", "label": "Ember", "url": "u", "orchestrator": True, "focus": "coordination"},
    {"id": "calc", "label": "Calculator", "url": "u", "focus": "arithmetic and units"},
    {"id": "explainer", "label": "Explainer", "url": "u", "focus": "plain explanations"},
    {"id": "poet", "label": "Poet", "url": "u", "focus": "poems"},
    {"id": "blank", "label": "Blank", "url": "u"},
]


class FakeRanker:
    def __init__(self, chosen=None, scores=None, error=None):
        self.chosen, self.scores, self.error, self.calls = chosen or [], scores, error, []

    def rank(self, question, options, k):
        self.calls.append((question, dict(options), k))
        if self.error:
            raise self.error
        return self.chosen[:k]

    def rank_with_scores(self, question, options, k):
        self.calls.append((question, dict(options), k))
        if self.error:
            raise self.error
        return self.chosen[:k], self.scores


@pytest.fixture
def registry(monkeypatch):
    monkeypatch.setattr(agent_registry, "reload", lambda: None)
    monkeypatch.setattr(agent_registry, "_AGENTS", AGENTS)
    monkeypatch.setattr(agent_registry, "_AGENTS_BY_ID", {a["id"]: a for a in AGENTS})


def _use(monkeypatch, orchestrator=True, **routing):
    spec = AgentSpec(id="orchestrator", label="Ember", port=9100, llm=LlmSpec(provider="anthropic"),
                     orchestrator=orchestrator, routing=RoutingSpec(**routing))
    monkeypatch.setattr(agent_spec, "_current", spec)


def test_specialists_exclude_self_and_orchestrators(registry, monkeypatch):
    _use(monkeypatch)
    assert [r.id for r in agent_routing.specialists()] == ["calc", "explainer", "poet", "blank"]


def test_non_orchestrator_has_no_roster(registry, monkeypatch):
    _use(monkeypatch, orchestrator=False)
    assert asyncio.run(agent_routing.roster_for("hi")) == []


def test_roster_without_laya_is_every_specialist(registry, monkeypatch):
    _use(monkeypatch, laya=False, top_k=1)
    assert len(asyncio.run(agent_routing.roster_for("hi"))) == 4


def test_roster_shortlist_keeps_chosen_plus_unfocused(registry, monkeypatch):
    _use(monkeypatch, laya=True, top_k=1)
    ranker = FakeRanker(chosen=["calc"])

    roster = asyncio.run(agent_routing.roster_for("what is 2+2", ranker))

    assert [r.id for r in roster] == ["calc", "blank"]
    question, options, k = ranker.calls[0]
    assert options == {"calc": "arithmetic and units", "explainer": "plain explanations", "poet": "poems"}
    assert k == 1


def test_roster_shortlist_skipped_at_or_below_top_k(registry, monkeypatch):
    _use(monkeypatch, laya=True, top_k=3)
    ranker = FakeRanker(chosen=["calc"])
    assert len(asyncio.run(agent_routing.roster_for("q", ranker))) == 4
    assert ranker.calls == []


def test_roster_falls_back_to_everyone_when_laya_fails(registry, monkeypatch):
    _use(monkeypatch, laya=True, top_k=1)
    roster = asyncio.run(agent_routing.roster_for("q", FakeRanker(error=ImportError("no laya"))))
    assert len(roster) == 4


def test_resolve_auto_picks_the_top_specialist(registry, monkeypatch):
    _use(monkeypatch, laya=True, allow_auto=True)
    entry = agent_routing.resolve_auto("explain gravity", FakeRanker(chosen=["explainer"], scores=[0.8]))
    assert entry.id == "explainer"


def test_resolve_auto_below_min_score_refuses(registry, monkeypatch):
    _use(monkeypatch, laya=True, allow_auto=True, min_score=0.5)
    with pytest.raises(ValueError, match="no specialist matches well enough"):
        agent_routing.resolve_auto("q", FakeRanker(chosen=["poet"], scores=[0.1]))


def test_resolve_auto_ignores_min_score_when_scores_are_missing(registry, monkeypatch):
    _use(monkeypatch, laya=True, allow_auto=True, min_score=0.5)
    assert agent_routing.resolve_auto("q", FakeRanker(chosen=["poet"], scores=None)).id == "poet"


def test_resolve_auto_reports_laya_failure(registry, monkeypatch):
    _use(monkeypatch, laya=True, allow_auto=True)
    with pytest.raises(ValueError, match="pick an agent_id explicitly"):
        agent_routing.resolve_auto("q", FakeRanker(error=RuntimeError("model load failed")))
