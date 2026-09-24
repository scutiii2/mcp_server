"""OpenAI Responses API provider - pinned by agent_config.py when
AI_AGENT_PROVIDER=openai.

Adapted from chat_app/src/services/llm/openai_provider.py - see
anthropic_provider.py's module docstring for what changed and why.

AI_AGENT_GATEWAY picks which client this instance talks through, same
pattern as anthropic_provider.py: always a block of
that name in configs/config_llms.json's "openai" section. "gpt" (default)
is just another block there, except it has no base_url (the OpenAI SDK
already defaults to api.openai.com) and its api_key points at the plain
GPT_API_KEY var. "azure" is the one exception requiring a different SDK
client class (AzureOpenAI - azure_endpoint/api_version/deployment, not a
base_url swap). Any other value (e.g. "together", "groq", "fireworks",
"deepinfra", "perplexity", "ollama", "vllm") is a plain OpenAI-compatible
base_url swap block.

has_api_key() checks the CURRENTLY SELECTED gateway's own required
secret(s), not a fixed var - a developer running only "groq" with
GROQ_API_KEY set (and no GPT_API_KEY at all) is correctly seen as
configured.

Caveat worth knowing: run_chat/run_interpret below call client.responses.
create - the OpenAI Responses API. Azure OpenAI supports it; most of the
other gateways (Together, Groq, Fireworks, DeepInfra, Perplexity, Ollama,
vLLM) only implement the older Chat Completions API
(client.chat.completions.create), not Responses. Pointing AI_AGENT_GATEWAY
at one of those will build a client fine but run_chat's actual API calls
may 404 - swapping the call site to chat.completions is a separate,
larger change (different message/tool-call shapes) than the client
wiring here.
"""

from __future__ import annotations

import json
import os
from typing import Any

from openai import AsyncAzureOpenAI, AsyncOpenAI, AzureOpenAI, OpenAI, RateLimitError

from src import delegation
from src.llm import cancellation, cooldown, llm_config, token_limits
from src.llm.agent_roles import SYSTEM_PROMPT, system_prompt_for
from src.llm.base_provider import (
    BaseProvider, ChatCancelled, ChatResult, LiveUsage, OnEvent, ToolCallRecord, dispatch_with_progress, step_event,
)
from src.mcp_upstream import call_tool, list_tools, tool_description


PROVIDER_NAME = "openai"

# Read by agent_config.py to decide whether this provider's run_chat() can
# be driven with a live on_event callback (streamed tokens +
# step_start/step_end around tool calls) or only awaited for a final
# ChatResult - see anthropic_provider.py's SUPPORTS_STREAMING for the same
# flag on that provider.
SUPPORTS_STREAMING = True


