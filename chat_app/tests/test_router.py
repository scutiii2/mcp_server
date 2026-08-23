"""Router tests: the dispatch and availability logic that everything else
(the /api/providers route, the /api/chat route) relies on."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.services.llm import cooldown, router
from src.services.llm.base import ChatResult, ModelAvailability, ModelAvailabilityCheck, ModelOption


def _patch_run_chat(provider_id: str, **kwargs):
    """Patch the run_chat a provider will actually dispatch to.

    Patching ``src.services.llm.claude_provider.run_chat`` does NOT
    work here: each provider module builds its ``PROVIDER = ProviderSpec(
    run_chat=run_chat, ...)`` at import time, so the spec holds a direct
    reference to the original function. Rebinding the module attribute
    afterwards leaves that reference untouched, and the test sails past
    the mock into a real network call. Patch the attribute on the spec
    the router will use instead.
    """
    return patch.object(router._PROVIDERS[provider_id], "run_chat", **kwargs)


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


def test_list_providers_calls_ollama_check_models_hook_exactly_once_per_request(monkeypatch):
    """The hook feeds BOTH the provider-level and every per-model
    available/reason field - list_providers() must call it once and reuse
    the result, never once per field."""
    monkeypatch.setattr(
        router._PROVIDERS["ollama"],
        "models",
        [ModelOption(id="qwen2.5:7b", label="Qwen 2.5 7B (local)"), ModelOption(id="llama3.2:1b", label="Llama 3.2 1B (local)")],
    )
    fake_result = ModelAvailabilityCheck(
        reachable=True,
        reason=None,
        models={
            "qwen2.5:7b": ModelAvailability(available=True, reason=None),
            "llama3.2:1b": ModelAvailability(available=False, reason="not_pulled"),
        },
    )

    with patch.object(router._PROVIDERS["ollama"], "check_models", return_value=fake_result) as mock_check:
        providers = {p["id"]: p for p in router.list_providers()}

    mock_check.assert_called_once()
    ollama_models = {m["id"]: m for m in providers["ollama"]["models"]}
    assert ollama_models["qwen2.5:7b"] == {
        "id": "qwen2.5:7b",
        "label": "Qwen 2.5 7B (local)",
        "available": True,
        "reason": None,
    }
    assert ollama_models["llama3.2:1b"] == {
        "id": "llama3.2:1b",
        "label": "Llama 3.2 1B (local)",
        "available": False,
        "reason": "not_pulled",
    }
    assert providers["ollama"]["available"] is True
    assert providers["ollama"]["reason"] is None


def test_list_providers_folds_unreachable_ollama_into_provider_level_fields(monkeypatch):
    """A provider whose reachability can't be confirmed shouldn't claim to
    be available - "unreachable" must surface at the provider level too,
    not just per-model."""
    monkeypatch.setattr(router._PROVIDERS["ollama"], "models", [ModelOption(id="qwen2.5:7b", label="Qwen")])
    fake_result = ModelAvailabilityCheck(
        reachable=False,
        reason="unreachable",
        models={"qwen2.5:7b": ModelAvailability(available=False, reason="unreachable")},
    )

    with patch.object(router._PROVIDERS["ollama"], "check_models", return_value=fake_result):
        providers = {p["id"]: p for p in router.list_providers()}

    assert providers["ollama"]["available"] is False
    assert providers["ollama"]["reason"] == "unreachable"
    assert providers["ollama"]["models"][0]["available"] is False
    assert providers["ollama"]["models"][0]["reason"] == "unreachable"


def test_list_providers_rate_limited_reason_is_not_overwritten_by_unreachable(monkeypatch):
    """Reason precedence: rate_limited/missing_key are computed first and
    must win over "unreachable" - the hook's reason only fills in when
    nothing higher-priority already explains the provider being
    unavailable. cooldown is keyed by plain provider id string, so it can
    be exercised for ollama here even though ollama_provider itself never
    starts one."""
    monkeypatch.setattr(router._PROVIDERS["ollama"], "models", [ModelOption(id="qwen2.5:7b", label="Qwen")])
    cooldown.start_cooldown("ollama", seconds=30)
    fake_result = ModelAvailabilityCheck(
        reachable=False,
        reason="unreachable",
        models={"qwen2.5:7b": ModelAvailability(available=False, reason="unreachable")},
    )

    with patch.object(router._PROVIDERS["ollama"], "check_models", return_value=fake_result):
        providers = {p["id"]: p for p in router.list_providers()}

    assert providers["ollama"]["reason"] == "rate_limited"


def test_list_providers_non_ollama_models_are_always_available_regardless_of_hook_existing(monkeypatch):
    """openai/claude have no check_models hook (it's None) - every model
    must show available: true, reason: null unconditionally, keeping the
    shape uniform so the frontend never special-cases by provider id."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    providers = {p["id"]: p for p in router.list_providers()}

    assert providers["openai"]["models"], "test is meaningless if openai has no models to check"
    for model in providers["openai"]["models"]:
        assert model["available"] is True
        assert model["reason"] is None
    assert providers["claude"]["models"], "test is meaningless if claude has no models to check"
    for model in providers["claude"]["models"]:
        assert model["available"] is True
        assert model["reason"] is None


def test_run_chat_dispatches_to_requested_provider(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    expected = ChatResult(response="from claude", tools_used=[], provider_id="claude")

    with _patch_run_chat("claude", return_value=expected) as mock_run:
        result = router.run_chat("hello", [], "claude")

    assert result is expected
    mock_run.assert_called_once_with("hello", [], None, None, chat_id=None)


def test_run_chat_forwards_model_id_to_manually_selected_provider(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    expected = ChatResult(response="from claude opus", tools_used=[], provider_id="claude")

    with _patch_run_chat("claude", return_value=expected) as mock_run:
        result = router.run_chat("hello", [], "claude", "claude-opus-4-8")

    assert result is expected
    mock_run.assert_called_once_with("hello", [], "claude-opus-4-8", None, chat_id=None)


def test_run_chat_forwards_enabled_extensions_to_manually_selected_provider(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    expected = ChatResult(response="from claude", tools_used=[], provider_id="claude")

    with _patch_run_chat("claude", return_value=expected) as mock_run:
        result = router.run_chat("hello", [], "claude", "claude-opus-4-8", ["reference"])

    assert result is expected
    mock_run.assert_called_once_with("hello", [], "claude-opus-4-8", ["reference"], chat_id=None)


def test_run_chat_forwards_chat_id_to_manually_selected_provider(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    expected = ChatResult(response="from claude", tools_used=[], provider_id="claude")

    with _patch_run_chat("claude", return_value=expected) as mock_run:
        result = router.run_chat("hello", [], "claude", None, None, "chat-123")

    assert result is expected
    mock_run.assert_called_once_with("hello", [], None, None, chat_id="chat-123")


def test_run_chat_automatic_forwards_chat_id(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    expected = ChatResult(response="from openai", tools_used=[], provider_id="openai")

    with _patch_run_chat("openai", return_value=expected) as mock_run:
        result = router.run_chat("hello", [], "auto", chat_id="chat-123")

    assert result is expected
    mock_run.assert_called_once_with("hello", [], enabled_extensions=None, chat_id="chat-123")


def test_run_chat_defaults_to_automatic_when_provider_not_specified(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    expected = ChatResult(response="from openai", tools_used=[], provider_id="openai")

    with _patch_run_chat("openai", return_value=expected) as mock_run:
        result = router.run_chat("hello", [], None)

    assert result is expected
    mock_run.assert_called_once_with("hello", [], enabled_extensions=None, chat_id=None)


def test_run_chat_automatic_prefers_openai_when_both_available(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    expected = ChatResult(response="from openai", tools_used=[], provider_id="openai")

    with _patch_run_chat("openai", return_value=expected) as mock_openai, \
         _patch_run_chat("claude") as mock_claude:
        result = router.run_chat("hello", [], "auto")

    assert result is expected
    mock_openai.assert_called_once()
    mock_claude.assert_not_called()


def test_run_chat_automatic_falls_back_to_claude_when_openai_unavailable(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    expected = ChatResult(response="from claude", tools_used=[], provider_id="claude")

    with _patch_run_chat("claude", return_value=expected) as mock_run:
        result = router.run_chat("hello", [], "auto")

    assert result is expected
    mock_run.assert_called_once_with("hello", [], enabled_extensions=None, chat_id=None)


def test_run_chat_automatic_falls_back_when_openai_is_cooling_down(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    cooldown.start_cooldown("openai", seconds=30)
    expected = ChatResult(response="from claude", tools_used=[], provider_id="claude")

    with _patch_run_chat("claude", return_value=expected) as mock_run:
        result = router.run_chat("hello", [], "auto")

    assert result is expected
    mock_run.assert_called_once_with("hello", [], enabled_extensions=None, chat_id=None)


def test_run_chat_automatic_forwards_enabled_extensions(monkeypatch):
    """The filter must reach whichever provider Automatic resolves to,
    exactly like the manual-select path - Automatic only special-cases
    the model, not the extension filter."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    expected = ChatResult(response="from openai", tools_used=[], provider_id="openai")

    with _patch_run_chat("openai", return_value=expected) as mock_run:
        result = router.run_chat("hello", [], "auto", enabled_extensions=["reference"])

    assert result is expected
    mock_run.assert_called_once_with("hello", [], enabled_extensions=["reference"], chat_id=None)


def test_run_chat_automatic_raises_when_nothing_available(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

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
