"""agent_config.py tests: provider/model resolution (including the
fail-loud paths) and the run_chat/cancel/status wrappers.

PROVIDER_ID/MODEL/_PROVIDER_MODULE are resolved once at import time, so
success-path tests re-import the module fresh (via importlib.reload)
after setting the env vars _resolve() reads. monkeypatch.setenv runs
before reload, so os.environ.setdefault (used when loading .env)
can never override it - but _SECRETS_PATH is ALSO redirected to a
guaranteed-nonexistent path for every test here, since a developer who
has already set up a real .env (a very normal thing to
have) would otherwise leak its AI_AGENT_PROVIDER/model/keys into these
"nothing configured" tests via that same setdefault.
"""

from __future__ import annotations

import importlib

import pytest

from src.llm.base_provider import ChatResult


@pytest.fixture(autouse=True)
def _no_real_secrets_file(monkeypatch, tmp_path):
    from src.agents import agent_config

    monkeypatch.setattr(agent_config, "_SECRETS_PATH", tmp_path / ".env")
    monkeypatch.setattr(agent_config.cancellation, "_cancelled", set())


def _clear_env(monkeypatch):
    # AI_AGENT_GATEWAY is also cleared: has_api_key() is gateway-aware, so a
    # developer's real .env pointing it at e.g. "openrouter" (with
    # OPENROUTER_API_KEY set) would otherwise leak a non-default gateway
    # selection into these "nothing configured" tests, same leak risk this
    # function already guards against for the provider/key vars below.
    for key in ("AI_AGENT_PROVIDER", "AI_AGENT_MODEL", "AI_AGENT_GATEWAY", "CLAUDE_API_KEY", "GPT_API_KEY"):
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

    from src.agents import agent_config

    with pytest.raises(agent_config.AgentConfigError, match="AI_AGENT_PROVIDER is not set"):
        agent_config._resolve()


