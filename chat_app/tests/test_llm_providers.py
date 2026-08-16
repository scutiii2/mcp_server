"""Provider-level tests: schema reshaping and availability checks.

No real OpenAI/Anthropic calls happen here - ``run_chat`` itself (the part
that actually talks to the API) isn't exercised; that would require either
a live key or mocking the SDK client deeply enough that the test stops
proving much. What's genuinely worth testing without any of that is each
provider's tool-schema reshaping and its ``is_available()`` check, since
those are the pieces the rest of the app (the /capabilities-style
dropdown, the router) actually depends on.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import URLError

import pytest

from chat_app.services.llm import claude_provider, cooldown, ollama_provider, openai_provider
from chat_app.services.llm.base import ModelOption


def _fake_tool():
    return SimpleNamespace(
        name="get_status_tool",
        description="Get the status of a resource.",
        inputSchema={"type": "object", "properties": {"resource_id": {"type": "string"}}},
    )


def test_openai_tool_schemas_use_function_parameters_shape():
    with patch("chat_app.services.llm.openai_provider.list_tools", return_value=[_fake_tool()]):
        schemas = openai_provider._tool_schemas()

    assert schemas == [
        {
            "type": "function",
            "name": "get_status_tool",
            "description": "Get the status of a resource.",
            "parameters": {"type": "object", "properties": {"resource_id": {"type": "string"}}},
        }
    ]


def test_claude_tool_schemas_use_input_schema_shape():
    with patch("chat_app.services.llm.claude_provider.list_tools", return_value=[_fake_tool()]):
        schemas = claude_provider._tool_schemas()

    assert schemas == [
        {
            "name": "get_status_tool",
            "description": "Get the status of a resource.",
            "input_schema": {"type": "object", "properties": {"resource_id": {"type": "string"}}},
        }
    ]


def test_openai_has_api_key_reflects_env_var(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert openai_provider.has_api_key() is False

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert openai_provider.has_api_key() is True


def test_claude_has_api_key_reflects_env_var(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert claude_provider.has_api_key() is False

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert claude_provider.has_api_key() is True


def test_openai_is_available_false_without_key_even_with_no_cooldown(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert openai_provider.is_available() is False


def test_openai_is_available_false_during_cooldown_even_with_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert openai_provider.is_available() is True

    cooldown.start_cooldown("openai", seconds=30)
    assert openai_provider.is_available() is False


def test_claude_is_available_false_during_cooldown_even_with_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert claude_provider.is_available() is True

    cooldown.start_cooldown("claude", seconds=30)
    assert claude_provider.is_available() is False


def test_openai_rate_limit_error_starts_a_cooldown(monkeypatch):
    """NOT executed/verified in the sandbox this was built in - openai
    isn't installed there (no network access to pip install it). The
    RateLimitError constructor signature below matches openai>=1.x's
    documented shape (message, response, body) as of this writing; if the
    installed version differs, this is the first place to check on a
    failure. Run this locally once the real package is installed to
    confirm."""
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
    with patch("chat_app.services.llm.openai_provider._get_client", return_value=fake_client), \
         patch("chat_app.services.llm.openai_provider.list_tools", return_value=[]):
        with pytest.raises(RateLimitError):
            openai_provider.run_chat("hello", [])

    assert cooldown.is_in_cooldown("openai") is True
    assert cooldown.seconds_remaining("openai") <= 5


def test_ollama_tool_schemas_use_function_wrapped_shape():
    """Same Chat-Completions function-wrapped shape Ollama's OpenAI-compat
    layer speaks, distinct from openai_provider.py's newer Responses-API
    shape."""
    with patch("chat_app.services.llm.ollama_provider.list_tools", return_value=[_fake_tool()]):
        schemas = ollama_provider._tool_schemas()

    assert schemas == [
        {
            "type": "function",
            "function": {
                "name": "get_status_tool",
                "description": "Get the status of a resource.",
                "parameters": {"type": "object", "properties": {"resource_id": {"type": "string"}}},
            },
        }
    ]


def test_ollama_has_no_api_key_requirement():
    """No API key concept at all for a local, unauthenticated Ollama
    instance - always True, unlike every other provider here."""
    assert ollama_provider.has_api_key() is True
    assert ollama_provider.is_available() is True


def test_ollama_base_url_defaults_to_localhost(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    assert ollama_provider._base_url() == "http://localhost:11434/v1"


def test_ollama_base_url_reads_env_override(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://192.168.1.50:11434/v1")
    assert ollama_provider._base_url() == "http://192.168.1.50:11434/v1"


class _FakeTagsResponse:
    """Stand-in for the object urlopen()'s context manager yields -
    mirrors test_mcp_client.py's _FakeResponse."""

    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._payload


