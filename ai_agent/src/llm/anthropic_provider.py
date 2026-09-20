"""Anthropic Messages API provider - pinned by agent_config.py when
AI_AGENT_PROVIDER=anthropic. (Renamed from claude_provider.py - the
AI_AGENT_PROVIDER value and PROVIDER_ID/cooldown key are "anthropic".)

Adapted from chat_app/src/services/llm/claude_provider.py: tool calls go
through src.mcp_upstream instead of src.services.mcp_client; no MODELS
list or ProviderSpec registration (this project pins one provider per
instance - see agent_config.py); DEFAULT_MODEL replaces chat_app's
shared Settings object. The tool-calling loop itself, including the
cancellation checkpoint between rounds, is unchanged.

AI_AGENT_GATEWAY picks which client this instance talks through, always
by looking up a block of the same name in configs/config_llms.json's
"anthropic" section - "claude" (default) is just another block there,
same as "openrouter"/"litellm"/"portkey"/etc, except it has no base_url
(the Anthropic SDK already defaults to api.anthropic.com), needs no
auth_token (Anthropic's own API takes a plain api_key), and its api_key
points at the plain CLAUDE_API_KEY var. "bedrock" and "vertex" are the
two exceptions requiring a different SDK client class (AnthropicBedrock/
AnthropicVertex, different auth shape entirely) rather than a base_url
swap. Whichever block is picked, the actual secret values it points at
("{CLAUDE_API_KEY}" etc) still only ever come from secret_llm.env,
resolved by llm_config.py - never written in the JSON file itself.
has_api_key() checks the CURRENTLY SELECTED gateway's own required
secret(s), not a fixed var - a developer running only "openrouter" with
OPENROUTER_API_KEY set (and no CLAUDE_API_KEY at all) is correctly seen
as configured.
"""

from __future__ import annotations

import os
from typing import Any

from anthropic import (
    Anthropic,
    AnthropicBedrock,
    AnthropicVertex,
    AsyncAnthropic,
    AsyncAnthropicBedrock,
    AsyncAnthropicVertex,
    RateLimitError,
)

from src import delegation
from src.llm import cancellation, cooldown, llm_config, token_limits
from src.llm.agent_roles import SYSTEM_PROMPT
from src.llm.base_provider import (
    BaseProvider, ChatCancelled, ChatResult, LiveUsage, OnEvent, ToolCallRecord, dispatch_with_progress, step_event,
)
from src.mcp_upstream import call_tool, list_tools, tool_description


PROVIDER_NAME = "anthropic"

# Read by Task 4's agent_config.py to decide whether this provider's
# run_chat() can be driven with a live on_event callback (streamed tokens +
# step_start/step_end around tool calls) or only awaited for a final
# ChatResult - every provider module gets this flag, not just the ones
# that support it, so agent_config.py can check it without a try/except.
SUPPORTS_STREAMING = True


