"""openai_provider.py tests - see test_claude_provider.py's module
docstring for the conventions this mirrors.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from src.llm import cancellation, cooldown
from src.llm.base import ChatCancelled
from src.llm import openai_provider


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
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert openai_provider.has_api_key() is False

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert openai_provider.has_api_key() is True


def test_is_available_false_during_cooldown_even_with_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
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

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    fake_response = httpx.Response(
        429,
        headers={"retry-after": "5"},
        request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
    )
    error = RateLimitError("rate limited", response=fake_response, body=None)

    fake_client = SimpleNamespace(responses=SimpleNamespace(create=lambda **_: (_ for _ in ()).throw(error)))
    with patch("src.llm.openai_provider._get_client", return_value=fake_client), \
         patch("src.llm.openai_provider.list_tools", return_value=[]):
        with pytest.raises(RateLimitError):
            openai_provider.run_chat("hello", [])

    assert cooldown.is_in_cooldown("openai") is True
    assert cooldown.seconds_remaining("openai") <= 5


def test_run_chat_dispatches_a_delegate_function_call_through_delegation(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    function_call = SimpleNamespace(
        type="function_call", call_id="call-1", name="delegate_to_agent",
        arguments='{"agent_id": "claude-agent", "question": "sub-question"}',
    )
    round_one = SimpleNamespace(usage=SimpleNamespace(total_tokens=10), output=[function_call])
    round_two = SimpleNamespace(usage=SimpleNamespace(total_tokens=5), output=[], output_text="final answer")

    fake_client = SimpleNamespace(responses=SimpleNamespace(create=Mock(side_effect=[round_one, round_two])))
    with patch("src.llm.openai_provider._get_client", return_value=fake_client), \
         patch("src.llm.openai_provider.list_tools", return_value=[]), \
         patch("src.llm.openai_provider.delegation.is_available", return_value=True), \
         patch("src.llm.openai_provider.delegation.call", return_value="the sub-agent's answer") as fake_delegate:
        result = openai_provider.run_chat("hello", [], depth=1)

    fake_delegate.assert_called_once_with("claude-agent", "sub-question", 1)
    assert result.response == "final answer"
    assert result.tools_used == ["delegate_to_agent"]
    assert result.tool_calls[0].result == "the sub-agent's answer"


def test_run_chat_shows_a_failed_delegation_the_same_way_as_a_failed_tool_call(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    function_call = SimpleNamespace(
        type="function_call", call_id="call-1", name="delegate_to_agent",
        arguments='{"agent_id": "nope", "question": "sub-question"}',
    )
    round_one = SimpleNamespace(usage=SimpleNamespace(total_tokens=10), output=[function_call])
    round_two = SimpleNamespace(usage=SimpleNamespace(total_tokens=5), output=[], output_text="ok I tried")

    fake_client = SimpleNamespace(responses=SimpleNamespace(create=Mock(side_effect=[round_one, round_two])))
    with patch("src.llm.openai_provider._get_client", return_value=fake_client), \
         patch("src.llm.openai_provider.list_tools", return_value=[]), \
         patch("src.llm.openai_provider.delegation.is_available", return_value=True), \
         patch("src.llm.openai_provider.delegation.call", side_effect=ValueError("unknown agent_id 'nope'")):
        result = openai_provider.run_chat("hello", [], depth=1)

    assert "Tool 'delegate_to_agent' failed: unknown agent_id 'nope'" in result.tool_calls[0].result


def test_run_chat_raises_chat_cancelled_before_any_api_call_when_already_cancelled(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cancellation.cancel("req-1")

    def _fail_if_called(**_):
        raise AssertionError("the API must not be called once cancellation is flagged")

    fake_client = SimpleNamespace(responses=SimpleNamespace(create=_fail_if_called))
    with patch("src.llm.openai_provider._get_client", return_value=fake_client), \
         patch("src.llm.openai_provider.list_tools", return_value=[]):
        with pytest.raises(ChatCancelled):
            openai_provider.run_chat("hello", [], request_id="req-1")

    cancellation.clear("req-1")