def _tags_payload(*names: str) -> bytes:
    return json.dumps({"models": [{"name": name, "model": name} for name in names]}).encode("utf-8")


def test_tags_url_strips_v1_suffix(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    assert ollama_provider._tags_url() == "http://localhost:11434/api/tags"


def test_tags_url_strips_v1_suffix_with_trailing_slash(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434/v1/")
    assert ollama_provider._tags_url() == "http://localhost:11434/api/tags"


def test_tags_url_leaves_a_base_without_v1_untouched(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    assert ollama_provider._tags_url() == "http://localhost:11434/api/tags"


def test_check_model_availability_skips_the_network_call_when_nothing_is_configured(monkeypatch):
    """No "providers.ollama.models" entries is a valid quiet deployment
    state, not something worth probing a host for."""
    monkeypatch.setattr(ollama_provider, "MODELS", [])

    with patch("chat_app.services.llm.ollama_provider.urlopen") as mock_urlopen:
        result = ollama_provider.check_model_availability()

    mock_urlopen.assert_not_called()
    assert result == ollama_provider.ModelAvailabilityCheck(reachable=True, reason=None, models={})


def test_check_model_availability_full_match(monkeypatch):
    monkeypatch.setattr(
        ollama_provider,
        "MODELS",
        [ModelOption(id="qwen2.5:7b", label="Qwen"), ModelOption(id="llama3.2:1b", label="Llama")],
    )
    response = _FakeTagsResponse(_tags_payload("qwen2.5:7b", "llama3.2:1b"))

    with patch("chat_app.services.llm.ollama_provider.urlopen", return_value=response):
        result = ollama_provider.check_model_availability()

    assert result.reachable is True
    assert result.reason is None
    assert result.models["qwen2.5:7b"] == ollama_provider.ModelAvailability(available=True, reason=None)
    assert result.models["llama3.2:1b"] == ollama_provider.ModelAvailability(available=True, reason=None)


def test_check_model_availability_partial_match(monkeypatch):
    """Some configured models are pulled, some aren't - the common case
    once a deployment lists more models than it's actually pulled."""
    monkeypatch.setattr(
        ollama_provider,
        "MODELS",
        [ModelOption(id="qwen2.5:7b", label="Qwen"), ModelOption(id="llama3.2:1b", label="Llama")],
    )
    response = _FakeTagsResponse(_tags_payload("qwen2.5:7b"))

    with patch("chat_app.services.llm.ollama_provider.urlopen", return_value=response):
        result = ollama_provider.check_model_availability()

    assert result.reachable is True
    assert result.reason is None
    assert result.models["qwen2.5:7b"] == ollama_provider.ModelAvailability(available=True, reason=None)
    assert result.models["llama3.2:1b"] == ollama_provider.ModelAvailability(available=False, reason="not_pulled")


def test_check_model_availability_connection_failure_fails_closed(monkeypatch):
    monkeypatch.setattr(ollama_provider, "MODELS", [ModelOption(id="qwen2.5:7b", label="Qwen")])

    with patch("chat_app.services.llm.ollama_provider.urlopen", side_effect=URLError("connection refused")):
        result = ollama_provider.check_model_availability()

    assert result.reachable is False
    assert result.reason == "unreachable"
    assert result.models["qwen2.5:7b"] == ollama_provider.ModelAvailability(available=False, reason="unreachable")


def test_check_model_availability_timeout_fails_closed(monkeypatch):
    monkeypatch.setattr(ollama_provider, "MODELS", [ModelOption(id="qwen2.5:7b", label="Qwen")])

    with patch("chat_app.services.llm.ollama_provider.urlopen", side_effect=TimeoutError("timed out")):
        result = ollama_provider.check_model_availability()

    assert result.reachable is False
    assert result.reason == "unreachable"
    assert result.models["qwen2.5:7b"].available is False
    assert result.models["qwen2.5:7b"].reason == "unreachable"


def test_check_model_availability_malformed_json_fails_closed(monkeypatch):
    monkeypatch.setattr(ollama_provider, "MODELS", [ModelOption(id="qwen2.5:7b", label="Qwen")])
    response = _FakeTagsResponse(b"not valid json")

    with patch("chat_app.services.llm.ollama_provider.urlopen", return_value=response):
        result = ollama_provider.check_model_availability()

    assert result.reachable is False
    assert result.reason == "unreachable"


def test_check_model_availability_unexpected_response_shape_fails_closed(monkeypatch):
    """Valid JSON, but not the documented {"models": [...]} shape (e.g. an
    unrelated endpoint answering on that port) - must degrade, not
    raise KeyError/TypeError out of the route this feeds."""
    monkeypatch.setattr(ollama_provider, "MODELS", [ModelOption(id="qwen2.5:7b", label="Qwen")])
    response = _FakeTagsResponse(json.dumps({"unexpected": "shape"}).encode("utf-8"))

    with patch("chat_app.services.llm.ollama_provider.urlopen", return_value=response):
        result = ollama_provider.check_model_availability()

    assert result.reachable is False
    assert result.reason == "unreachable"


def test_claude_run_chat_accumulates_total_tokens_across_tool_call_rounds(monkeypatch):
    """Each round of the tool-calling loop is a separately-billed API
    call, so the reported total is the sum of every round's usage, not
    just the final one."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    tool_use_block = SimpleNamespace(type="tool_use", name="get_status_tool", input={"resource_id": "web-1"}, id="tool_1")
    round_one = SimpleNamespace(
        stop_reason="tool_use",
        content=[tool_use_block],
        usage=SimpleNamespace(input_tokens=100, output_tokens=20),
    )
    text_block = SimpleNamespace(type="text", text="web-1 is healthy.")
    round_two = SimpleNamespace(
        stop_reason="end_turn",
        content=[text_block],
        usage=SimpleNamespace(input_tokens=150, output_tokens=30),
    )
    fake_client = SimpleNamespace(messages=SimpleNamespace(create=Mock(side_effect=[round_one, round_two])))

    with patch("chat_app.services.llm.claude_provider._get_client", return_value=fake_client), \
         patch("chat_app.services.llm.claude_provider.list_tools", return_value=[]), \
         patch("chat_app.services.llm.claude_provider.call_tool", return_value="ok"):
        result = claude_provider.run_chat("how is web-1?", [])

    assert result.response == "web-1 is healthy."
    # (100 + 20) + (150 + 30) - both rounds counted, not just the final one.
    assert result.total_tokens == 300


def test_claude_run_chat_reports_total_tokens_on_a_single_round_too():
    response = SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text="hi")],
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )
    fake_client = SimpleNamespace(messages=SimpleNamespace(create=Mock(return_value=response)))

    with patch("chat_app.services.llm.claude_provider._get_client", return_value=fake_client), \
         patch("chat_app.services.llm.claude_provider.list_tools", return_value=[]):
        result = claude_provider.run_chat("hello", [])

    assert result.total_tokens == 15


def test_openai_run_chat_accumulates_total_tokens_across_tool_call_rounds(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    function_call = SimpleNamespace(
        type="function_call", name="get_status_tool", arguments='{"resource_id": "web-1"}', call_id="call_1"
    )
    round_one = SimpleNamespace(output=[function_call], output_text="", usage=SimpleNamespace(total_tokens=120))
    round_two = SimpleNamespace(output=[], output_text="web-1 is healthy.", usage=SimpleNamespace(total_tokens=80))
    fake_client = SimpleNamespace(responses=SimpleNamespace(create=Mock(side_effect=[round_one, round_two])))

    with patch("chat_app.services.llm.openai_provider._get_client", return_value=fake_client), \
         patch("chat_app.services.llm.openai_provider.list_tools", return_value=[]), \
         patch("chat_app.services.llm.openai_provider.call_tool", return_value="ok"):
        result = openai_provider.run_chat("how is web-1?", [])

    assert result.response == "web-1 is healthy."
    assert result.total_tokens == 200


def test_openai_run_chat_total_tokens_is_none_when_usage_missing(monkeypatch):
    """Some SDK versions leave response.usage unset - that round
    contributes nothing countable rather than crashing or reporting 0."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    response = SimpleNamespace(output=[], output_text="ok", usage=None)
    fake_client = SimpleNamespace(responses=SimpleNamespace(create=Mock(return_value=response)))

    with patch("chat_app.services.llm.openai_provider._get_client", return_value=fake_client), \
         patch("chat_app.services.llm.openai_provider.list_tools", return_value=[]):
        result = openai_provider.run_chat("hi", [])

    assert result.total_tokens is None


def test_ollama_run_chat_accumulates_total_tokens_across_tool_call_rounds(monkeypatch):
    monkeypatch.setattr(ollama_provider, "MODELS", [ModelOption(id="llama3.2:1b", label="Llama")])
    monkeypatch.setattr(ollama_provider, "_DEFAULT_MODEL_ID", "llama3.2:1b")

    call = SimpleNamespace(id="call_1", function=SimpleNamespace(name="get_status_tool", arguments='{"resource_id": "web-1"}'))
    round_one_message = SimpleNamespace(content=None, tool_calls=[call])
    round_one = SimpleNamespace(choices=[SimpleNamespace(message=round_one_message)], usage=SimpleNamespace(total_tokens=90))
    round_two_message = SimpleNamespace(content="web-1 is healthy.", tool_calls=None)
    round_two = SimpleNamespace(choices=[SimpleNamespace(message=round_two_message)], usage=SimpleNamespace(total_tokens=60))
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(side_effect=[round_one, round_two])))
    )

    with patch("chat_app.services.llm.ollama_provider._get_client", return_value=fake_client), \
         patch("chat_app.services.llm.ollama_provider.list_tools", return_value=[]), \
         patch("chat_app.services.llm.ollama_provider.call_tool", return_value="ok"):
        result = ollama_provider.run_chat("how is web-1?", [])

    assert result.response == "web-1 is healthy."
    assert result.total_tokens == 150


