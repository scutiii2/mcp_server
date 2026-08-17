"""Local Ollama provider, via Ollama's OpenAI Chat-Completions-compatible
endpoint (``/v1/chat/completions``).

Reuses the ``openai`` package already in chat_app's dependencies (see
pyproject.toml) rather than adding an Ollama-specific SDK - Ollama's
compatibility layer is deliberately built to be a drop-in target for the
OpenAI client, just pointed at a different ``base_url``.

Deliberately uses the OLDER Chat-Completions shape, not the newer
Responses API shape openai_provider.py uses. Ollama's own documentation
describes its ``/v1/responses`` support as still preliminary as of this
writing, while ``/v1/chat/completions`` (including tool calling) is the
mature, long-documented path - this deliberately doesn't rely on the
newer one.

No API key needed - Ollama has no auth by default. The OpenAI client
still requires *some* string for ``api_key``, so this passes the literal
placeholder ``"ollama"``, matching Ollama's own documented convention.
Never a real secret, never read from an env var.

Honest caveat about small local models and tool calling: the default
model this was set up against (``llama3.2:1b``) does have Ollama's
tool-calling template support built in - that part isn't guesswork. But
every independent guide on Ollama tool-calling agrees smaller models are
the least reliable at producing well-formed ``tool_calls`` JSON, and most
already call 3B unreliable for production tool use - 1B is smaller than
that. Expect this provider to work fine for simple, low-tool-count
questions and to sometimes answer in prose instead of calling a tool, or
produce malformed arguments, as the tool surface grows. That's why
router.py deliberately leaves this OUT of AUTOMATIC_ORDER - manual-select
only, so a flaky local model never silently becomes what answers a real
question. List a larger locally-hosted model in config.json's
"providers.ollama.models" (see infra/app_config.py) if reliability
matters more than running fully local on a 1B model.

No rate-limit cooldown wiring here, unlike the two cloud providers, for
the reason it isn't needed: local inference doesn't 429.

has_api_key()/is_available() are still both unconditionally True - no
auth concept here, so neither can meaningfully fail. What DOES get a
live check now is per-model availability: MODELS is the operator's
WISH list (read once at startup, from config.json - see below), and
check_model_availability() below verifies live, via Ollama's own
/api/tags, which of those are actually pulled on the host right now.
That's a deliberate split - the model list itself only changes when
someone edits config.json and restarts (same as OLLAMA_MODELS before
it - this isn't a regression, env vars already required a restart),
but whether a given entry actually works can change any time someone
runs `ollama pull`/`ollama rm`, so that half is checked on every
/api/providers request instead of trusted from a stale list.
"""

from __future__ import annotations

import json
import os
import re
import secrets
from typing import Any
from urllib.request import urlopen

from chat_app.config import settings
from chat_app.infra.app_config import load_ollama_models
from chat_app.services.llm.base import (
    SYSTEM_PROMPT,
    ChatResult,
    ModelAvailability,
    ModelAvailabilityCheck,
    ModelOption,
    ProviderSpec,
    RecursiveRoundRecord,
    ToolCallRecord,
)
from chat_app.services.mcp_client import call_tool, list_tools


PROVIDER_ID = "ollama"


def _base_url() -> str:
    """Point this at your Ollama host's LAN address, not localhost,
    whenever chat_app and Ollama run on different machines (chat_app on
    your dev machine, Ollama on a homelab/NAS box on the same network).
    Ollama itself binds to 127.0.0.1 only by default on a plain install -
    if this times out or gets connection-refused, check that
    OLLAMA_HOST=0.0.0.0 (or equivalent) is set on the Ollama side, not
    just this env var on the chat_app side."""
    return os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")


def has_api_key() -> bool:
    """No real auth for Ollama - always True. Kept as a function, not a
    constant, for interface parity with every other provider."""
    return True


def is_available() -> bool:
    return has_api_key()


