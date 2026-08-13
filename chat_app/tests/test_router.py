"""Router tests: the dispatch and availability logic that everything else
(the /api/providers route, the /api/chat route) relies on."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from chat_app.services.llm import cooldown, router
from chat_app.services.llm.base import ChatResult


def test_list_providers_reflects_availability(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    providers = {p["id"]: p for p in router.list_providers()}

    assert providers["openai"]["available"] is True
    assert providers["openai"]["label"] == "ChatGPT"
    assert providers["openai"]["reason"] is None
    assert providers["claude"]["available"] is False
    assert providers["claude"]["label"] == "Claude"
    assert providers["claude"]["reason"] == "missing_key"


def test_list_providers_includes_automatic_first_and_available_if_any_provider_is(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    providers = router.list_providers()

    assert providers[0]["id"] == "auto"
    assert providers[0]["label"] == "Automatic"
    assert providers[0]["available"] is True
    assert providers[0]["reason"] is None


def test_list_providers_includes_model_options_per_provider_but_not_automatic(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    providers = {p["id"]: p for p in router.list_providers()}

    assert providers["auto"]["models"] == []
    openai_model_ids = [m["id"] for m in providers["openai"]["models"]]
    assert "gpt-5.6-sol" in openai_model_ids
    claude_model_ids = [m["id"] for m in providers["claude"]["models"]]
    assert "claude-opus-4-8" in claude_model_ids
    assert "claude-sonnet-5" in claude_model_ids
    assert providers["claude"]["default_model_id"] == "claude-sonnet-5"


def test_list_providers_automatic_unavailable_when_nothing_is(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    providers = {p["id"]: p for p in router.list_providers()}

    assert providers["auto"]["available"] is False
    assert providers["auto"]["reason"] == "none_available"


def test_list_providers_automatic_ignores_providers_outside_automatic_order(monkeypatch):
    """Regression test: ollama_provider is always available() (no API
    key needed - see its module docstring) but deliberately excluded
    from AUTOMATIC_ORDER. Before this fix, list_providers() computed
    "Automatic"'s availability from every registered provider, so adding
    ollama would have made "auto" claim to be available even with every
    real provider unconfigured - even though _pick_automatic() would
    still raise, since it only ever loops over AUTOMATIC_ORDER."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    for var in ("AICORE_CLIENT_ID", "AICORE_CLIENT_SECRET", "AICORE_AUTH_URL", "AICORE_BASE_URL"):
        monkeypatch.delenv(var, raising=False)

    providers = {p["id"]: p for p in router.list_providers()}

    assert providers["ollama"]["available"] is True  # confirms the premise of this test
    assert providers["auto"]["available"] is False
    assert providers["auto"]["reason"] == "none_available"


def test_list_providers_reports_rate_limited_reason(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cooldown.start_cooldown("openai", seconds=45)

    providers = {p["id"]: p for p in router.list_providers()}

    assert providers["openai"]["available"] is False
    assert providers["openai"]["reason"] == "rate_limited"
    assert 0 < providers["openai"]["cooldown_seconds_remaining"] <= 45


def test_run_chat_dispatches_to_requested_provider(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    expected = ChatResult(response="from claude", tools_used=[], provider_id="claude")

    with patch("chat_app.services.llm.claude_provider.run_chat", return_value=expected) as mock_run:
        result = router.run_chat("hello", [], "claude")

    assert result is expected
    mock_run.assert_called_once_with("hello", [], None)


def test_run_chat_forwards_model_id_to_manually_selected_provider(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    expected = ChatResult(response="from claude opus", tools_used=[], provider_id="claude")

    with patch("chat_app.services.llm.claude_provider.run_chat", return_value=expected) as mock_run:
        result = router.run_chat("hello", [], "claude", "claude-opus-4-8")

    assert result is expected
    mock_run.assert_called_once_with("hello", [], "claude-opus-4-8")


def test_run_chat_defaults_to_automatic_when_provider_not_specified(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    expected = ChatResult(response="from openai", tools_used=[], provider_id="openai")

    with patch("chat_app.services.llm.openai_provider.run_chat", return_value=expected) as mock_run:
        result = router.run_chat("hello", [], None)

    assert result is expected
    mock_run.assert_called_once_with("hello", [])


def test_run_chat_automatic_prefers_openai_when_both_available(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    expected = ChatResult(response="from openai", tools_used=[], provider_id="openai")

    with patch("chat_app.services.llm.openai_provider.run_chat", return_value=expected) as mock_openai, \
         patch("chat_app.services.llm.claude_provider.run_chat") as mock_claude:
        result = router.run_chat("hello", [], "auto")

    assert result is expected
    mock_openai.assert_called_once()
    mock_claude.assert_not_called()


def test_run_chat_automatic_falls_back_to_claude_when_openai_unavailable(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    expected = ChatResult(response="from claude", tools_used=[], provider_id="claude")

    with patch("chat_app.services.llm.claude_provider.run_chat", return_value=expected) as mock_run:
        result = router.run_chat("hello", [], "auto")

    assert result is expected
    mock_run.assert_called_once_with("hello", [])


def test_run_chat_automatic_falls_back_when_openai_is_cooling_down(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    cooldown.start_cooldown("openai", seconds=30)
    expected = ChatResult(response="from claude", tools_used=[], provider_id="claude")

    with patch("chat_app.services.llm.claude_provider.run_chat", return_value=expected) as mock_run:
        result = router.run_chat("hello", [], "auto")

    assert result is expected
    mock_run.assert_called_once_with("hello", [])


def test_run_chat_automatic_raises_when_nothing_available(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    for var in ("AICORE_CLIENT_ID", "AICORE_CLIENT_SECRET", "AICORE_AUTH_URL", "AICORE_BASE_URL"):
        monkeypatch.delenv(var, raising=False)

    with pytest.raises(ValueError, match="No provider is currently available"):
        router.run_chat("hello", [], "auto")


def test_run_chat_rejects_unavailable_provider(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(ValueError, match="Claude is not configured"):
        router.run_chat("hello", [], "claude")


def test_run_chat_rejects_unknown_provider():
    with pytest.raises(ValueError, match="Unknown provider"):
        router.run_chat("hello", [], "some-made-up-provider")


def test_run_chat_rejects_provider_in_cooldown_even_with_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cooldown.start_cooldown("openai", seconds=30)

    with pytest.raises(ValueError, match="ChatGPT is rate-limited"):
        router.run_chat("hello", [], "openai")


def test_run_chat_cooldown_message_does_not_hide_missing_key(monkeypatch):
    """Missing key should win over 'not in cooldown' - there's nothing
    useful about telling someone to 'wait for the rate limit' when they
    never configured a key in the first place."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cooldown.start_cooldown("claude", seconds=30)

    with pytest.raises(ValueError, match="Claude is not configured"):
        router.run_chat("hello", [], "claude")