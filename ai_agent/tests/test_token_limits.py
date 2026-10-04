"""Persistent, provider-scoped token-limit policy tests."""

from __future__ import annotations

import json

import pytest

from src.llm import token_limits


@pytest.fixture
def configured_limits(tmp_path, monkeypatch):
    config_path = tmp_path / "config_token_limits.json"
    config_path.write_text(json.dumps({
        "default": {
            "max_output_tokens": 20,
            "max_context_tokens": 10,
            "max_tool_rounds": 3,
        },
        "anthropic": {"max_output_tokens": 30},
        "openai": {
            "gateways": {"ollama": {"max_context_tokens": 16_384}},
        },
    }))
    monkeypatch.setattr(token_limits, "_CONFIG_PATH", config_path)
    token_limits.reset_cache()
    return config_path


def test_provider_settings_merge_specific_values_over_default(configured_limits):
    assert token_limits.max_output_tokens("anthropic") == 30
    assert token_limits.max_context_tokens("anthropic") == 10


def test_max_tool_rounds_comes_from_config(configured_limits):
    assert token_limits.max_tool_rounds("anthropic") == 3


def test_gateway_override_applies_only_to_its_named_gateway(configured_limits):
    assert token_limits.max_context_tokens("openai", "ollama") == 16_384
    assert token_limits.max_context_tokens("openai", "gpt") == 10


def test_context_cap_rejects_an_oversized_request(configured_limits):
    with pytest.raises(token_limits.ContextLimitError):
        token_limits.enforce_context_limit("anthropic", [{"role": "user", "content": "x" * 100}])

