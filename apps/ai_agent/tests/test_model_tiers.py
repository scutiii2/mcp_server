"""model_tiers.py tests: a gateway's tiers cut to an agent's cap, resolving a
requested tier (exact, clamped, invalid), and the registry record round trip."""

from __future__ import annotations

import logging

import pytest

from src.agents import agent_spec
from src.agents.agent_spec import AgentSpec, LlmSpec, TierInfo
from src.llm import llm_config, model_tiers

LIGHT = TierInfo("light", "haiku", "quick")
STANDARD = TierInfo("standard", "sonnet", "most")
HEAVY = TierInfo("heavy", "opus", "hard")
ALL = [LIGHT, STANDARD, HEAVY]

GATEWAY = {"models": {
    "light": {"id": "haiku", "use_for": "quick"},
    "standard": {"id": "sonnet", "use_for": "most"},
    "heavy": {"id": "opus", "use_for": "hard"},
}}


def _gateway(monkeypatch, block=GATEWAY):
    monkeypatch.setattr(llm_config, "_config", {"anthropic": {"claude": block}})


def test_effective_tiers_without_a_cap_is_the_whole_gateway(monkeypatch):
    _gateway(monkeypatch)
    assert model_tiers.effective_tiers("anthropic", "claude", None, None) == ALL


def test_effective_tiers_are_cut_to_the_range(monkeypatch):
    _gateway(monkeypatch)
    assert model_tiers.effective_tiers("anthropic", "claude", "standard", None) == [STANDARD, HEAVY]
    assert model_tiers.effective_tiers("anthropic", "claude", None, "standard") == [LIGHT, STANDARD]
    assert model_tiers.effective_tiers("anthropic", "claude", "standard", "standard") == [STANDARD]


def test_effective_tiers_of_a_gateway_without_models_or_unknown_is_empty(monkeypatch):
    _gateway(monkeypatch, {"model": "sonnet"})
    assert model_tiers.effective_tiers("anthropic", "claude", None, None) == []
    assert model_tiers.effective_tiers("anthropic", "nope", None, None) == []


def test_a_cap_that_excludes_every_defined_tier_warns(monkeypatch, caplog):
    _gateway(monkeypatch, {"models": {"light": {"id": "haiku", "use_for": "quick"}}})
    with caplog.at_level(logging.WARNING, logger="src.llm.model_tiers"):
        assert model_tiers.effective_tiers("anthropic", "claude", "heavy", None) == []
    assert "no tier inside" in caplog.text


def test_resolve_without_a_request_uses_the_default_model():
    assert model_tiers.resolve(None, ALL, "default-model", "calc") == model_tiers.Resolution("default-model", None)


def test_resolve_an_available_tier_is_exact_and_silent():
    assert model_tiers.resolve("heavy", ALL, "default-model", "calc") == model_tiers.Resolution("opus", "heavy")


def test_resolve_above_the_range_clamps_down_with_a_note():
    result = model_tiers.resolve("heavy", [LIGHT, STANDARD], "default-model", "pdf-assistant")
    assert (result.model, result.tier) == ("sonnet", "standard")
    assert result.note == "heavy is not available for pdf-assistant; ran on standard"


def test_resolve_below_the_range_clamps_up():
    result = model_tiers.resolve("light", [STANDARD, HEAVY], "default-model", "reviewer")
    assert (result.model, result.tier) == ("sonnet", "standard")
    assert "ran on standard" in result.note


def test_resolve_a_tie_goes_to_the_weaker_tier():
    result = model_tiers.resolve("standard", [LIGHT, HEAVY], "default-model", "calc")
    assert result.tier == "light"


def test_resolve_with_no_effective_tiers_uses_the_default_silently():
    assert model_tiers.resolve("heavy", [], "default-model", "calc") == model_tiers.Resolution("default-model", None)


def test_resolve_an_invalid_name_uses_the_default_with_a_note():
    result = model_tiers.resolve("giant", ALL, "default-model", "calc")
    assert (result.model, result.tier) == ("default-model", None)
    assert "unknown model_tier 'giant'" in result.note


def test_records_round_trip_and_malformed_records_are_skipped():
    records = model_tiers.as_records(ALL)
    assert records[0] == {"tier": "light", "id": "haiku", "use_for": "quick"}
    assert model_tiers.from_records(records) == tuple(ALL)
    assert model_tiers.from_records([{"tier": "giant", "id": "x", "use_for": "y"}, {"tier": "light"}, "junk"]) == ()
    assert model_tiers.from_records(None) == ()


def _use_spec(monkeypatch, provider="anthropic", **llm):
    spec = AgentSpec(id="calc", label="Calc", port=9103, llm=LlmSpec(provider=provider, **llm))
    monkeypatch.setattr(agent_spec, "_current", spec)


def test_own_tiers_uses_this_agents_gateway_and_cap(monkeypatch):
    _gateway(monkeypatch)
    _use_spec(monkeypatch, max_tier="standard")
    monkeypatch.setenv("AI_AGENT_GATEWAY", "claude")
    assert model_tiers.own_tiers() == [LIGHT, STANDARD]


def test_own_tiers_falls_back_to_the_providers_default_gateway(monkeypatch):
    _gateway(monkeypatch)
    _use_spec(monkeypatch)
    monkeypatch.delenv("AI_AGENT_GATEWAY", raising=False)
    assert model_tiers.own_tiers() == ALL


def test_own_tiers_of_a_laya_agent_is_empty(monkeypatch):
    _use_spec(monkeypatch, provider="laya")
    assert model_tiers.own_tiers() == []