def test_unknown_provider_fails_loudly(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_AGENT_PROVIDER", "bogus")

    from src.agents import agent_config

    with pytest.raises(agent_config.AgentConfigError, match="Unknown AI_AGENT_PROVIDER 'bogus'"):
        agent_config._resolve()


def test_laya_resolves_without_cloud_keys_or_cloud_provider_imports(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_AGENT_PROVIDER", "laya")
    from src.agents import agent_config

    original_import = agent_config.importlib.import_module
    imports = []

    def selected_import(name):
        imports.append(name)
        return original_import(name)

    monkeypatch.setattr(agent_config.importlib, "import_module", selected_import)
    provider, module = agent_config._resolve()
    assert provider == "laya"
    assert module.has_api_key() is True
    assert imports == ["src.llm.laya_provider"]


def test_provider_without_api_key_fails_loudly(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_AGENT_PROVIDER", "anthropic")

    from src.agents import agent_config

    with pytest.raises(agent_config.AgentConfigError, match="its API key is not configured"):
        agent_config._resolve()


def test_valid_anthropic_config_resolves(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_AGENT_PROVIDER", "anthropic")
    monkeypatch.setenv("CLAUDE_API_KEY", "test-key")

    from src.agents import agent_config

    reloaded = importlib.reload(agent_config)

    assert reloaded.PROVIDER_ID == "anthropic"
    assert reloaded.MODEL is None
    status = reloaded.status()
    assert status["provider_id"] == "anthropic"
    assert status["available"] is True
    assert status["reason"] is None


def test_blank_model_env_var_counts_as_unset(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_AGENT_PROVIDER", "anthropic")
    monkeypatch.setenv("CLAUDE_API_KEY", "test-key")
    monkeypatch.setenv("AI_AGENT_MODEL", "")

    from src.agents import agent_config

    reloaded = importlib.reload(agent_config)

    assert reloaded.MODEL is None


def test_run_chat_registers_and_clears_cancellation_around_the_call(monkeypatch):
    """Test that run_chat registers/clears cancellation around async provider calls."""
    import asyncio

    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_AGENT_PROVIDER", "anthropic")
    monkeypatch.setenv("CLAUDE_API_KEY", "test-key")

    from src.agents import agent_config

    reloaded = importlib.reload(agent_config)

    async def _run():
        calls = []
        monkeypatch.setattr(reloaded.cancellation, "register", lambda rid: calls.append(("register", rid)))
        monkeypatch.setattr(reloaded.cancellation, "clear", lambda rid: calls.append(("clear", rid)))

        captured_args = {}

        async def _fake_run_chat(question, history, model, enabled_extensions, request_id, depth, on_event=None, caveman=False):
            calls.append(("run_chat", request_id))
            captured_args["args"] = (question, history, model, enabled_extensions, request_id, depth)
            return ChatResult(response="fake-result")

        monkeypatch.setattr(reloaded._PROVIDER_MODULE, "run_chat", _fake_run_chat)

        result = await reloaded.run_chat("hi", [], ["reference"], "req-1", depth=1)

        assert result.response == "fake-result"
        assert calls == [("register", "req-1"), ("run_chat", "req-1"), ("clear", "req-1")]
        assert captured_args["args"] == ("hi", [], None, ["reference"], "req-1", 1)

    asyncio.run(_run())


def test_run_chat_defaults_depth_to_zero(monkeypatch):
    """Test that run_chat defaults depth parameter to 0."""
    import asyncio

    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_AGENT_PROVIDER", "anthropic")
    monkeypatch.setenv("CLAUDE_API_KEY", "test-key")

    from src.agents import agent_config

    reloaded = importlib.reload(agent_config)

    async def _run():
        captured = {}

        async def _fake_run_chat(question, history, model, enabled_extensions, request_id, depth, on_event=None, caveman=False):
            captured["depth"] = depth
            return ChatResult(response="fake-result")

        monkeypatch.setattr(reloaded._PROVIDER_MODULE, "run_chat", _fake_run_chat)

        await reloaded.run_chat("hi", [], [])

        assert captured["depth"] == 0

    asyncio.run(_run())


def test_run_chat_still_clears_cancellation_when_the_provider_raises(monkeypatch):
    """Test that run_chat clears cancellation even when the provider raises."""
    import asyncio

    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_AGENT_PROVIDER", "anthropic")
    monkeypatch.setenv("CLAUDE_API_KEY", "test-key")

    from src.agents import agent_config

    reloaded = importlib.reload(agent_config)

    async def _run():
        cleared = []
        monkeypatch.setattr(reloaded.cancellation, "clear", lambda rid: cleared.append(rid))

        async def _boom(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(reloaded._PROVIDER_MODULE, "run_chat", _boom)

        with pytest.raises(RuntimeError, match="boom"):
            await reloaded.run_chat("hi", [], [], "req-1")

        assert cleared == ["req-1"]

    asyncio.run(_run())


def test_cancel_delegates_to_cancellation_module(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_AGENT_PROVIDER", "anthropic")
    monkeypatch.setenv("CLAUDE_API_KEY", "test-key")

    from src.agents import agent_config

    reloaded = importlib.reload(agent_config)

    assert reloaded.cancel("req-1") is True
    assert reloaded.cancellation.is_cancelled("req-1") is True


def test_run_chat_awaits_async_provider_and_forwards_on_event(monkeypatch):
    """run_chat should be async and directly await async providers,
    forwarding the on_event callback."""
    import asyncio
    from unittest.mock import AsyncMock, patch

    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_AGENT_PROVIDER", "anthropic")
    monkeypatch.setenv("CLAUDE_API_KEY", "test-key")

    from src.agents import agent_config
    
    reloaded = importlib.reload(agent_config)

    async def _run():
        fake_result = ChatResult(response="hi")
        with patch.object(reloaded, "_PROVIDER_MODULE") as module:
            module.run_chat = AsyncMock(return_value=fake_result)
            events_seen = []

            async def on_event(e):
                events_seen.append(e)

            result = await reloaded.run_chat("q", [], [], on_event=on_event)

            assert result is fake_result
            module.run_chat.assert_awaited_once()
            assert module.run_chat.call_args.kwargs["on_event"] is on_event

    asyncio.run(_run())


def test_run_chat_falls_back_to_thread_for_sync_provider(monkeypatch):
    """run_chat should detect sync providers and run them in a worker thread
    via anyio.to_thread.run_sync to avoid blocking the event loop."""
    import asyncio
    from unittest.mock import patch

    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_AGENT_PROVIDER", "anthropic")
    monkeypatch.setenv("CLAUDE_API_KEY", "test-key")

    from src.agents import agent_config
    from src.llm.base_provider import ChatResult

    reloaded = importlib.reload(agent_config)

    async def _run():
        fake_result = ChatResult(response="sync result")
        sync_provider_called = []

        def _sync_run_chat(question, history, model, enabled_extensions, request_id, depth, caveman=False):
            sync_provider_called.append((question, history, model, enabled_extensions, request_id, depth))
            return fake_result

        with patch.object(reloaded, "_PROVIDER_MODULE") as module:
            # Make run_chat NOT async (plain function, not AsyncMock)
            module.run_chat = _sync_run_chat

            # on_event is silently dropped for sync providers (Phase 3 will fix this)
            result = await reloaded.run_chat("q", [], ["ext"], request_id="r1", depth=2, on_event=lambda e: None)

            assert result is fake_result
            assert len(sync_provider_called) == 1
            assert sync_provider_called[0] == ("q", [], None, ["ext"], "r1", 2)

    asyncio.run(_run())


def test_run_chat_still_registers_and_clears_cancellation_for_async_provider(monkeypatch):
    """Cancellation should wrap the entire async provider call."""
    import asyncio
    from unittest.mock import AsyncMock, patch

    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_AGENT_PROVIDER", "anthropic")
    monkeypatch.setenv("CLAUDE_API_KEY", "test-key")

    from src.agents import agent_config
    from src.llm.base_provider import ChatResult

    reloaded = importlib.reload(agent_config)

    async def _run():
        fake_result = ChatResult(response="hi")
        calls = []
        monkeypatch.setattr(reloaded.cancellation, "register", lambda rid: calls.append(("register", rid)))
        monkeypatch.setattr(reloaded.cancellation, "clear", lambda rid: calls.append(("clear", rid)))

        with patch.object(reloaded, "_PROVIDER_MODULE") as module:
            module.run_chat = AsyncMock(return_value=fake_result)

            result = await reloaded.run_chat("q", [], [], request_id="req-1")

            assert result is fake_result
            assert calls == [("register", "req-1"), ("clear", "req-1")]

    asyncio.run(_run())


def test_run_chat_still_clears_cancellation_when_async_provider_raises(monkeypatch):
    """Cancellation clear should run even if the provider raises."""
    import asyncio
    from unittest.mock import AsyncMock, patch

    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_AGENT_PROVIDER", "anthropic")
    monkeypatch.setenv("CLAUDE_API_KEY", "test-key")

    from src.agents import agent_config

    reloaded = importlib.reload(agent_config)

    async def _run():
        cleared = []
        monkeypatch.setattr(reloaded.cancellation, "clear", lambda rid: cleared.append(rid))

        async def _boom(*args, **kwargs):
            raise RuntimeError("boom")

        with patch.object(reloaded, "_PROVIDER_MODULE") as module:
            module.run_chat = _boom

            with pytest.raises(RuntimeError, match="boom"):
                await reloaded.run_chat("hi", [], [], "req-1")

            assert cleared == ["req-1"]

    asyncio.run(_run())


def test_run_chat_passes_the_resolved_tier_model_to_the_provider(monkeypatch):
    import asyncio

    from src.agents.agent_spec import TierInfo

    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_AGENT_PROVIDER", "anthropic")
    monkeypatch.setenv("CLAUDE_API_KEY", "test-key")

    from src.agents import agent_config

    reloaded = importlib.reload(agent_config)
    monkeypatch.setattr(reloaded.model_tiers, "own_tiers", lambda: [TierInfo("light", "haiku", "q"), TierInfo("heavy", "opus", "h")])
    seen = {}

    async def _fake_run_chat(question, history, model, enabled_extensions, request_id, depth, on_event=None, caveman=False):
        seen["model"] = model
        return ChatResult(response="x")

    monkeypatch.setattr(reloaded._PROVIDER_MODULE, "run_chat", _fake_run_chat)

    result = asyncio.run(reloaded.run_chat("hi", [], [], model_tier="heavy"))
    assert seen["model"] == "opus"
    assert (result.model_tier, result.model_note) == ("heavy", "")

    result = asyncio.run(reloaded.run_chat("hi", [], [], model_tier="standard"))
    assert seen["model"] == "haiku"
    assert result.model_tier == "light"
    assert "ran on light" in result.model_note


def test_run_chat_without_a_tier_keeps_the_pinned_model(monkeypatch):
    import asyncio

    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_AGENT_PROVIDER", "anthropic")
    monkeypatch.setenv("CLAUDE_API_KEY", "test-key")
    monkeypatch.setenv("AI_AGENT_MODEL", "pinned-model")

    from src.agents import agent_config

    reloaded = importlib.reload(agent_config)
    seen = {}

    async def _fake_run_chat(question, history, model, enabled_extensions, request_id, depth, on_event=None, caveman=False):
        seen["model"] = model
        return ChatResult(response="x")

    monkeypatch.setattr(reloaded._PROVIDER_MODULE, "run_chat", _fake_run_chat)

    result = asyncio.run(reloaded.run_chat("hi", [], []))
    assert seen["model"] == "pinned-model"
    assert result.model_tier is None


def _recall_setup(monkeypatch, *, recall_on):
    """A reloaded agent_config whose provider records the question it gets."""
    import dataclasses

    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_AGENT_PROVIDER", "anthropic")
    monkeypatch.setenv("CLAUDE_API_KEY", "test-key")

    from src.agents import agent_config

    reloaded = importlib.reload(agent_config)
    spec = dataclasses.replace(reloaded.agent_spec.current(), memory_recall=recall_on)
    monkeypatch.setattr(reloaded.agent_spec, "current", lambda: spec)
    searches = []
    monkeypatch.setattr(reloaded.memory_recall, "_search", lambda: searches.append(1) or "1 saved note(s):\nblock")
    seen = {}

    async def _fake_run_chat(question, history, model, enabled_extensions, request_id, depth, on_event=None, caveman=False):
        seen["question"] = question
        return ChatResult(response="ok")

    monkeypatch.setattr(reloaded._PROVIDER_MODULE, "run_chat", _fake_run_chat)
    return reloaded, searches, seen


def test_run_chat_gives_the_provider_the_recalled_notes_when_recall_is_on(monkeypatch):
    import asyncio

    reloaded, searches, seen = _recall_setup(monkeypatch, recall_on=True)
    attachment_questions = []
    real_bind = reloaded.delegation.bind_attachments
    monkeypatch.setattr(
        reloaded.delegation, "bind_attachments", lambda question, history: attachment_questions.append(question) or real_bind(question, history)
    )

    asyncio.run(reloaded.run_chat("hi", [], []))

    assert searches == [1]
    assert seen["question"].startswith(reloaded.memory_recall.LABEL)
    assert seen["question"].endswith("[User message]\nhi")
    assert attachment_questions == ["hi"]  # attachments still see the original question


def test_run_chat_leaves_the_question_alone_when_recall_is_off(monkeypatch):
    import asyncio

    reloaded, searches, seen = _recall_setup(monkeypatch, recall_on=False)

    asyncio.run(reloaded.run_chat("hi", [], []))

    assert searches == [] and seen["question"] == "hi"


def test_run_chat_does_not_recall_for_a_delegated_agent(monkeypatch):
    import asyncio

    reloaded, searches, seen = _recall_setup(monkeypatch, recall_on=True)

    asyncio.run(reloaded.run_chat("hi", [], [], depth=1))

    assert searches == [] and seen["question"] == "hi"


def _recall_chat(monkeypatch, recall_calls, cancel_first=False):
    """A reloaded run_chat with an entry agent that has memory_recall on and a fake provider."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_AGENT_PROVIDER", "anthropic")
    monkeypatch.setenv("CLAUDE_API_KEY", "test-key")

    from src.agents import agent_config

    reloaded = importlib.reload(agent_config)
    spec = SimpleNamespace(id="ember", memory_recall=True, llm=SimpleNamespace(max_effort=None))
    monkeypatch.setattr(reloaded.agent_spec, "current", lambda: spec)

    async def fake_recall(question, on_event=None):
        recall_calls.append(question)
        return "NOTES " + question

    monkeypatch.setattr(reloaded.memory_recall, "with_recall", fake_recall)
    provider = AsyncMock(return_value=ChatResult(response="ok"))
    monkeypatch.setattr(reloaded._PROVIDER_MODULE, "run_chat", provider)
    if cancel_first:
        monkeypatch.setattr(reloaded.cancellation, "is_cancelled", lambda rid: True)
    return reloaded, provider


def test_a_cancelled_request_does_not_run_the_recall_search(monkeypatch):
    import asyncio

    recall_calls = []
    reloaded, provider = _recall_chat(monkeypatch, recall_calls, cancel_first=True)

    with pytest.raises(reloaded.ChatCancelled):
        asyncio.run(reloaded.run_chat("hi", [], [], "req-1"))

    assert recall_calls == []
    provider.assert_not_awaited()


def test_recall_runs_once_per_turn_and_only_changes_the_provider_question(monkeypatch):
    import asyncio

    recall_calls = []
    reloaded, provider = _recall_chat(monkeypatch, recall_calls)

    asyncio.run(reloaded.run_chat("hi", [], [], "req-1"))

    assert recall_calls == ["hi"]
    provider.assert_awaited_once()
    assert provider.call_args.args[0] == "NOTES hi"


def test_a_delegated_turn_does_not_recall(monkeypatch):
    import asyncio

    recall_calls = []
    reloaded, provider = _recall_chat(monkeypatch, recall_calls)

    asyncio.run(reloaded.run_chat("hi", [], [], "req-1", depth=1))

    assert recall_calls == []
    assert provider.call_args.args[0] == "hi"