# Read once at startup, from config.json's "providers.ollama.models" -
# see infra/app_config.py. An empty list (no config.json, or no
# "providers.ollama" section) means no models are offered; that's a
# valid, quiet deployment state, not an error - see load_ollama_models's
# docstring.
MODELS = load_ollama_models(settings.chat_config_path)
_DEFAULT_MODEL_ID = MODELS[0].id if MODELS else ""

_client: Any = None


def _get_client() -> Any:
    global _client
    if _client is None:
        from openai import OpenAI  # already a chat_app dependency - see module docstring

        _client = OpenAI(base_url=_base_url(), api_key="ollama")
    return _client


def _tool_schemas(enabled_extensions: list[str] | None = None) -> list[dict[str, Any]]:
    """Chat-Completions function-wrapped shape - note this nests the
    schema under a "function" key, unlike openai_provider.py's flatter
    Responses API shape."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.inputSchema or {"type": "object", "properties": {}},
            },
        }
        for tool in list_tools(enabled_extensions)
    ]


def _usage_tokens(usage: Any) -> int | None:
    """Best-effort token count for one round of the Chat Completions loop.

    Ollama doesn't always populate ``usage`` depending on version - a
    missing usage object, or one that reports zero on both fields, means
    this round contributed nothing countable (not that zero tokens were
    genuinely used), so this returns None rather than 0 for either case."""
    if usage is None:
        return None
    total = getattr(usage, "total_tokens", None)
    if not total:
        prompt = getattr(usage, "prompt_tokens", None) or 0
        completion = getattr(usage, "completion_tokens", None) or 0
        total = prompt + completion
    return total or None


# Ollama's own default context window (independent of any per-model
# training context) is small - often 2048 tokens - unless a request
# explicitly asks for more via the "options.num_ctx" field its
# OpenAI-compatible endpoint accepts as an extension (not part of the
# openai SDK's own typed kwargs, hence `extra_body`). A tool result can
# easily be verbose enough (a host-health dump with many disks/processes,
# for instance) to overflow that default on the follow-up summarization
# call - and a small model whose context overflows tends to emit an
# empty completion rather than an error, which otherwise looks
# indistinguishable from a genuinely blank answer. 8192 gives real
# headroom over the default without asking Ollama to reserve much more
# memory than a small local model already needs.
_NUM_CTX = 8192

# Nothing bounds how long a single completion can run by default - a
# small model that starts hallucinating instead of answering has no
# reason to stop on its own. Confirmed live: phi4-mini rambled about a
# fictional Google Cloud Run setup for 8m52s / 3748 tokens on one
# request. 1024 tokens is generous for a genuine answer (including a
# thorough tool-result summary) while bounding the worst case to a
# fraction of what an unbounded generation could reach.
_NUM_PREDICT = 1024

# Small local models have been observed (live, against phi4-mini)
# hallucinating an entirely unrelated execution context - inventing a
# cloud platform and an HTTP endpoint that were never mentioned - instead
# of using the tool-calling mechanism this request actually offers, and
# writing a tool call as prose/JSON in the reply instead of a real
# tool_calls entry. This is a best-effort nudge against both, not a fix:
# whether it helps depends on how well a given model's own chat template
# implements tool calling in the first place - see this module's
# docstring for the broader small-model tool-calling caveat. Layered on
# top of SYSTEM_PROMPT (never replacing it) and only for this provider -
# the cloud providers' own tool-calling is already reliable and doesn't
# need this.
_LOCAL_MODEL_TOOL_GUIDANCE = (
    "You are running locally via Ollama with real tool-calling support. "
    "When you need a tool, call it using your native function-calling "
    "mechanism - never write the tool call, its JSON arguments, or a "
    "pretend HTTP request as text in your reply. Only ever call tools "
    "that were actually offered to you in this request; do not invent or "
    "assume any other platform, API, or execution environment (for "
    "example a cloud provider) that wasn't mentioned."
)

_MAX_TOOL_CALL_ROUNDS = 6

# Extra self-review rounds for models with recursive_chain=True (see
# config.json / ModelOption). Capped, not unbounded, for the same reason
# _MAX_TOOL_CALL_ROUNDS is: a small local model that never settles on a
# stable answer must not turn one chat request into an unbounded number
# of API calls.
_MAX_RECURSIVE_CHAIN_ROUNDS = 3

_RECURSIVE_CHAIN_PROMPT = (
    "Review your previous answer for correctness and completeness. If it "
    "is already correct and complete, repeat it verbatim. Otherwise, "
    "provide a corrected, final answer."
)


def _recursive_chain_enabled(model_name: str) -> bool:
    for model in MODELS:
        if model.id == model_name:
            return model.recursive_chain
    return False


# Balances one level of brace nesting - enough for the malformed shapes
# small models have actually been observed to leak (a flat object, or one
# with a single nested "arguments"/"function" object inside). A tool's
# own echoed JSON Schema nests deeper than this (parameters -> properties
# -> per-field type objects), so it either fails to match as a complete
# object here or - if some fragment of it does match - fails the
# schema-shape rejection below. Either way it's never mistaken for a
# real call; see _extract_fallback_tool_call's docstring.
_JSON_OBJECT_RE = re.compile(r"\{(?:[^{}]|\{[^{}]*\})*\}")

# Key names small models have been observed using in place of the
# correct nested {"function": {"name": ..., "arguments": ...}} shape -
# e.g. a flat literal string key "function.name" instead of actually
# nesting. Checked in order; first match wins.
_FALLBACK_NAME_KEYS = ("name", "function.name")
_FALLBACK_ARGS_KEYS = ("arguments", "parameters", "function.arguments", "arguments.function.arguments")


def _extract_fallback_tool_call(content: str, known_tool_names: set[str]) -> tuple[str, dict[str, Any]] | None:
    """Recovers a tool call that leaked into plain-text ``content``
    instead of the API's structured ``tool_calls`` field - a known
    reliability gap for small local models (see this module's docstring).

    Returns ``None`` - leaving the caller's existing "treat this as the
    final answer" behavior completely unchanged - unless it finds, in the
    same JSON object literal, BOTH a name matching one of THIS request's
    actually-offered tools (``known_tool_names``, built from this
    request's own ``tool_schemas`` - never a hallucinated or stale name)
    AND an arguments-shaped dict. "Arguments-shaped" deliberately excludes
    anything that looks like a JSON Schema (``"properties"`` present, or
    ``"type": "object"``) - a confused model echoing back the tool
    definition it was given has a "name" too, and must not be mistaken
    for an attempt to call it.
    """
    for candidate in _JSON_OBJECT_RE.findall(content):
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(parsed, dict):
            continue

        function_block = parsed.get("function")
        lookup = {**parsed, **(function_block if isinstance(function_block, dict) else {})}

        name = next(
            (lookup[key] for key in _FALLBACK_NAME_KEYS if isinstance(lookup.get(key), str)),
            None,
        )
        if name is None or name not in known_tool_names:
            continue

        arguments = next((lookup[key] for key in _FALLBACK_ARGS_KEYS if isinstance(lookup.get(key), dict)), None)
        if arguments is None or "properties" in arguments or arguments.get("type") == "object":
            continue

        return name, arguments

    return None


def _tool_loop(
    client: Any,
    messages: list[dict[str, Any]],
    model_name: str,
    tool_schemas: list[dict[str, Any]],
    tools_used: list[str],
    tool_calls_log: list[ToolCallRecord],
) -> tuple[str, int | None]:
    """One full pass through the tool-calling loop: keep letting the model
    call tools until it produces a plain-text answer, capped at
    _MAX_TOOL_CALL_ROUNDS rounds. Mutates ``messages``/``tools_used``/
    ``tool_calls_log`` in place (append-only) so a caller making multiple
    _tool_loop() calls in sequence - recursive_chain's extra review rounds -
    keeps full conversation history across calls. Appends the final
    plain-text answer to ``messages`` as an assistant turn before
    returning, for the same reason: a follow-up review round needs that
    answer in context.

    Every round is a real, separately-billed API call, so the returned
    token count is the sum across all rounds of this one pass - stays
    None (rather than 0) until a round actually reports usage, consistent
    with ChatResult.total_tokens's "unknown" semantics."""
    total_tokens: int | None = None
    known_tool_names = {schema["function"]["name"] for schema in tool_schemas}

    for _ in range(_MAX_TOOL_CALL_ROUNDS):
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            tools=tool_schemas if tool_schemas else None,
            extra_body={"options": {"num_ctx": _NUM_CTX, "num_predict": _NUM_PREDICT}},
        )
        round_tokens = _usage_tokens(getattr(response, "usage", None))
        if round_tokens is not None:
            total_tokens = (total_tokens or 0) + round_tokens

        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None) or []

        if not tool_calls:
            fallback = _extract_fallback_tool_call(message.content or "", known_tool_names)
            if fallback is not None:
                fallback_name, fallback_arguments = fallback
                call_id = f"recovered-{secrets.token_hex(4)}"
                # Reconstructed in the same shape a real tool_calls entry
                # would take, so the rest of the conversation (and the
                # model's next round) sees a normal tool exchange rather
                # than the malformed text that actually arrived.
                messages.append(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": call_id,
                                "type": "function",
                                "function": {"name": fallback_name, "arguments": json.dumps(fallback_arguments)},
                            }
                        ],
                    }
                )
                tools_used.append(fallback_name)
                try:
                    result_text = call_tool(fallback_name, fallback_arguments)
                except Exception as error:
                    result_text = f"Tool '{fallback_name}' failed: {error}"
                tool_calls_log.append(ToolCallRecord(name=fallback_name, arguments=fallback_arguments, result=result_text))
                messages.append({"role": "tool", "tool_call_id": call_id, "content": result_text})
                continue

            answer = message.content or ""
            messages.append({"role": "assistant", "content": answer})
            return answer, total_tokens

        messages.append({"role": "assistant", "content": message.content, "tool_calls": tool_calls})
        for call in tool_calls:
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except Exception:
                arguments = {}
            tools_used.append(call.function.name)
            try:
                result_text = call_tool(call.function.name, arguments)
            except Exception as error:
                result_text = f"Tool '{call.function.name}' failed: {error}"
            tool_calls_log.append(ToolCallRecord(name=call.function.name, arguments=arguments, result=result_text))
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result_text})

    return "Reached maximum tool-call rounds without a final answer.", total_tokens