class _Anthropic(BaseProvider):
    PROVIDER_ID = "anthropic"
    GATEWAY_ENV = "AI_AGENT_GATEWAY"
    DEFAULT_MODEL_FALLBACK = "claude-sonnet-5"

    _client: AsyncAnthropic | AsyncAnthropicBedrock | AsyncAnthropicVertex | None = None
    # Separate cache from _client above - run_interpret() needs a plain
    # synchronous client (its own client.messages.create(...) call is not
    # awaited), while run_chat() needs the async one. Same gateway
    # resolution/config either way, just a different SDK class built from
    # it, so the two accessors (get_client/get_sync_client) must not share
    # a cache slot or one call site would get back the wrong kind of
    # client on the second call.
    _sync_client: Anthropic | AnthropicBedrock | AnthropicVertex | None = None

    @classmethod
    def _gateway_name(cls) -> str:
        return os.getenv(cls.GATEWAY_ENV) or "claude"

    @classmethod
    def has_api_key(cls) -> bool:
        gateway_name = cls._gateway_name()
        if gateway_name == "bedrock":
            cfg = llm_config.gateway(PROVIDER_NAME, "bedrock")
            return bool(cfg.get("aws_access_key_id") and cfg.get("aws_secret_access_key"))
        if gateway_name == "vertex":
            cfg = llm_config.gateway(PROVIDER_NAME, "vertex")
            return bool(cfg.get("project_id"))
        try:
            cfg = llm_config.gateway(PROVIDER_NAME, gateway_name)
        except KeyError:
            return False
        return bool(cfg.get("api_key") or cfg.get("auth_token"))

    @classmethod
    def get_client(cls) -> AsyncAnthropic | AsyncAnthropicBedrock | AsyncAnthropicVertex:
        if cls._client is not None:
            return cls._client

        gateway_name = cls._gateway_name()

        if gateway_name == "bedrock":
            cfg = llm_config.gateway(PROVIDER_NAME, "bedrock")
            cls._client = AsyncAnthropicBedrock(
                aws_access_key=cfg.get("aws_access_key_id"),
                aws_secret_key=cfg.get("aws_secret_access_key"),
                aws_region=cfg.get("aws_region"),
            )
            return cls._client

        if gateway_name == "vertex":
            cfg = llm_config.gateway(PROVIDER_NAME, "vertex")
            if not cfg.get("project_id"):
                raise ValueError("configs/config_llms.json anthropic.vertex.project_id env var not set")
            cls._client = AsyncAnthropicVertex(project_id=cfg["project_id"], region=cfg.get("region"))
            return cls._client

        # Every other block ("claude" itself, "openrouter", "litellm",
        # "helicone", "portkey", ...) is a plain AsyncAnthropic() build -
        # config_llms.json supplies api_key/auth_token/base_url, "claude"'s
        # own block just leaves base_url unset (SDK default).
        cfg = llm_config.gateway(PROVIDER_NAME, gateway_name)
        api_key = cfg.get("api_key")
        auth_token = cfg.get("auth_token")
        if not api_key and not auth_token:
            raise ValueError(
                f"configs/config_llms.json anthropic.{gateway_name}: neither its api_key nor "
                "auth_token env var is set in secret_llm.env"
            )
        cls._client = AsyncAnthropic(api_key=api_key, auth_token=auth_token, base_url=cfg.get("base_url"))
        return cls._client

    @classmethod
    def get_sync_client(cls) -> Anthropic | AnthropicBedrock | AnthropicVertex:
        """Same gateway resolution as get_client() above, but builds the
        plain synchronous SDK classes (Anthropic/AnthropicBedrock/
        AnthropicVertex) instead of their Async* counterparts. Exists
        solely for run_interpret(), which does a single, non-streaming,
        non-`await`ed `client.messages.create(...)` call - get_client()'s
        AsyncAnthropic etc. would hand that call site an unawaited
        coroutine instead of a response. Cached separately in
        `_sync_client` so this never collides with get_client()'s `_client`."""
        if cls._sync_client is not None:
            return cls._sync_client

        gateway_name = cls._gateway_name()

        if gateway_name == "bedrock":
            cfg = llm_config.gateway(PROVIDER_NAME, "bedrock")
            cls._sync_client = AnthropicBedrock(
                aws_access_key=cfg.get("aws_access_key_id"),
                aws_secret_key=cfg.get("aws_secret_access_key"),
                aws_region=cfg.get("aws_region"),
            )
            return cls._sync_client

        if gateway_name == "vertex":
            cfg = llm_config.gateway(PROVIDER_NAME, "vertex")
            if not cfg.get("project_id"):
                raise ValueError("configs/config_llms.json anthropic.vertex.project_id env var not set")
            cls._sync_client = AnthropicVertex(project_id=cfg["project_id"], region=cfg.get("region"))
            return cls._sync_client

        cfg = llm_config.gateway(PROVIDER_NAME, gateway_name)
        api_key = cfg.get("api_key")
        auth_token = cfg.get("auth_token")
        if not api_key and not auth_token:
            raise ValueError(
                f"configs/config_llms.json anthropic.{gateway_name}: neither its api_key nor "
                "auth_token env var is set in secret_llm.env"
            )
        cls._sync_client = Anthropic(api_key=api_key, auth_token=auth_token, base_url=cfg.get("base_url"))
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
        """Human-readable name of the CURRENTLY SELECTED gateway (its
        "label" field in configs/config_llms.json), for chat_app's
        provider dropdown to show the actual vendor in use - e.g.
        "OpenRouter" rather than a static "Claude Agent" - when
        AI_AGENT_GATEWAY points this instance somewhere other than
        "claude". Falls back to the gateway's own name, capitalized, if
        its block has no "label" (or the gateway name is unknown)."""
        gateway_name = cls._gateway_name()
        try:
            cfg = llm_config.gateway(PROVIDER_NAME, gateway_name)
        except KeyError:
            cfg = {}
        return cfg.get("label") or gateway_name.capitalize()


