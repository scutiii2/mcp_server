"""llm_config.tiers(): reads a gateway block's optional `models` map."""

from __future__ import annotations

import pytest

from src.llm import llm_config


def _use(monkeypatch, block):
    monkeypatch.setattr(llm_config, "_config", {"anthropic": {"claude": block}})


def test_tiers_are_returned_in_ladder_order_with_trimmed_use_for(monkeypatch):
    _use(monkeypatch, {"models": {
        "heavy": {"id": "opus", "use_for": "hard"},
        "light": {"id": "haiku", "use_for": "  quick  "},
    }})

    found = llm_config.tiers("anthropic", "claude")

    assert list(found) == ["light", "heavy"]
    assert found["light"] == llm_config.TierModel("haiku", "quick")


def test_no_models_means_no_tiers(monkeypatch):
    _use(monkeypatch, {"model": "sonnet"})
    assert llm_config.tiers("anthropic", "claude") == {}


def test_a_placeholder_id_is_resolved_from_the_environment(monkeypatch):
    monkeypatch.setenv("TIER_TEST_MODEL", "my-deployment")
    _use(monkeypatch, {"models": {"standard": {"id": "{TIER_TEST_MODEL}", "use_for": "most"}}})
    assert llm_config.tiers("anthropic", "claude")["standard"].id == "my-deployment"


def test_a_tier_whose_placeholder_is_unset_is_dropped(monkeypatch):
    monkeypatch.delenv("TIER_TEST_MODEL", raising=False)
    _use(monkeypatch, {"models": {
        "light": {"id": "{TIER_TEST_MODEL}", "use_for": "quick"},
        "heavy": {"id": "opus", "use_for": "hard"},
    }})
    assert list(llm_config.tiers("anthropic", "claude")) == ["heavy"]


def test_an_unknown_tier_name_is_rejected(monkeypatch):
    _use(monkeypatch, {"models": {"giant": {"id": "x", "use_for": "y"}}})
    with pytest.raises(ValueError, match="anthropic.claude.models.giant is not a tier"):
        llm_config.tiers("anthropic", "claude")


def test_a_tier_without_use_for_is_rejected(monkeypatch):
    _use(monkeypatch, {"models": {"light": {"id": "x"}}})
    with pytest.raises(ValueError, match="light.use_for must be a non-empty string"):
        llm_config.tiers("anthropic", "claude")


def test_a_tier_without_id_is_rejected(monkeypatch):
    _use(monkeypatch, {"models": {"light": {"use_for": "y"}}})
    with pytest.raises(ValueError, match="light.id must be a non-empty string"):
        llm_config.tiers("anthropic", "claude")


def test_models_must_be_an_object(monkeypatch):
    _use(monkeypatch, {"models": ["light"]})
    with pytest.raises(ValueError, match="models must be an object"):
        llm_config.tiers("anthropic", "claude")


def test_an_unknown_gateway_raises_key_error(monkeypatch):
    _use(monkeypatch, {})
    with pytest.raises(KeyError):
        llm_config.tiers("anthropic", "nope")
