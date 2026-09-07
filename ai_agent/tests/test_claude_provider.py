"""claude_provider.py tests: schema reshaping, availability checks, the
rate-limit -> cooldown path, and the cancellation checkpoint - mirroring
chat_app's own (now-migrated) test_llm_providers.py convention: no real
Anthropic call happens here, run_chat's SDK client is always mocked.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from src.llm import cancellation, cooldown
from src.llm.base import ChatCancelled
from src.llm import claude_provider


@pytest.fixture(autouse=True)
def _reset_state():
    cooldown.reset()
    yield
    cooldown.reset()


def _fake_tool():
    return SimpleNamespace(
        name="get_status_tool",
        description="Get the status of a resource.",
        inputSchema={"type": "object", "properties": {"resource_id": {"type": "string"}}},
    )


def test_tool_schemas_use_input_schema_shape():
    with patch("src.llm.claude_provider.list_tools", return_value=[_fake_tool()]), \
         patch("src.llm.claude_provider.delegation.is_available", return_value=False):
        schemas = claude_provider._tool_schemas()

    assert schemas == [
        {
            "name": "get_status_tool",
            "description": "Get the status of a resource.",
            "input_schema": {"type": "object", "properties": {"resource_id": {"type": "string"}}},
        }
    ]


def test_tool_schemas_includes_delegate_tool_when_available():
    with patch("src.llm.claude_provider.list_tools", return_value=[]), \
         patch("src.llm.claude_provider.delegation.is_available", return_value=True), \
         patch("src.llm.claude_provider.delegation.tool_description", return_value="delegate away"):
        schemas = claude_provider._tool_schemas()

    assert schemas == [
        {
            "name": "delegate_to_agent",
            "description": "delegate away",
            "input_schema": claude_provider.delegation.TOOL_PARAMETERS,
        }
    ]


def test_tool_schemas_excludes_delegate_tool_when_unavailable():
    with patch("src.llm.claude_provider.list_tools", return_value=[]), \
         patch("src.llm.claude_provider.delegation.is_available", return_value=False):
        schemas = claude_provider._tool_schemas()

    assert schemas == []


def test_dispatch_routes_delegate_calls_to_delegation_and_others_to_call_tool():
    with patch("src.llm.claude_provider.delegation.call", return_value="delegated answer") as fake_delegate, \
         patch("src.llm.claude_provider.call_tool", return_value="tool result") as fake_call_tool:
        delegate_result = claude_provider._dispatch(
            "delegate_to_agent", {"agent_id": "openai-agent", "question": "hi"}, depth=1
        )
        other_result = claude_provider._dispatch("get_status_tool", {"resource_id": "x"}, depth=1)

    fake_delegate.assert_called_once_with("openai-agent", "hi", 1)
    fake_call_tool.assert_called_once_with("get_status_tool", {"resource_id": "x"})
    assert delegate_result == "delegated answer"
    assert other_result == "tool result"


def test_has_api_key_reflects_env_var(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert claude_provider.has_api_key() is False

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert claude_provider.has_api_key() is True


def test_is_available_false_during_cooldown_even_with_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert claude_provider.is_available() is True

    cooldown.start_cooldown("claude", seconds=30)
    assert claude_provider.is_available() is False


def test_rate_limit_error_starts_a_cooldown(monkeypatch):
    import httpx
    from anthropic import RateLimitError

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    fake_response = httpx.Response(
        429,
        headers={"retry-after": "5"},
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
    )
    error = RateLimitError("rate limited", response=fake_response, body=None)

    fake_client = SimpleNamespace(messages=SimpleNamespace(create=lambda **_: (_ for _ in ()).throw(error)))
    with patch("src.llm.claude_provider._get_client", return_value=fake_client), \
         patch("src.llm.claude_provider.list_tools", return_value=[]):
        with pytest.raises(RateLimitError):
            claude_provider.run_chat("hello", [])

    assert cooldown.is_in_cooldown("claude") is True
    assert cooldown.seconds_remaining("claude") <= 5


def _usage(input_tokens=10, output_tokens=5):
    return SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)


def test_run_chat_dispatches_a_delegate_tool_use_block_through_delegation(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    tool_use_block = SimpleNamespace(
        type="tool_use", id="call-1", name="delegate_to_agent",
        input={"agent_id": "openai-agent", "question": "sub-question"},
    )
    round_one = SimpleNamespace(
        usage=_usage(), stop_reason="tool_use", content=[tool_use_block],
    )
    final_block = SimpleNamespace(type="text", text="final answer")
    round_two = SimpleNamespace(usage=_usage(), stop_reason="end_turn", content=[final_block])

    fake_client = SimpleNamespace(messages=SimpleNamespace(create=Mock(side_effect=[round_one, round_two])))
    with patch("src.llm.claude_provider._get_client", return_value=fake_client), \
         patch("src.llm.claude_provider.list_tools", return_value=[]), \
         patch("src.llm.claude_provider.delegation.is_available", return_value=True), \
         patch("src.llm.claude_provider.delegation.call", return_value="the sub-agent's answer") as fake_delegate:
        result = claude_provider.run_chat("hello", [], depth=1)

    fake_delegate.assert_called_once_with("openai-agent", "sub-question", 1)
    assert result.response == "final answer"
    assert result.tools_used == ["delegate_to_agent"]
    assert result.tool_calls[0].result == "the sub-agent's answer"


def test_run_chat_shows_a_failed_delegation_the_same_way_as_a_failed_tool_call(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    tool_use_block = SimpleNamespace(
        type="tool_use", id="call-1", name="delegate_to_agent",
        input={"agent_id": "nope", "question": "sub-question"},
    )
    round_one = SimpleNamespace(usage=_usage(), stop_reason="tool_use", content=[tool_use_block])
    final_block = SimpleNamespace(type="text", text="ok I tried")
    round_two = SimpleNamespace(usage=_usage(), stop_reason="end_turn", content=[final_block])

    fake_client = SimpleNamespace(messages=SimpleNamespace(create=Mock(side_effect=[round_one, round_two])))
    with patch("src.llm.claude_provider._get_client", return_value=fake_client), \
         patch("src.llm.claude_provider.list_tools", return_value=[]), \
         patch("src.llm.claude_provider.delegation.is_available", return_value=True), \
         patch("src.llm.claude_provider.delegation.call", side_effect=ValueError("unknown agent_id 'nope'")):
        result = claude_provider.run_chat("hello", [], depth=1)

    assert "Tool 'delegate_to_agent' failed: unknown agent_id 'nope'" in result.tool_calls[0].result


def test_run_chat_raises_chat_cancelled_before_any_api_call_when_already_cancelled(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    cancellation.cancel("req-1")

    def _fail_if_called(**_):
        raise AssertionError("the API must not be called once cancellation is flagged")

    fake_client = SimpleNamespace(messages=SimpleNamespace(create=_fail_if_called))
    with patch("src.llm.claude_provider._get_client", return_value=fake_client), \
         patch("src.llm.claude_provider.list_tools", return_value=[]):
        with pytest.raises(ChatCancelled):
            claude_provider.run_chat("hello", [], request_id="req-1")

    cancellation.clear("req-1")