PROVIDER_ID = _Anthropic.PROVIDER_ID
DEFAULT_MODEL = _Anthropic.resolve_default_model()
VENDOR_LABEL = _Anthropic.resolve_vendor_label()

_get_client = _Anthropic.get_client
_get_sync_client = _Anthropic.get_sync_client
has_api_key = _Anthropic.has_api_key
is_available = _Anthropic.is_available


def _dispatch(name: str, arguments: dict[str, Any], depth: int) -> str:
    if name == delegation.TOOL_NAME:
        return delegation.call(arguments["agent_id"], arguments["question"], depth)
    return call_tool(name, arguments)


def _tool_schemas(enabled_extensions: list[str] | None = None) -> list[dict[str, Any]]:
    # display_label rides along on every schema dict returned here so
    # run_chat can build its step_start "label" lookup from the same
    # list it already has - it is NOT a real Anthropic tools= schema
    # field, so run_chat pops it back off before sending schemas to the
    # API (see the `labels = {...pop...}` line below).
    schemas = [
        {
            "name": tool.name,
            "description": tool_description(tool),
            "input_schema": tool.inputSchema or {"type": "object", "properties": {}},
            "display_label": (tool.meta or {}).get("display_label") if hasattr(tool, "meta") else None,
        }
        for tool in list_tools(enabled_extensions)
    ]
    if delegation.is_available():
        schemas.append(
            {
                "name": delegation.TOOL_NAME,
                "description": delegation.tool_description(),
                "input_schema": delegation.TOOL_PARAMETERS,
                "display_label": None,
            }
        )
    return schemas


