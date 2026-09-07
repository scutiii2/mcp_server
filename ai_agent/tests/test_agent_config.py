"""agent_config.py tests: provider/model resolution (including the
fail-loud paths) and the run_chat/cancel/status wrappers.

PROVIDER_ID/MODEL/_PROVIDER_MODULE are resolved once at import time, so
success-path tests re-import the module fresh (via importlib.reload)
after setting the env vars _resolve() reads. monkeypatch.setenv runs
before reload, so os.environ.setdefault (used when loading secret_llm.env)
can never override it - but _SECRETS_PATH is ALSO redirected to a
guaranteed-nonexistent path for every test here, since a developer who
has already set up a real secrets/secret_llm.env (a very normal thing to
have) would otherwise leak its AI_AGENT_PROVIDER/model/keys into these
"nothing configured" tests via that same setdefault.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture(autouse=True)
def _no_real_secrets_file(monkeypatch, tmp_path):
    from src import agent_config

    monkeypatch.setattr(agent_config, "_SECRETS_PATH", tmp_path / "secret_llm.env")


def _clear_env(monkeypatch):
    for key in ("AI_AGENT_PROVIDER", "AI_AGENT_MODEL", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)


def test_missing_provider_env_var_fails_loudly(monkeypatch):
    # Calls _resolve() directly rather than importlib.reload(agent_config):
    # reload() re-executes the module body, which defines a NEW
    # AgentConfigError class object - pytest.raises(agent_config.
    # AgentConfigError, ...) captures the OLD (pre-reload) class
    # reference eagerly, so it would never match an exception raised
    # against the new one. Calling the already-imported module's own
    # _resolve() function keeps everything referencing one class.
    _clear_env(monkeypatch)

    from src import agent_config

    with pytest.raises(agent_config.AgentConfigError, match="AI_AGENT_PROVIDER is not set"):
        agent_config._resolve()


def test_unknown_provider_fails_loudly(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_AGENT_PROVIDER", "bogus")

    from src import agent_config

    with pytest.raises(agent_config.AgentConfigError, match="Unknown AI_AGENT_PROVIDER 'bogus'"):
        agent_config._resolve()


def test_provider_without_api_key_fails_loudly(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_AGENT_PROVIDER", "claude")

    from src import agent_config

    with pytest.raises(agent_config.AgentConfigError, match="its API key is not configured"):
        agent_config._resolve()


def test_valid_claude_config_resolves(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_AGENT_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    from src import agent_config

    reloaded = importlib.reload(agent_config)

    assert reloaded.PROVIDER_ID == "claude"
    assert reloaded.MODEL is None
    status = reloaded.status()
    assert status["provider_id"] == "claude"
    assert status["available"] is True
    assert status["reason"] is None


def test_blank_model_env_var_counts_as_unset(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_AGENT_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("AI_AGENT_MODEL", "")

    from src import agent_config

    reloaded = importlib.reload(agent_config)

    assert reloaded.MODEL is None


def test_run_chat_registers_and_clears_cancellation_around_the_call(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_AGENT_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    from src import agent_config

    reloaded = importlib.reload(agent_config)

    calls = []
    monkeypatch.setattr(reloaded.cancellation, "register", lambda rid: calls.append(("register", rid)))
    monkeypatch.setattr(reloaded.cancellation, "clear", lambda rid: calls.append(("clear", rid)))

    captured_args = {}

    def _fake_run_chat(question, history, model, enabled_extensions, request_id, depth):
        calls.append(("run_chat", request_id))
        captured_args["args"] = (question, history, model, enabled_extensions, request_id, depth)
        return "fake-result"

    monkeypatch.setattr(reloaded._PROVIDER_MODULE, "run_chat", _fake_run_chat)

    result = reloaded.run_chat("hi", [], ["reference"], "req-1", depth=1)

    assert result == "fake-result"
    assert calls == [("register", "req-1"), ("run_chat", "req-1"), ("clear", "req-1")]
    assert captured_args["args"] == ("hi", [], None, ["reference"], "req-1", 1)


def test_run_chat_defaults_depth_to_zero(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_AGENT_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    from src import agent_config

    reloaded = importlib.reload(agent_config)

    captured = {}

    def _fake_run_chat(question, history, model, enabled_extensions, request_id, depth):
        captured["depth"] = depth
        return "fake-result"

    monkeypatch.setattr(reloaded._PROVIDER_MODULE, "run_chat", _fake_run_chat)

    reloaded.run_chat("hi", [], [])

    assert captured["depth"] == 0


def test_run_chat_still_clears_cancellation_when_the_provider_raises(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_AGENT_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    from src import agent_config

    reloaded = importlib.reload(agent_config)

    cleared = []
    monkeypatch.setattr(reloaded.cancellation, "clear", lambda rid: cleared.append(rid))

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(reloaded._PROVIDER_MODULE, "run_chat", _boom)

    with pytest.raises(RuntimeError, match="boom"):
        reloaded.run_chat("hi", [], [], "req-1")

    assert cleared == ["req-1"]


def test_cancel_delegates_to_cancellation_module(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_AGENT_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    from src import agent_config

    reloaded = importlib.reload(agent_config)

    assert reloaded.cancel("req-1") is True
    assert reloaded.cancellation.is_cancelled("req-1") is True
