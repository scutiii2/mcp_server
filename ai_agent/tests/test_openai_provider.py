"""openai_provider.py tests - see test_claude_provider.py's module
docstring for the conventions this mirrors. run_chat is async (see
test_anthropic_provider_streaming.py's module docstring for why these are
plain sync `def test_x():` wrapping `asyncio.run(...)` rather than
`@pytest.mark.asyncio`) and its final round streams through
client.responses.stream, mirroring anthropic_provider.run_chat's shape.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from src.llm import cancellation, cooldown, token_limits
from src.llm.base_provider import ChatCancelled
from src.llm import openai_provider


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch, tmp_path):
    # has_api_key()/get_client() are gateway-aware (see AI_AGENT_GATEWAY),
    # so a developer's real secret_llm.env pointing it at a non-default
    # gateway (e.g. "openrouter") must not leak into these tests, which
    # assume the default "gpt" gateway's GPT_API_KEY semantics.
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


def _fake_stream(delta_texts, final_response):
    """Builds an `async with client.responses.stream(...) as stream:` fake
    matching openai_provider.run_chat's streaming branch: async-iterable of
    `response.output_text.delta` events, then an awaited get_final_response().
    MagicMock (not SimpleNamespace) because dunders like __aenter__/__aiter__
    are looked up on the type, not the instance."""
    events = [SimpleNamespace(type="response.output_text.delta", delta=text) for text in delta_texts]

    async def _aiter():
        for event in events:
            yield event

    stream = MagicMock()
    stream.__aiter__ = Mock(return_value=_aiter())
    stream.get_final_response = AsyncMock(return_value=final_response)

    stream_cm = MagicMock()
    stream_cm.__aenter__ = AsyncMock(return_value=stream)
    stream_cm.__aexit__ = AsyncMock(return_value=False)
    return stream_cm


def test_run_interpret_uses_shared_output_cap(monkeypatch):
    monkeypatch.setenv("GPT_API_KEY", "sk-test")
    response = SimpleNamespace(output_text="ok", usage=SimpleNamespace(total_tokens=1, input_tokens=1))
    client = SimpleNamespace(responses=SimpleNamespace(create=Mock(return_value=response)))
    with patch("src.llm.openai_provider._get_sync_client", return_value=client), \
         patch("src.llm.openai_provider.token_limits.max_output_tokens", return_value=777):
        openai_provider.run_interpret("hello")

    assert client.responses.create.call_args.kwargs["max_output_tokens"] == 777


def test_run_interpret_rejects_context_before_calling_openai(monkeypatch):
    monkeypatch.setenv("GPT_API_KEY", "sk-test")
    client = SimpleNamespace(responses=SimpleNamespace(create=Mock()))
    with patch("src.llm.openai_provider._get_sync_client", return_value=client), \
         patch("src.llm.openai_provider.token_limits.enforce_context_limit", side_effect=token_limits.ContextLimitError("too large")):
        with pytest.raises(token_limits.ContextLimitError):
            openai_provider.run_interpret("hello")

    client.responses.create.assert_not_called()


def test_tool_schemas_use_function_parameters_shape():
    with patch("src.llm.openai_provider.list_tools", return_value=[_fake_tool()]), \
         patch("src.llm.openai_provider.delegation.is_available", return_value=False):
        schemas = openai_provider._tool_schemas()

    assert schemas == [
        {
            "type": "function",
            "name": "get_status_tool",
            "description": "Get the status of a resource.",
            "parameters": {"type": "object", "properties": {"resource_id": {"type": "string"}}},
            "display_label": None,
        }
    ]


def test_tool_schemas_includes_delegate_tool_when_available():
    with patch("src.llm.openai_provider.list_tools", return_value=[]), \
         patch("src.llm.openai_provider.delegation.is_available", return_value=True), \
         patch("src.llm.openai_provider.delegation.tool_description", return_value="delegate away"):
        schemas = openai_provider._tool_schemas()

    assert schemas == [
        {
            "type": "function",
            "name": "delegate_to_agent",
            "description": "delegate away",
            "parameters": openai_provider.delegation.TOOL_PARAMETERS,
            "display_label": None,
        }
    ]


def test_tool_schemas_excludes_delegate_tool_when_unavailable():
    with patch("src.llm.openai_provider.list_tools", return_value=[]), \
         patch("src.llm.openai_provider.delegation.is_available", return_value=False):
        schemas = openai_provider._tool_schemas()

    assert schemas == []


def test_dispatch_routes_delegate_calls_to_delegation_and_others_to_call_tool():
    with patch("src.llm.openai_provider.delegation.call", return_value="delegated answer") as fake_delegate, \
         patch("src.llm.openai_provider.call_tool", return_value="tool result") as fake_call_tool:
        delegate_result = openai_provider._dispatch(
            "delegate_to_agent", {"agent_id": "claude-agent", "question": "hi"}, depth=1
        )
        other_result = openai_provider._dispatch("get_status_tool", {"resource_id": "x"}, depth=1)

    fake_delegate.assert_called_once_with("claude-agent", "hi", 1)
    fake_call_tool.assert_called_once_with("get_status_tool", {"resource_id": "x"})
    assert delegate_result == "delegated answer"
    assert other_result == "tool result"


def test_has_api_key_reflects_env_var(monkeypatch):
    monkeypatch.delenv("GPT_API_KEY", raising=False)
    assert openai_provider.has_api_key() is False

    monkeypatch.setenv("GPT_API_KEY", "sk-test")
    assert openai_provider.has_api_key() is True


def test_is_available_false_during_cooldown_even_with_key(monkeypatch):
    monkeypatch.setenv("GPT_API_KEY", "sk-test")
    assert openai_provider.is_available() is True

    cooldown.start_cooldown("openai", seconds=30)
    assert openai_provider.is_available() is False


def test_rate_limit_error_starts_a_cooldown(monkeypatch):
    """NOT executed/verified in every sandbox - requires the openai
    package installed with network-independent SDK internals. The
    RateLimitError constructor signature below matches openai>=1.x's
    documented shape (message, response, body); if the installed version
    differs, this is the first place to check on a failure."""
    import httpx
    from openai import RateLimitError

    monkeypatch.setenv("GPT_API_KEY", "sk-test")
    fake_response = httpx.Response(
        429,
        headers={"retry-after": "5"},
        request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
    )
    error = RateLimitError("rate limited", response=fake_response, body=None)

    fake_client = SimpleNamespace(responses=SimpleNamespace(stream=Mock(side_effect=error)))
    with patch("src.llm.openai_provider._get_client", return_value=fake_client), \
         patch("src.llm.openai_provider.list_tools", return_value=[]):
        with pytest.raises(RateLimitError):
            asyncio.run(openai_provider.run_chat("hello", []))

    assert cooldown.is_in_cooldown("openai") is True
    assert cooldown.seconds_remaining("openai") <= 5


def test_run_chat_dispatches_a_delegate_function_call_through_delegation(monkeypatch):
    monkeypatch.setenv("GPT_API_KEY", "sk-test")

    function_call = SimpleNamespace(
        type="function_call", call_id="call-1", name="delegate_to_agent",
        arguments='{"agent_id": "claude-agent", "question": "sub-question"}',
    )
    round_one = SimpleNamespace(usage=SimpleNamespace(total_tokens=10), output=[function_call])
    round_two = SimpleNamespace(usage=SimpleNamespace(total_tokens=5), output=[], output_text="ignored")
    final_response = SimpleNamespace(usage=SimpleNamespace(total_tokens=2), output=[], output_text="final answer")

    fake_client = SimpleNamespace(
        responses=SimpleNamespace(
            stream=Mock(side_effect=[_fake_stream([], round_one), _fake_stream(["final answer"], final_response)]),
        )
    )
    with patch("src.llm.openai_provider._get_client", return_value=fake_client), \
         patch("src.llm.openai_provider.list_tools", return_value=[]), \
         patch("src.llm.openai_provider.delegation.is_available", return_value=True), \
         patch("src.llm.openai_provider.delegation.call", return_value="the sub-agent's answer") as fake_delegate:
        result = asyncio.run(openai_provider.run_chat("hello", [], depth=1))

    fake_delegate.assert_called_once_with("claude-agent", "sub-question", 1)
    assert result.response == "final answer"
    assert result.tools_used == ["delegate_to_agent"]
    assert result.tool_calls[0].result == "the sub-agent's answer"


def test_run_chat_shows_a_failed_delegation_the_same_way_as_a_failed_tool_call(monkeypatch):
    monkeypatch.setenv("GPT_API_KEY", "sk-test")

    function_call = SimpleNamespace(
        type="function_call", call_id="call-1", name="delegate_to_agent",
        arguments='{"agent_id": "nope", "question": "sub-question"}',
    )
    round_one = SimpleNamespace(usage=SimpleNamespace(total_tokens=10), output=[function_call])
    round_two = SimpleNamespace(usage=SimpleNamespace(total_tokens=5), output=[], output_text="ignored")
    final_response = SimpleNamespace(usage=SimpleNamespace(total_tokens=2), output=[], output_text="ok I tried")

    fake_client = SimpleNamespace(
        responses=SimpleNamespace(
            stream=Mock(side_effect=[_fake_stream([], round_one), _fake_stream(["ok I tried"], final_response)]),
        )
    )
    with patch("src.llm.openai_provider._get_client", return_value=fake_client), \
         patch("src.llm.openai_provider.list_tools", return_value=[]), \
         patch("src.llm.openai_provider.delegation.is_available", return_value=True), \
         patch("src.llm.openai_provider.delegation.call", side_effect=ValueError("unknown agent_id 'nope'")):
        result = asyncio.run(openai_provider.run_chat("hello", [], depth=1))

    assert "Tool 'delegate_to_agent' failed: unknown agent_id 'nope'" in result.tool_calls[0].result


def test_run_chat_raises_chat_cancelled_before_any_api_call_when_already_cancelled(monkeypatch):
    monkeypatch.setenv("GPT_API_KEY", "sk-test")
    cancellation.cancel("req-1")

    async def _fail_if_called(**_):
        raise AssertionError("the API must not be called once cancellation is flagged")

    fake_client = SimpleNamespace(responses=SimpleNamespace(create=_fail_if_called))
    with patch("src.llm.openai_provider._get_client", return_value=fake_client), \
         patch("src.llm.openai_provider.list_tools", return_value=[]):
        with pytest.raises(ChatCancelled):
            asyncio.run(openai_provider.run_chat("hello", [], request_id="req-1"))

    cancellation.clear("req-1")


def test_run_chat_emits_step_events_around_a_tool_call(monkeypatch):
    monkeypatch.setenv("GPT_API_KEY", "sk-test")

    async def _run():
        events = []

        async def on_event(event):
            events.append(event)

        function_call = SimpleNamespace(
            type="function_call", call_id="call-1", name="tool_srv_listApps", arguments="{}",
        )
        round_one = SimpleNamespace(usage=SimpleNamespace(total_tokens=10), output=[function_call])
        round_two = SimpleNamespace(usage=SimpleNamespace(total_tokens=5), output=[], output_text="ignored")
        final_response = SimpleNamespace(usage=SimpleNamespace(total_tokens=2), output=[], output_text="Hello world")

        fake_client = SimpleNamespace(
            responses=SimpleNamespace(
                stream=Mock(side_effect=[_fake_stream([], round_one), _fake_stream(["Hello", " world"], final_response)]),
            )
        )
        with patch("src.llm.openai_provider._get_client", return_value=fake_client), \
             patch("src.llm.openai_provider._dispatch", return_value="2 apps running"), \
             patch("src.llm.openai_provider.list_tools", return_value=[]):
            return await openai_provider.run_chat("status?", [], on_event=on_event), events

    result, events = asyncio.run(_run())

    assert result.response == "Hello world"
    step_starts = [e for e in events if e["type"] == "step_start"]
    step_ends = [e for e in events if e["type"] == "step_end"]
    tokens = [e for e in events if e["type"] == "token"]
    assert step_starts and step_starts[0]["tool"] == "tool_srv_listApps"
    assert step_ends and step_ends[0]["ok"] is True
    assert [t["text"] for t in tokens] == ["Hello", " world"]


def test_output_items_are_resent_without_sdk_only_fields():
    class Parsed:
        def model_dump(self, exclude_none=False):
            return {
                "type": "function_call", "call_id": "c1", "name": "t", "arguments": "{}",
                "parsed_arguments": {"x": 1},
                "extra": [{"parsed": None, "text": "hi"}],
            }

    plain = SimpleNamespace(type="reasoning")
    items = openai_provider._output_as_input_items([Parsed(), plain])

    assert items[0] == {"type": "function_call", "call_id": "c1", "name": "t", "arguments": "{}", "extra": [{"text": "hi"}]}
    assert items[1] is plain