def run_chat(
    question: str,
    history: list[dict[str, Any]],
    model: str | None = None,
    enabled_extensions: list[str] | None = None,
) -> ChatResult:
    client = _get_client()
    system_content = f"{SYSTEM_PROMPT}\n\n{_LOCAL_MODEL_TOOL_GUIDANCE}"
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_content}, *history]
    messages.append({"role": "user", "content": question})
    tools_used: list[str] = []
    tool_calls: list[ToolCallRecord] = []
    tool_schemas = _tool_schemas(enabled_extensions)
    model_name = model or _DEFAULT_MODEL_ID
    total_tokens: int | None = None

    answer, round_tokens = _tool_loop(client, messages, model_name, tool_schemas, tools_used, tool_calls)
    if round_tokens is not None:
        total_tokens = (total_tokens or 0) + round_tokens

    recursive_rounds: list[RecursiveRoundRecord] = []
    if _recursive_chain_enabled(model_name):
        # Ask the model to double-check its own answer for a bounded
        # number of extra rounds, stopping early the moment an answer
        # repeats verbatim (convergence) rather than always spending the
        # full budget. An answer that keeps changing every round still
        # stops at _MAX_RECURSIVE_CHAIN_ROUNDS and returns the last one.
        for round_number in range(1, _MAX_RECURSIVE_CHAIN_ROUNDS + 1):
            messages.append({"role": "user", "content": _RECURSIVE_CHAIN_PROMPT})
            refined_answer, round_tokens = _tool_loop(client, messages, model_name, tool_schemas, tools_used, tool_calls)
            if round_tokens is not None:
                total_tokens = (total_tokens or 0) + round_tokens
            converged = refined_answer.strip() == answer.strip()
            answer = refined_answer
            recursive_rounds.append(RecursiveRoundRecord(round=round_number, response=refined_answer, converged=converged))
            if converged:
                break

    return ChatResult(
        response=answer,
        tools_used=tools_used,
        tool_calls=tool_calls,
        recursive_rounds=recursive_rounds,
        provider_id=PROVIDER_ID,
        model=model_name,
        total_tokens=total_tokens,
    )


