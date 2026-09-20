"""anthropic_provider.py tests: schema reshaping, availability checks, the
rate-limit -> cooldown path, and the cancellation checkpoint - mirroring
chat_app's own (now-migrated) test_llm_providers.py convention: no real
Anthropic call happens here, run_chat's SDK client is always mocked.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from src.llm import cancellation, cooldown, token_limits
from src.llm.base_provider import ChatCancelled
from src.llm import anthropic_provider


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch, tmp_path):
    # has_api_key()/get_client() are gateway-aware (see AI_AGENT_GATEWAY),
    # so a developer's real secret_llm.env pointing it at a non-default
    # gateway (e.g. "openrouter") must not leak into these tests, which
    # assume the default "claude" gateway's CLAUDE_API_KEY semantics.
    monkeypatch.delenv("AI_AGENT_GATEWAY", raising=False)
    cooldown.reset()
    yield
    cooldown.reset()


def _fake_tool():
    return SimpleNamespace(
        name="get_status_tool",
        description="Get the status of a resource.",
        inputSchema={"type": "object", "properties": {"resource_id": {"type": "string"}}},
    )


def test_run_interpret_uses_shared_output_cap(monkeypatch):
    monkeypatch.setenv("CLAUDE_API_KEY", "sk-test")
    response = SimpleNamespace(content=[], usage=_usage())
    client = SimpleNamespace(messages=SimpleNamespace(create=Mock(return_value=response)))
    with patch("src.llm.anthropic_provider._get_sync_client", return_value=client), \
         patch("src.llm.anthropic_provider.token_limits.max_output_tokens", return_value=777):
        anthropic_provider.run_interpret("hello")

    assert client.messages.create.call_args.kwargs["max_tokens"] == 777


def test_run_interpret_rejects_context_before_calling_anthropic(monkeypatch):
    monkeypatch.setenv("CLAUDE_API_KEY", "sk-test")
    client = SimpleNamespace(messages=SimpleNamespace(create=Mock()))
    with patch("src.llm.anthropic_provider._get_sync_client", return_value=client), \
         patch("src.llm.anthropic_provider.token_limits.enforce_context_limit", side_effect=token_limits.ContextLimitError("too large")):
        with pytest.raises(token_limits.ContextLimitError):
            anthropic_provider.run_interpret("hello")

    client.messages.create.assert_not_called()


def test_tool_schemas_use_input_schema_shape():
    with patch("src.llm.anthropic_provider.list_tools", return_value=[_fake_tool()]), \
         patch("src.llm.anthropic_provider.delegation.is_available", return_value=False):
        schemas = anthropic_provider._tool_schemas()

    assert schemas == [
        {
            "name": "get_status_tool",
            "description": "Get the status of a resource.",
            "input_schema": {"type": "object", "properties": {"resource_id": {"type": "string"}}},
            "display_label": None,
        }
    ]


def test_tool_schemas_includes_delegate_tool_when_available():
    with patch("src.llm.anthropic_provider.list_tools", return_value=[]), \
         patch("src.llm.anthropic_provider.delegation.is_available", return_value=True), \
         patch("src.llm.anthropic_provider.delegation.tool_description", return_value="delegate away"):
        schemas = anthropic_provider._tool_schemas()

    assert schemas == [
        {
            "name": "delegate_to_agent",
            "description": "delegate away",
            "input_schema": anthropic_provider.delegation.TOOL_PARAMETERS,
            "display_label": None,
        }
    ]


def test_tool_schemas_excludes_delegate_tool_when_unavailable():
    with patch("src.llm.anthropic_provider.list_tools", return_value=[]), \
         patch("src.llm.anthropic_provider.delegation.is_available", return_value=False):
        schemas = anthropic_provider._tool_schemas()

    assert schemas == []


def test_dispatch_routes_delegate_calls_to_delegation_and_others_to_call_tool():
    with patch("src.llm.anthropic_provider.delegation.call", return_value="delegated answer") as fake_delegate, \
         patch("src.llm.anthropic_provider.call_tool", return_value="tool result") as fake_call_tool:
        delegate_result = anthropic_provider._dispatch(
            "delegate_to_agent", {"agent_id": "openai-agent", "question": "hi"}, depth=1
        )
        other_result = anthropic_provider._dispatch("get_status_tool", {"resource_id": "x"}, depth=1)

    fake_delegate.assert_called_once_with("openai-agent", "hi", 1)
    fake_call_tool.assert_called_once_with("get_status_tool", {"resource_id": "x"})
    assert delegate_result == "delegated answer"
    assert other_result == "tool result"


def test_has_api_key_reflects_env_var(monkeypatch):
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)
    assert anthropic_provider.has_api_key() is False

    monkeypatch.setenv("CLAUDE_API_KEY", "sk-ant-test")
    assert anthropic_provider.has_api_key() is True


def test_is_available_false_during_cooldown_even_with_key(monkeypatch):
    monkeypatch.setenv("CLAUDE_API_KEY", "sk-ant-test")
    assert anthropic_provider.is_available() is True

    cooldown.start_cooldown("anthropic", seconds=30)
    assert anthropic_provider.is_available() is False


def test_rate_limit_error_starts_a_cooldown(monkeypatch):
    import httpx
    from anthropic import RateLimitError

    monkeypatch.setenv("CLAUDE_API_KEY", "sk-ant-test")
    fake_response = httpx.Response(
        429,
        headers={"retry-after": "5"},
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
    )
    error = RateLimitError("rate limited", response=fake_response, body=None)

    fake_client = SimpleNamespace(messages=SimpleNamespace(stream=Mock(side_effect=error)))
    with patch("src.llm.anthropic_provider._get_client", return_value=fake_client), \
         patch("src.llm.anthropic_provider.list_tools", return_value=[]):
        with pytest.raises(RateLimitError):
            asyncio.run(anthropic_provider.run_chat("hello", []))

    assert cooldown.is_in_cooldown("anthropic") is True
    assert cooldown.seconds_remaining("anthropic") <= 5


def _usage(input_tokens=10, output_tokens=5):
    return SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)


def _fake_async_iter(items):
    async def gen():
        for item in items:
            yield item
    return gen()


def _stream_cm(text_chunks, final_message=None, input_tokens=1, output_tokens=1):
    """A fake `client.messages.stream(...)` context manager - every run_chat
    round streams via `async with client.messages.stream(...)`. `final_message`
    is what get_final_message() returns (stop_reason/content/usage)."""
    if final_message is None:
        final_message = SimpleNamespace(
            usage=_usage(input_tokens, output_tokens), stop_reason="end_turn", content=[],
        )
    stream = SimpleNamespace(
        text_stream=_fake_async_iter(text_chunks),
        get_final_message=AsyncMock(return_value=final_message),
    )
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=stream)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def test_run_chat_dispatches_a_delegate_tool_use_block_through_delegation(monkeypatch):
    monkeypatch.setenv("CLAUDE_API_KEY", "sk-ant-test")

    tool_use_block = SimpleNamespace(
        type="tool_use", id="call-1", name="delegate_to_agent",
        input={"agent_id": "openai-agent", "question": "sub-question"},
    )
    round_one = SimpleNamespace(
        usage=_usage(), stop_reason="tool_use", content=[tool_use_block],
    )
    round_two = SimpleNamespace(usage=_usage(), stop_reason="end_turn", content=[])

    fake_client = SimpleNamespace(
        messages=SimpleNamespace(
            stream=Mock(side_effect=[_stream_cm([], round_one), _stream_cm(["final answer"], round_two)]),
        )
    )
    with patch("src.llm.anthropic_provider._get_client", return_value=fake_client), \
         patch("src.llm.anthropic_provider.list_tools", return_value=[]), \
         patch("src.llm.anthropic_provider.delegation.is_available", return_value=True), \
         patch("src.llm.anthropic_provider.delegation.call", return_value="the sub-agent's answer") as fake_delegate:
        result = asyncio.run(anthropic_provider.run_chat("hello", [], depth=1))

    fake_delegate.assert_called_once_with("openai-agent", "sub-question", 1)
    assert result.response == "final answer"
    assert result.tools_used == ["delegate_to_agent"]
    assert result.tool_calls[0].result == "the sub-agent's answer"


def test_run_chat_shows_a_failed_delegation_the_same_way_as_a_failed_tool_call(monkeypatch):
    monkeypatch.setenv("CLAUDE_API_KEY", "sk-ant-test")

    tool_use_block = SimpleNamespace(
        type="tool_use", id="call-1", name="delegate_to_agent",
        input={"agent_id": "nope", "question": "sub-question"},
    )
    round_one = SimpleNamespace(usage=_usage(), stop_reason="tool_use", content=[tool_use_block])
    round_two = SimpleNamespace(usage=_usage(), stop_reason="end_turn", content=[])

    fake_client = SimpleNamespace(
        messages=SimpleNamespace(
            stream=Mock(side_effect=[_stream_cm([], round_one), _stream_cm(["ok I tried"], round_two)]),
        )
    )
    with patch("src.llm.anthropic_provider._get_client", return_value=fake_client), \
         patch("src.llm.anthropic_provider.list_tools", return_value=[]), \
         patch("src.llm.anthropic_provider.delegation.is_available", return_value=True), \
         patch("src.llm.anthropic_provider.delegation.call", side_effect=ValueError("unknown agent_id 'nope'")):
        result = asyncio.run(anthropic_provider.run_chat("hello", [], depth=1))

    assert "Tool 'delegate_to_agent' failed: unknown agent_id 'nope'" in result.tool_calls[0].result


def test_run_interpret_works_with_a_plain_synchronous_client_no_await_needed(monkeypatch):
    # run_interpret's own client.messages.create(...) call is a plain,
    # non-`await`ed call - it must go through _get_sync_client(), not
    # run_chat's _get_client() (which now returns an AsyncAnthropic and
    # would hand this call site an unawaited coroutine instead of a
    # response). This fake client is deliberately a plain Mock/MagicMock,
    # not an AsyncMock - if run_interpret ever started calling
    # _get_client() (or otherwise expected an awaitable) again, `response`
    # below would be a MagicMock's return value passed straight into
    # `response.content`/`response.usage`, which would raise, not silently
    # pass.
    text_block = SimpleNamespace(type="text", text="the interpreted answer")
    fake_response = MagicMock(content=[text_block], usage=_usage(input_tokens=7, output_tokens=3))
    fake_client = Mock()
    fake_client.messages.create = Mock(return_value=fake_response)

    with patch("src.llm.anthropic_provider._get_sync_client", return_value=fake_client) as fake_get_sync_client, \
         patch("src.llm.anthropic_provider._get_client") as fake_get_client:
        result = anthropic_provider.run_interpret("summarize this")

    fake_get_sync_client.assert_called_once()
    fake_get_client.assert_not_called()
    fake_client.messages.create.assert_called_once()
    assert result.response == "the interpreted answer"
    assert result.total_tokens == 10
    assert result.context_tokens == 7
    assert result.provider_id == anthropic_provider.PROVIDER_ID


def test_run_chat_raises_chat_cancelled_before_any_api_call_when_already_cancelled(monkeypatch):
    monkeypatch.setenv("CLAUDE_API_KEY", "sk-ant-test")
    cancellation.cancel("req-1")

    async def _fail_if_called(**_):
        raise AssertionError("the API must not be called once cancellation is flagged")

    fake_client = SimpleNamespace(messages=SimpleNamespace(create=_fail_if_called))
    with patch("src.llm.anthropic_provider._get_client", return_value=fake_client), \
         patch("src.llm.anthropic_provider.list_tools", return_value=[]):
        with pytest.raises(ChatCancelled):
            asyncio.run(anthropic_provider.run_chat("hello", [], request_id="req-1"))

    cancellation.clear("req-1")