class _OpenAI(BaseProvider):
    PROVIDER_ID = "openai"
    GATEWAY_ENV = "AI_AGENT_GATEWAY"
    DEFAULT_MODEL_FALLBACK = "gpt-5.6-sol"

    _client: AsyncOpenAI | AsyncAzureOpenAI | None = None
    # Separate cache from _client above - run_interpret() need
    # plain synchronous clients (their own client.responses.create(...) calls
    # are not awaited), while run_chat() needs the async ones. Same gateway
    # resolution/config either way, just a different SDK class built from
    # it - mirrors anthropic_provider._Anthropic's get_client/get_sync_client
    # split, same reasoning.
    _sync_client: OpenAI | AzureOpenAI | None = None

    @classmethod
    def _gateway_name(cls) -> str:
        return os.getenv(cls.GATEWAY_ENV) or "gpt"

    @classmethod
    def has_api_key(cls) -> bool:
        gateway_name = cls._gateway_name()
        if gateway_name == "azure":
            cfg = llm_config.gateway(PROVIDER_NAME, "azure")
            return bool(cfg.get("azure_endpoint") and cfg.get("api_key"))
        try:
            cfg = llm_config.gateway(PROVIDER_NAME, gateway_name)
        except KeyError:
            return False
        return bool(cfg.get("api_key") or cfg.get("auth_token"))

    @classmethod
    def get_client(cls) -> AsyncOpenAI | AsyncAzureOpenAI:
        if cls._client is not None:
            return cls._client

        gateway_name = cls._gateway_name()

        if gateway_name == "azure":
            cfg = llm_config.gateway(PROVIDER_NAME, "azure")
            if not cfg.get("azure_endpoint") or not cfg.get("api_key"):
                raise ValueError(
                    "configs/config_llms.json openai.azure: AZURE_OPENAI_ENDPOINT / "
                    "AZURE_OPENAI_API_KEY not set in secret_llm.env"
                )
            cls._client = AsyncAzureOpenAI(
                azure_endpoint=cfg["azure_endpoint"],
                api_version=cfg.get("api_version"),
                api_key=cfg["api_key"],
            )
            return cls._client

        # Every other block ("gpt" itself, "together", "groq", "ollama",
        # ...) is a plain AsyncOpenAI() build - config_llms.json supplies
        # api_key/base_url, "gpt"'s own block just leaves base_url unset
        # (SDK default).
        cfg = llm_config.gateway(PROVIDER_NAME, gateway_name)
        secret = cfg.get("api_key") or cfg.get("auth_token")
        if not secret:
            raise ValueError(
                f"configs/config_llms.json openai.{gateway_name}: its api_key env var is not "
                "set in secret_llm.env"
            )
        cls._client = AsyncOpenAI(api_key=secret, base_url=cfg.get("base_url"))
        return cls._client

    @classmethod
    def get_sync_client(cls) -> OpenAI | AzureOpenAI:
        """Same gateway resolution as get_client() above, but builds the
        plain synchronous SDK classes (OpenAI/AzureOpenAI) instead of their
        Async* counterparts - used by run_interpret(), whose
        client.responses.create(...) calls are never awaited. Cached
        separately in `_sync_client` so this never collides with
        get_client()'s `_client`."""
        if cls._sync_client is not None:
            return cls._sync_client

        gateway_name = cls._gateway_name()

        if gateway_name == "azure":
            cfg = llm_config.gateway(PROVIDER_NAME, "azure")
            if not cfg.get("azure_endpoint") or not cfg.get("api_key"):
                raise ValueError(
                    "configs/config_llms.json openai.azure: AZURE_OPENAI_ENDPOINT / "
                    "AZURE_OPENAI_API_KEY not set in secret_llm.env"
                )
            cls._sync_client = AzureOpenAI(
                azure_endpoint=cfg["azure_endpoint"],
                api_version=cfg.get("api_version"),
                api_key=cfg["api_key"],
            )
            return cls._sync_client

        cfg = llm_config.gateway(PROVIDER_NAME, gateway_name)
        secret = cfg.get("api_key") or cfg.get("auth_token")
        if not secret:
            raise ValueError(
                f"configs/config_llms.json openai.{gateway_name}: its api_key env var is not "
                "set in secret_llm.env"
            )
        cls._sync_client = OpenAI(api_key=secret, base_url=cfg.get("base_url"))
        return cls._sync_client

    @classmethod
    def resolve_default_model(cls) -> str:
        try:
            cfg = llm_config.gateway(PROVIDER_NAME, cls._gateway_name())
        except KeyError:
            cfg = {}
        if cfg.get("model"):
            return cfg["model"]
        return cls.DEFAULT_MODEL_FALLBACK

    @classmethod
    def resolve_vendor_label(cls) -> str:
        """See anthropic_provider._Anthropic.resolve_vendor_label - same
        reasoning, just the "openai" section of config_llms.json."""
        gateway_name = cls._gateway_name()
        try:
            cfg = llm_config.gateway(PROVIDER_NAME, gateway_name)
        except KeyError:
            cfg = {}
        return cfg.get("label") or gateway_name.capitalize()


PROVIDER_ID = _OpenAI.PROVIDER_ID
DEFAULT_MODEL = _OpenAI.resolve_default_model()
VENDOR_LABEL = _OpenAI.resolve_vendor_label()

_get_client = _OpenAI.get_client
_get_sync_client = _OpenAI.get_sync_client
has_api_key = _OpenAI.has_api_key
is_available = _OpenAI.is_available


def _limit_gateway() -> str:
    return _OpenAI._gateway_name()


