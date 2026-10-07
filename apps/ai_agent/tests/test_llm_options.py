"""llm_options.py tests: per-agent knobs become provider kwargs, and a
parameter the model rejects is dropped (once, with a warning)."""

from __future__ import annotations

import logging

from src.agents.agent_spec import LlmSpec
from src.llm.llm_options import LlmOptions


def test_defaults_send_nothing_extra():
    options = LlmOptions("anthropic", "calc", LlmSpec(provider="anthropic"))
    assert options.extra_kwargs("m") == {}
    assert options.max_tokens(1000) == 1000
    assert options.max_tool_rounds(6) == 6


def test_anthropic_kwargs():
    llm = LlmSpec(provider="anthropic", temperature=0.0, reasoning_effort="high", max_tokens=4096, max_tool_rounds=3)
    options = LlmOptions("anthropic", "calc", llm)
    assert options.extra_kwargs("m") == {"temperature": 0.0, "output_config": {"effort": "high"}}
    assert options.max_tokens(1000) == 4096
    assert options.max_tool_rounds(6) == 3


def test_openai_kwargs():
    options = LlmOptions("openai", "calc", LlmSpec(provider="openai", temperature=0.7, reasoning_effort="low"))
    assert options.extra_kwargs("m") == {"temperature": 0.7, "reasoning": {"effort": "low"}}


def test_drop_rejected_drops_the_named_parameter_once(caplog):
    options = LlmOptions("anthropic", "calc", LlmSpec(provider="anthropic", temperature=0.5, reasoning_effort="high"))

    with caplog.at_level(logging.WARNING):
        assert options.drop_rejected("temperature: not supported for this model", "m") is True

    assert options.extra_kwargs("m") == {"output_config": {"effort": "high"}}
    assert "temperature" in caplog.text
    assert options.drop_rejected("output_config.effort: invalid", "m") is True
    assert options.extra_kwargs("m") == {}
    assert options.drop_rejected("messages: roles must alternate", "m") is False


def test_a_rejection_on_one_model_does_not_drop_the_option_for_another():
    options = LlmOptions("anthropic", "calc", LlmSpec(provider="anthropic", temperature=0.5, reasoning_effort="high"))

    assert options.drop_rejected("temperature: not supported", "model-a") is True

    assert options.extra_kwargs("model-a") == {"output_config": {"effort": "high"}}
    assert options.extra_kwargs("model-b") == {"temperature": 0.5, "output_config": {"effort": "high"}}