def test_ollama_run_chat_total_tokens_is_none_when_usage_missing():
    """Ollama does not always populate usage, depending on version."""
    message = SimpleNamespace(content="ok", tool_calls=None)
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])  # no .usage at all
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(return_value=response))))

    with patch("chat_app.services.llm.ollama_provider._get_client", return_value=fake_client), \
         patch("chat_app.services.llm.ollama_provider.list_tools", return_value=[]):
        result = ollama_provider.run_chat("hi", [])

    assert result.total_tokens is None


def test_ollama_run_chat_requests_a_larger_context_window():
    """Ollama defaults to its own small context window (often 2048
    tokens) unless a request explicitly asks for more. A verbose tool
    result (e.g. a host-health dump with many disks/processes) can
    silently overflow that default on the follow-up summarization call,
    and a small model overflowing its context tends to emit an empty
    completion rather than an error - exactly the "no error, no text,
    but real tokens burned" failure this guards against."""
    message = SimpleNamespace(content="ok", tool_calls=None)
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    fake_create = Mock(return_value=response)
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create)))

    with patch("chat_app.services.llm.ollama_provider._get_client", return_value=fake_client), \
         patch("chat_app.services.llm.ollama_provider.list_tools", return_value=[]):
        ollama_provider.run_chat("hi", [])

    _, kwargs = fake_create.call_args
    assert kwargs["extra_body"] == {"options": {"num_ctx": ollama_provider._NUM_CTX}}