def _tool_schemas(enabled_extensions: list[str] | None = None) -> list[dict[str, Any]]:
    # display_label rides along on every schema dict returned here, same as
    # anthropic_provider._tool_schemas - NOT a real Responses API tools=
    # field, so run_chat pops it back off before sending schemas to the API.
    schemas = [
        {
            "type": "function",
            "name": tool.name,
            "description": tool_description(tool),
            "parameters": tool.inputSchema or {"type": "object", "properties": {}},
            "display_label": (tool.meta or {}).get("display_label") if hasattr(tool, "meta") else None,
        }
        for tool in list_tools(enabled_extensions)
    ]
    if delegation.is_available():
        schemas.append(
            {
                "type": "function",
                "name": delegation.TOOL_NAME,
                "description": delegation.tool_description(),
                "parameters": delegation.TOOL_PARAMETERS,
                "display_label": None,
            }
        )
    return schemas


# Fields the SDK adds to the parsed output items that stream.get_final_response()
# returns (ParsedResponseFunctionToolCall.parsed_arguments,
# ParsedResponseOutputText.parsed) - the Responses API rejects them when the
# items are sent back as input ("Unknown parameter: input[3].parsed_arguments").
_SDK_ONLY_FIELDS = {"parsed_arguments", "parsed"}


def _strip_sdk_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_sdk_fields(v) for k, v in value.items() if k not in _SDK_ONLY_FIELDS}
    if isinstance(value, list):
        return [_strip_sdk_fields(v) for v in value]
    return value


def _output_as_input_items(output: list[Any]) -> list[Any]:
    """Response output items, as plain dicts safe to resend as input."""
    return [
        _strip_sdk_fields(item.model_dump(exclude_none=True)) if hasattr(item, "model_dump") else item
        for item in output
    ]


def _dispatch(name: str, arguments: dict[str, Any], depth: int) -> str:
    if name == delegation.TOOL_NAME:
        return delegation.call(arguments["agent_id"], arguments["question"], depth)
    return call_tool(name, arguments)