# Short enough that a hung/unreachable Ollama host doesn't make the
# /api/providers poll (every 15s, from every open chat tab) noticeably
# laggy. A real LAN round-trip to a host that's actually up is
# millisecond-scale; this is sized for "host is off/unreachable", not
# for a slow-but-working one.
_AVAILABILITY_TIMEOUT_SECONDS = 2.0


def _tags_url() -> str:
    """Ollama's native model-listing endpoint - GET /api/tags - lives at
    the ROOT of the Ollama host, unlike /v1/chat/completions. _base_url()
    defaults to ".../11434/v1"; strip a trailing "/v1" (or "/v1/") to get
    back to the root before appending "/api/tags"."""
    base = _base_url().rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    return f"{base}/api/tags"


def check_model_availability() -> ModelAvailabilityCheck:
    """Live check of which of MODELS (the operator's desired list, read
    once at startup - see above) are actually pulled on the Ollama host
    right now.

    Ollama's documented /api/tags response shape (docs/api.md, "List
    Local Models") is::

        {"models": [{"name": "qwen2.5:7b", "model": "qwen2.5:7b", ...}]}

    "name" is already in the same name:tag form as a configured model id,
    so this is a plain exact-string match - no normalization needed.

    Fails closed: connection refused, timeout, non-2xx (urlopen raises
    for those), invalid JSON, or a payload missing the "models" list -
    all collapse to the same "unreachable" outcome, with every configured
    model marked unavailable too, rather than raising out of a route
    that's polled every 15 seconds by every open chat tab.
    """
    configured_ids = [model.id for model in MODELS]
    if not configured_ids:
        # Nothing configured to verify - config.json has no
        # "providers.ollama.models" entries (or no config.json at all),
        # which is a valid quiet deployment state, not a failure. Skips
        # the network call entirely rather than probing a host nobody
        # asked this deployment to use.
        return ModelAvailabilityCheck(reachable=True, reason=None, models={})

    try:
        with urlopen(_tags_url(), timeout=_AVAILABILITY_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
        pulled_names = {str(entry["name"]) for entry in payload["models"]}
    except Exception:
        return ModelAvailabilityCheck(
            reachable=False,
            reason="unreachable",
            models={
                model_id: ModelAvailability(available=False, reason="unreachable")
                for model_id in configured_ids
            },
        )

    models = {
        model_id: (
            ModelAvailability(available=True, reason=None)
            if model_id in pulled_names
            else ModelAvailability(available=False, reason="not_pulled")
        )
        for model_id in configured_ids
    }
    return ModelAvailabilityCheck(reachable=True, reason=None, models=models)


PROVIDER = ProviderSpec(
    id=PROVIDER_ID,
    label="Local (Ollama)",
    has_api_key=has_api_key,
    is_available=is_available,
    run_chat=run_chat,
    models=MODELS,
    default_model_id=_DEFAULT_MODEL_ID,
    check_models=check_model_availability,
)