async def run_chat(
    question: str,
    history: list[dict[str, Any]],
    model: str | None = None,
    enabled_extensions: list[str] | None = None,
    request_id: str | None = None,
    depth: int = 0,
    on_event: OnEvent | None = None,
) -> ChatResult:
    client = _get_client()
    model_name = model or DEFAULT_MODEL
    history = token_limits.trim_history_to_fit(history, PROVIDER_ID)
    messages: list[dict[str, Any]] = [*history, {"role": "user", "content": question}]
    tools_used: list[str] = []
    tool_calls: list[ToolCallRecord] = []
    schemas = _tool_schemas(enabled_extensions)
    # display_label isn't a real Anthropic tools= field (see _tool_schemas) -
    # pop it into this name->label lookup here, once, rather than sending it
    # to the API or re-deriving it per tool_use block below.
    labels = {s["name"]: s.pop("display_label") for s in schemas}
    # Every round of this loop is a real, separately-billed API call, so a
    # multi-tool-call answer's total is the sum across all rounds, not just
    # the final one. Anthropic's usage object has input_tokens/output_tokens
    # but no total_tokens field of its own - always present on this API, so
    # this stays a plain int rather than the optional/"unknown" handling the
    # other providers need.
    total_tokens = 0
    meter = LiveUsage(on_event)
    # The full prompt just sent (all resent history + this round's tool
    # results), not a sum across rounds like total_tokens - this is what
    # the usage bar and the phase-5 auto-trigger need to know how close
    # the *next* call is to the model's context window, so it's
    # overwritten each round rather than accumulated.
    context_tokens = 0

    try:
        for _ in range(token_limits.max_tool_rounds(PROVIDER_ID)):
            if cancellation.is_cancelled(request_id):
                raise ChatCancelled()
            token_limits.enforce_context_limit(PROVIDER_ID, [SYSTEM_PROMPT, *messages])
            # Every round is streamed, so text appears as the model writes
            # it. A round that ends in tool_use may still have streamed some
            # text first; "token_reset" tells the client to drop it, since
            # the real answer is the text of the final (non-tool) round.
            text_parts: list[str] = []
            async with client.messages.stream(
                model=model_name,
                max_tokens=token_limits.max_output_tokens(PROVIDER_ID),
                system=SYSTEM_PROMPT,
                messages=messages,
                tools=schemas,
            ) as stream:
                async for chunk in stream.text_stream:
                    text_parts.append(chunk)
                    if on_event:
                        await on_event(step_event("token", text=chunk))
                    await meter.chars(len(chunk))
                response = await stream.get_final_message()
            total_tokens += response.usage.input_tokens + response.usage.output_tokens
            await meter.round_done(response.usage.input_tokens + response.usage.output_tokens)
            context_tokens = response.usage.input_tokens

            if response.stop_reason != "tool_use":
                return ChatResult(
                    response="".join(text_parts),
                    tools_used=tools_used,
                    tool_calls=tool_calls,
                    provider_id=PROVIDER_ID,
                    model=model_name,
                    total_tokens=total_tokens,
                    context_tokens=context_tokens,
                )

            if text_parts and on_event:
                await on_event(step_event("token_reset"))
            messages.append({"role": "assistant", "content": response.content})

            tool_results: list[dict[str, Any]] = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                tools_used.append(block.name)
                step_id = block.id
                if on_event:
                    await on_event(step_event(
                        "step_start", id=step_id, tool=block.name, label=labels.get(block.name), arguments=block.input,
                    ))
                try:
                    result_text = await dispatch_with_progress(_dispatch, on_event, step_id, block.name, block.input, depth)
                    ok = True
                except Exception as error:
                    result_text = f"Tool '{block.name}' failed: {error}"
                    ok = False
                if on_event:
                    await on_event(step_event("step_end", id=step_id, ok=ok, result=result_text))
                tool_calls.append(ToolCallRecord(name=block.name, arguments=block.input, result=result_text))
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result_text})

            messages.append({"role": "user", "content": tool_results})
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
    )


def run_interpret(text: str, model: str | None = None) -> ChatResult:
    """One non-agentic completion, no tools offered (see server.py's
    `interpret` tool) - without letting the model wander into calling
    tools, which run_chat's full loop would allow. No cancellation/depth handling - unlike run_chat, this is
    always a single call, never a multi-round loop.

    Uses _get_sync_client(), not _get_client() - this call is a plain,
    non-`await`ed `client.messages.create(...)`, so it needs the
    synchronous Anthropic/AnthropicBedrock/AnthropicVertex client, not
    run_chat's AsyncAnthropic/etc. (calling an async client's
    .messages.create(...) without awaiting it returns an unawaited
    coroutine, not a response)."""
    client = _get_sync_client()
    model_name = model or DEFAULT_MODEL
    try:
        messages = [{"role": "user", "content": text}]
        token_limits.enforce_context_limit(PROVIDER_ID, [SYSTEM_PROMPT, *messages])
        response = client.messages.create(
            model=model_name,
            max_tokens=token_limits.max_output_tokens(PROVIDER_ID),
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        response_text = "".join(block.text for block in response.content if block.type == "text")
        total_tokens = response.usage.input_tokens + response.usage.output_tokens
        return ChatResult(
            response=response_text,
            provider_id=PROVIDER_ID,
            model=model_name,
            total_tokens=total_tokens,
            context_tokens=response.usage.input_tokens,
        )
    except RateLimitError as error:
        seconds = cooldown.extract_retry_after_seconds(error) or cooldown.DEFAULT_COOLDOWN_SECONDS
        cooldown.start_cooldown(PROVIDER_ID, seconds)
        raise
