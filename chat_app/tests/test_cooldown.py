"""Tests for the cooldown tracker in isolation."""

from __future__ import annotations

from types import SimpleNamespace

from chat_app.services.llm import cooldown


def test_not_in_cooldown_by_default():
    assert cooldown.is_in_cooldown("openai") is False
    assert cooldown.seconds_remaining("openai") == 0.0


def test_start_cooldown_makes_it_active():
    cooldown.start_cooldown("openai", seconds=30)

    assert cooldown.is_in_cooldown("openai") is True
    assert 0 < cooldown.seconds_remaining("openai") <= 30


def test_cooldown_is_per_provider():
    cooldown.start_cooldown("openai", seconds=30)

    assert cooldown.is_in_cooldown("openai") is True
    assert cooldown.is_in_cooldown("claude") is False


def test_reset_clears_one_provider():
    cooldown.start_cooldown("openai", seconds=30)
    cooldown.start_cooldown("claude", seconds=30)

    cooldown.reset("openai")

    assert cooldown.is_in_cooldown("openai") is False
    assert cooldown.is_in_cooldown("claude") is True


def test_reset_with_no_args_clears_everything():
    cooldown.start_cooldown("openai", seconds=30)
    cooldown.start_cooldown("claude", seconds=30)

    cooldown.reset()

    assert cooldown.is_in_cooldown("openai") is False
    assert cooldown.is_in_cooldown("claude") is False


def test_extract_retry_after_seconds_from_header():
    error = SimpleNamespace(response=SimpleNamespace(headers={"retry-after": "42"}))
    assert cooldown.extract_retry_after_seconds(error) == 42.0


def test_extract_retry_after_seconds_missing_header():
    error = SimpleNamespace(response=SimpleNamespace(headers={}))
    assert cooldown.extract_retry_after_seconds(error) is None


def test_extract_retry_after_seconds_no_response_at_all():
    error = Exception("boom")
    assert cooldown.extract_retry_after_seconds(error) is None
