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

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from chat_app.services.llm import claude_provider, cooldown, ollama_provider, openai_provider


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


def test_ollama_models_parsed_from_env():
    import os

    old = os.environ.get("OLLAMA_MODELS")
    try:
        os.environ["OLLAMA_MODELS"] = "llama3.2:1b=Tiny local,qwen2.5:3b=Bigger local"
        models = ollama_provider._parse_models_from_env()
    finally:
        if old is None:
            os.environ.pop("OLLAMA_MODELS", None)
        else:
            os.environ["OLLAMA_MODELS"] = old

    assert [m.id for m in models] == ["llama3.2:1b", "qwen2.5:3b"]
    assert [m.label for m in models] == ["Tiny local", "Bigger local"]


def test_ollama_models_parsed_preserves_the_tag_colon_in_model_id():
    """Regression test for the exact bug found while testing this
    provider: Ollama model IDs contain a colon themselves (name:tag), so
    a ":"-separated id/label format truncates "qwen2.5:3b" down to just
    "qwen2.5" and loses the tag - which then 404s against Ollama, since
    "qwen2.5" alone isn't a pulled model. "=" as the separator avoids
    the collision entirely."""
    import os

    old = os.environ.get("OLLAMA_MODELS")
    try:
        os.environ["OLLAMA_MODELS"] = "qwen2.5:3b=Qwen 2.5 3B (local)"
        models = ollama_provider._parse_models_from_env()
    finally:
        if old is None:
            os.environ.pop("OLLAMA_MODELS", None)
        else:
            os.environ["OLLAMA_MODELS"] = old

    assert len(models) == 1
    assert models[0].id == "qwen2.5:3b"  # NOT "qwen2.5" - the tag must survive
    assert models[0].label == "Qwen 2.5 3B (local)"


def test_ollama_models_parsed_falls_back_to_id_when_label_omitted():
    import os

    old = os.environ.get("OLLAMA_MODELS")
    try:
        os.environ["OLLAMA_MODELS"] = "qwen2.5:3b"
        models = ollama_provider._parse_models_from_env()
    finally:
        if old is None:
            os.environ.pop("OLLAMA_MODELS", None)
        else:
            os.environ["OLLAMA_MODELS"] = old

    assert models == [ollama_provider.ModelOption(id="qwen2.5:3b", label="qwen2.5:3b")]


def test_ollama_not_in_automatic_order():
    """The one behavioral guarantee this provider's whole design rests
    on - see its module docstring and router.py's comment on
    AUTOMATIC_ORDER for why a small local model must never be silently
    picked for a real question."""
    from chat_app.services.llm import router

    assert "ollama" not in router.AUTOMATIC_ORDER
    assert "ollama" in router._PROVIDERS  # still registered - manually selectable