def test_ollama_usage_tokens_falls_back_to_prompt_plus_completion_when_total_missing():
    usage = SimpleNamespace(total_tokens=None, prompt_tokens=40, completion_tokens=10)
    assert ollama_provider._usage_tokens(usage) == 50


def test_ollama_usage_tokens_treats_all_zero_usage_as_uncountable():
    """A round that genuinely reports zero on every field is treated the
    same as a missing usage object, not as a real zero-token round."""
    usage = SimpleNamespace(total_tokens=0, prompt_tokens=0, completion_tokens=0)
    assert ollama_provider._usage_tokens(usage) is None


def test_ollama_run_chat_recursive_chain_disabled_makes_a_single_round():
    """Default behavior (recursive_chain unset/False) must be unchanged:
    exactly one API call, no refinement round appended."""
    message = SimpleNamespace(content="ok", tool_calls=None)
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    fake_create = Mock(return_value=response)
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create)))

    with patch("chat_app.services.llm.ollama_provider._get_client", return_value=fake_client), \
         patch("chat_app.services.llm.ollama_provider.list_tools", return_value=[]):
        result = ollama_provider.run_chat("hi", [])

    assert result.response == "ok"
    assert fake_create.call_count == 1


def test_ollama_run_chat_recursive_chain_runs_a_refinement_round_then_converges(monkeypatch):
    """recursive_chain=True asks the model to double-check its own answer.
    When the refinement round repeats the same answer, that's convergence
    - stop there instead of burning the rest of the round budget."""
    monkeypatch.setattr(
        ollama_provider, "MODELS", [ModelOption(id="phi4-mini:latest", label="Phi 4 Mini", recursive_chain=True)]
    )
    monkeypatch.setattr(ollama_provider, "_DEFAULT_MODEL_ID", "phi4-mini:latest")

    first = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Draft answer.", tool_calls=None))])
    second = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Draft answer.", tool_calls=None))])
    fake_create = Mock(side_effect=[first, second])
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create)))

    with patch("chat_app.services.llm.ollama_provider._get_client", return_value=fake_client), \
         patch("chat_app.services.llm.ollama_provider.list_tools", return_value=[]):
        result = ollama_provider.run_chat("hi", [])

    assert result.response == "Draft answer."
    assert fake_create.call_count == 2