async def run_chat(
    question: str,
    history: list[dict[str, Any]],
    model: str | None = None,
    enabled_extensions: list[str] | None = None,
    request_id: str | None = None,
    depth: int = 0,
    on_event: OnEvent | None = None,
    caveman: bool = False,
) -> ChatResult:
    client = _get_client()
    model_name = model or DEFAULT_MODEL
    history = token_limits.trim_history_to_fit(history, PROVIDER_ID, _limit_gateway())
    messages: list[Any] = [{"role": "system", "content": system_prompt_for(caveman)}, *history]
    messages.append({"role": "user", "content": question})
    tools_used: list[str] = []
    tool_calls: list[ToolCallRecord] = []
    schemas = _tool_schemas(enabled_extensions)
    # display_label isn't a real Responses API tools= field (see
    # _tool_schemas) - pop it into this name->label lookup here, once,
    # rather than sending it to the API or re-deriving it per call below.
    labels = {s["name"]: s.pop("display_label") for s in schemas}
    # Stays None (rather than 0) until a round actually reports usage -
    # some SDK versions leave response.usage unset, and a provider that
    # never reported usage should say "unknown" (see ChatResult.total_tokens),
    # not "zero tokens".
    total_tokens: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    meter = LiveUsage(on_event)
    # The full prompt just sent (all resent history), not a sum across
    # rounds like total_tokens - overwritten each round rather than
    # accumulated, same reasoning as anthropic_provider.run_chat.
    context_tokens: int | None = None

    try:
        for _ in range(token_limits.max_tool_rounds(PROVIDER_ID, _limit_gateway())):
            if cancellation.is_cancelled(request_id):
                raise ChatCancelled()
            token_limits.enforce_context_limit(PROVIDER_ID, messages, _limit_gateway())
            # Every round is streamed, so text appears as the model writes
            # it. A round that ends in function calls may still have streamed
            # some text first; "token_reset" tells the client to drop it,
            # since the real answer is the text of the final (no-tool) round.
            text_parts: list[str] = []
            async with client.responses.stream(
                model=model_name,
                input=messages,
                tools=schemas if schemas else None,
                max_output_tokens=token_limits.max_output_tokens(PROVIDER_ID, _limit_gateway()),
            ) as stream:
                async for event in stream:
                    if event.type == "response.output_text.delta":
                        text_parts.append(event.delta)
                        if on_event:
                            await on_event(step_event("token", text=event.delta))
                        await meter.chars(len(event.delta))
                response = await stream.get_final_response()
            usage = getattr(response, "usage", None)
            round_tokens = getattr(usage, "total_tokens", None) if usage is not None else None
            if round_tokens is not None:
                total_tokens = (total_tokens or 0) + round_tokens
            round_input = getattr(usage, "input_tokens", None) if usage is not None else None
            if round_input is not None:
                input_tokens = (input_tokens or 0) + round_input
            round_output = getattr(usage, "output_tokens", None) if usage is not None else None
            if round_output is not None:
                output_tokens = (output_tokens or 0) + round_output
            await meter.round_done(round_tokens)
            context_tokens = getattr(usage, "input_tokens", None) if usage is not None else None

            function_calls = [item for item in response.output if getattr(item, "type", "") == "function_call"]
            if not function_calls:
                return ChatResult(
                    response="".join(text_parts) or response.output_text,
                    tools_used=tools_used,
                    tool_calls=tool_calls,
                    provider_id=PROVIDER_ID,
                    model=model_name,
                    total_tokens=total_tokens,
                    context_tokens=context_tokens,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )

            if text_parts and on_event:
                await on_event(step_event("token_reset"))

            messages.extend(_output_as_input_items(response.output))
            for call in function_calls:
                try:
                    arguments = json.loads(call.arguments or "{}")
                except Exception:
                    arguments = {}
                tools_used.append(call.name)
                step_id = call.call_id
                if on_event:
                    await on_event(step_event(
                        "step_start", id=step_id, tool=call.name, label=labels.get(call.name), arguments=arguments,
                    ))
                try:
                    result_text = await dispatch_with_progress(_dispatch, on_event, step_id, call.name, arguments, depth)
                    ok = True
                except Exception as error:
                    result_text = f"Tool '{call.name}' failed: {error}"
                    ok = False
                if on_event:
                    await on_event(step_event("step_end", id=step_id, ok=ok, result=result_text))
                tool_calls.append(ToolCallRecord(name=call.name, arguments=arguments, result=result_text))
                messages.append({"type": "function_call_output", "call_id": call.call_id, "output": result_text})
    except RateLimitError as error:
        seconds = cooldown.extract_retry_after_seconds(error) or cooldown.DEFAULT_COOLDOWN_SECONDS
        cooldown.start_cooldown(PROVIDER_ID, seconds)
        raise

    return ChatResult(
        response="Reached maximum tool-call rounds without a final answer.",
        tools_used=tools_used,
        tool_calls=tool_calls,
        provider_id=PROVIDER_ID,
        model=model_name,
        total_tokens=total_tokens,
        context_tokens=context_tokens,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def run_interpret(text: str, model: str | None = None) -> ChatResult:
    """One non-agentic completion, no tools offered - see
    claude_provider.run_interpret's docstring, same reasoning. Uses
    _get_sync_client(), not _get_client() - this call is a plain,
    non-`await`ed client.responses.create(...), same reasoning as
    anthropic_provider.run_interpret."""
    client = _get_sync_client()
    model_name = model or DEFAULT_MODEL
    try:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ]
        token_limits.enforce_context_limit(PROVIDER_ID, messages, _limit_gateway())
        response = client.responses.create(
            model=model_name,
            input=messages,
            max_output_tokens=token_limits.max_output_tokens(PROVIDER_ID, _limit_gateway()),
        )
        usage = getattr(response, "usage", None)
        total_tokens = getattr(usage, "total_tokens", None) if usage is not None else None
        context_tokens = getattr(usage, "input_tokens", None) if usage is not None else None
        return ChatResult(
            response=response.output_text,
            provider_id=PROVIDER_ID,
            model=model_name,
            total_tokens=total_tokens,
            context_tokens=context_tokens,
        )
    except RateLimitError as error:
        seconds = cooldown.extract_retry_after_seconds(error) or cooldown.DEFAULT_COOLDOWN_SECONDS
        cooldown.start_cooldown(PROVIDER_ID, seconds)
        raise