def test_ollama_run_chat_recursive_chain_caps_at_max_refinement_rounds(monkeypatch):
    """An answer that keeps changing every round must not loop forever -
    it stops after ollama_provider._MAX_RECURSIVE_CHAIN_ROUNDS refinement
    rounds and returns whatever the last round produced."""
    monkeypatch.setattr(
        ollama_provider, "MODELS", [ModelOption(id="phi4-mini:latest", label="Phi 4 Mini", recursive_chain=True)]
    )
    monkeypatch.setattr(ollama_provider, "_DEFAULT_MODEL_ID", "phi4-mini:latest")

    def _round(text):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text, tool_calls=None))])

    # 1 initial round + _MAX_RECURSIVE_CHAIN_ROUNDS refinement rounds, each
    # producing a different answer so convergence never kicks in early.
    total_rounds = 1 + ollama_provider._MAX_RECURSIVE_CHAIN_ROUNDS
    responses = [_round(f"answer v{i}") for i in range(total_rounds)]
    fake_create = Mock(side_effect=responses)
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create)))

    with patch("chat_app.services.llm.ollama_provider._get_client", return_value=fake_client), \
         patch("chat_app.services.llm.ollama_provider.list_tools", return_value=[]):
        result = ollama_provider.run_chat("hi", [])

    assert result.response == f"answer v{total_rounds - 1}"
    assert fake_create.call_count == total_rounds


def test_ollama_run_chat_recursive_chain_is_resolved_per_selected_model(monkeypatch):
    """Two configured models, only one with recursive_chain=True - picking
    the plain model must not trigger any refinement round."""
    monkeypatch.setattr(
        ollama_provider,
        "MODELS",
        [
            ModelOption(id="llama3.2:1b", label="Llama", recursive_chain=False),
            ModelOption(id="phi4-mini:latest", label="Phi 4 Mini", recursive_chain=True),
        ],
    )
    message = SimpleNamespace(content="plain answer", tool_calls=None)
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    fake_create = Mock(return_value=response)
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create)))

    with patch("chat_app.services.llm.ollama_provider._get_client", return_value=fake_client), \
         patch("chat_app.services.llm.ollama_provider.list_tools", return_value=[]):
        result = ollama_provider.run_chat("hi", [], model="llama3.2:1b")

    assert result.response == "plain answer"
    assert fake_create.call_count == 1


def test_ollama_not_in_automatic_order():
    """The one behavioral guarantee this provider's whole design rests
    on - see its module docstring and router.py's comment on
    AUTOMATIC_ORDER for why a small local model must never be silently
    picked for a real question."""
    from chat_app.services.llm import router

    assert "ollama" not in router.AUTOMATIC_ORDER
    assert "ollama" in router._PROVIDERS  # still registered - manually selectable