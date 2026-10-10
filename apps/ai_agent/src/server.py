"""ai_agent entry point - a FastMCP server exposing ask/status/cancel
tools to chat_app, backed by one pinned LLM provider (agent_config.py)
that itself talks to mcp_server as an MCP client (mcp_upstream.py).

Run with:
    python -m src.server
    python -m src.server --gateway openrouter
    python -m src.server --mcp-url http://127.0.0.1:8010/mcp
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any
from urllib.parse import urlsplit

_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument(
    "--gateway",
    help=(
        "Override this run's gateway block (gateways/<provider>/<gateway>.json), "
        "e.g. openrouter/bedrock/vertex/litellm/helicone/portkey for "
        "anthropic, or azure/together/groq/fireworks/deepinfra/"
        "perplexity/ollama/vllm for openai. Takes precedence over "
        "AI_AGENT_GATEWAY. Set before importing "
        "agent_config, since the provider resolves its client/default "
        "model from the gateway at import time."
    ),
)
_parser.add_argument(
    "--mcp-url",
    help=(
        "Override the mcp_server URL this agent connects to as an MCP "
        "client (configs/config_servers.json's 'main' entry), e.g. "
        "http://127.0.0.1:8010/mcp to point at a different host/port. "
        "Takes precedence over MCP_SERVER_URL. Set before mcp_upstream.connect() "
        "runs in main() below."
    ),
)
_args, _ = _parser.parse_known_args()
if _args.gateway:
    os.environ["AI_AGENT_GATEWAY"] = _args.gateway
if _args.mcp_url:
    os.environ["MCP_SERVER_URL"] = _args.mcp_url

# A supervised child (see supervisor.py) gets its agent file in
# AI_AGENT_FILE. Its provider/gateway/model must reach the env vars before
# agent_config is imported (the providers resolve them at import time), so
# this runs first. agent_spec imports nothing from this project.
from src.agents import agent_spec

if os.getenv("AI_AGENT_FILE"):
    try:
        agent_spec.apply_to_environ(agent_spec.current())
    except agent_spec.AgentSpecError as _exc:
        sys.stderr.write(f"\nai_agent cannot start - agent file error:\n  {_exc}\n\n")
        sys.exit(1)

import uvicorn
from mcp.server.fastmcp import Context, FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

# agent_config resolves provider/key/role/config files at import time and
# raises on a bad value; show that as one clean line instead of a traceback.
# Anything else (a real bug, ImportError...) still propagates untouched.
_CONFIG_ERROR_NAMES = {"AgentConfigError", "AgentRoleError", "ConfigError", "AgentSpecError"}
try:
    from src.agents import agent_config, agent_events, agent_registry, agent_store
    from src.core import approvals, internal_auth, questions, usage_log
    from src.mcp_client import mcp_upstream
    from src.llm.base_provider import ChatCancelled
    from src.llm import model_tiers
    from src.llm import reasoning_effort as effort_limits
    from src.llm.model_limits import context_window_for

    # Parsed here so a malformed `models` block is a clean one-line exit.
    _OWN_TIERS = model_tiers.as_records(model_tiers.own_tiers())
    _OWN_EFFORTS = list(effort_limits.own_efforts())
except Exception as _exc:
    if not (isinstance(_exc, (FileNotFoundError, ValueError)) or type(_exc).__name__ in _CONFIG_ERROR_NAMES):
        raise
    sys.stderr.write(f"\nai_agent cannot start - configuration error:\n  {_exc}\n\n")
    sys.exit(1)

HOST = os.getenv("AI_AGENT_HOST", "127.0.0.1")
PORT = int(os.getenv("AI_AGENT_PORT", "9100"))



def _agent_url(host: str, port: int, advertise: str | None) -> str:
    """The URL this instance registers under (see register()/deregister()
    below): one a peer can actually connect to. AI_AGENT_ADVERTISE_URL
    ("http://10.0.0.5", no path) names it when peers are on another machine;
    without a port in it this instance's own port is added, so one value
    serves every supervised agent. Without it HOST is used, and a bind-all
    address (0.0.0.0), which isn't itself reachable, falls back to loopback.
    Raises ValueError for an advertise value that is not an http(s) origin."""
    if advertise:
        value = advertise.strip()
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.netloc or parts.path not in ("", "/") or parts.query or parts.fragment:
            raise ValueError(
                f"AI_AGENT_ADVERTISE_URL must be an http(s) address with no path, like http://10.0.0.5; got {advertise!r}"
            )
        origin = f"{parts.scheme}://{parts.netloc}"
        return f"{origin}/mcp" if parts.port else f"{origin}:{port}/mcp"
    return f"http://{host if host not in ('0.0.0.0', '') else '127.0.0.1'}:{port}/mcp"


SPEC = agent_spec.current()
_AGENT_ID = SPEC.id
# An env-var instance has no label of its own: keep today's "<vendor> Agent".
_AGENT_LABEL = SPEC.label or f"{agent_config.status()['vendor_label']} Agent"
try:
    # The agent file's own `url` wins over the host/port/env derived one.
    _AGENT_URL = SPEC.url or _agent_url(HOST, PORT, os.getenv("AI_AGENT_ADVERTISE_URL"))
except ValueError as _exc:
    sys.stderr.write(f"\nai_agent cannot start - configuration error:\n  {_exc}\n\n")
    sys.exit(1)

mcp = FastMCP(
    name=f"ai-agent-{_AGENT_ID}",
    instructions=(
        f"Chat agent backed by {agent_config.PROVIDER_ID} "
        f"({agent_config.MODEL or 'provider default'}), with tool access to "
        "mcp_server. Call ask() with a question."
    ),
    host=HOST,
    port=PORT,
)


def _request_headers(ctx: Context | None) -> Any:
    """The HTTP headers of the request this tool call arrived on, or None
    (no ctx, or a transport without HTTP requests)."""
    if ctx is None:
        return None
    try:
        request = ctx.request_context.request
    except ValueError:
        return None
    return getattr(request, "headers", None)


def _cancelled_result() -> dict[str, Any]:
    """Same shape ask() returns for a normal turn, so chat_app's client
    doesn't need a separate code path - just a "⏹️ Cancelled." response
    with no tool activity. This is a normal (non-error) structured
    result: the user hitting Stop is an expected action, not a failure,
    matching chat_app's own pre-migration ChatCancelled handling."""
    return {
        "response": "⏹️ Cancelled.",
        "tools_used": [],
        "tool_calls": [],
        "total_tokens": None,
        "context_tokens": None,
        "context_window": agent_config.status()["context_window"],
        "provider_id": agent_config.PROVIDER_ID,
        "model": agent_config.MODEL or agent_config.status()["model"],
        "cancelled": True,
    }


@mcp.tool()
async def ask(
    question: str,
    history: list[dict[str, Any]] | None = None,
    enabled_extensions: list[str] | None = None,
    request_id: str | None = None,
    depth: int = 0,
    caveman: bool = False,
    approval_mode: str = "off",
    allowed_tools: list[str] | None = None,
    delegated_by: str | None = None,
    disabled_tools: list[str] | None = None,
    private_extensions: list[dict[str, Any]] | None = None,
    model_tier: str | None = None,
    reasoning_effort: str | None = None,
    ask_user: bool = False,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Ask this agent a question. Runs its own tool-calling loop against
    mcp_server (up to max_tool_rounds from config_tuning.json) before returning a final answer.
    request_id, if given, can be passed to cancel() to stop this turn
    cooperatively before its next round. depth is set only by a
    delegating peer's own delegate_to_agent call (see delegation.py) -
    chat_app never sets it, so it defaults to 0 for every top-level call.
    caveman appends terse-reply instructions to the system prompt for this
    turn only.
    approval_mode: "off" (default), "ask" (the user answers, through
    decide(), before each tool not in allowed_tools runs) or "deny" (such
    tools are refused; a delegating agent's sub-agent gets this).
    delegated_by: the orchestrator's agent id when another agent delegated
    this question (see delegation.py); recorded in usage rows.
    disabled_tools: mcp_server tool names the asking user switched off for
    their own chats; this turn neither offers nor runs them (core/tool_filter.py).
    private_extensions: the user's own MCP servers for this turn,
    `[{id, label, url, headers}]`; see src/private_extensions/.
    model_tier: the strength of model to run this turn on ("light",
    "standard" or "heavy"), set by a delegating orchestrator. This agent
    resolves it against its own gateway tiers and min_tier/max_tier, so a
    request outside the cap runs on the nearest allowed tier; the result
    then carries `model_tier` and, when changed, `model_note`.
    reasoning_effort: how hard to reason this turn ("off", "low", "medium"
    or "high"), set by a delegating orchestrator. It is capped at this
    agent's llm.max_effort, so a request above the cap runs at the cap; the
    result then carries `reasoning_effort` and, when changed, `effort_note`.
    ask_user: the caller can show the user clickable questions and send their
    answers back through answer_question(); only then is the ask_user tool
    offered (top-level turns only).
    ctx, if the MCP client requested it, is FastMCP's injected Context -
    used below only to relay run_chat's live step/token events as MCP
    progress notifications; chat_app's own tool call never needs to pass
    it explicitly, FastMCP supplies it automatically per request."""

    async def on_event(event: dict[str, Any]) -> None:
        # progress/total are left at 0/None - chat_app's client reads
        # only the message string (a JSON-encoded event dict), not a
        # percentage, so there's nothing meaningful to report there.
        # ctx is None when this agent is called directly (tests, or an
        # MCP client that didn't request progress) - a no-op then,
        # since run_chat's on_event is always invoked either way.
        if ctx is not None:
            await ctx.report_progress(0, None, json.dumps(agent_events.stamp(event, _AGENT_ID, _AGENT_LABEL)))

    # The asking user, from ember_api's / chat_app's identity headers; every
    # mcp_server tool this turn calls carries it on (see internal_auth.py).
    started_at = agent_events.now_iso()
    requester_token = internal_auth.bind_requester(internal_auth.Requester.from_headers(_request_headers(ctx)))
    try:
        tier_args = {"model_tier": model_tier} if model_tier else {}
        if reasoning_effort:
            tier_args["reasoning_effort"] = reasoning_effort
        private_args = {"private_extensions": private_extensions} if private_extensions else {}
        result = await agent_config.run_chat(
            question, history or [], enabled_extensions or [], request_id, depth,
            on_event=on_event, caveman=caveman, approval_mode=approval_mode, allowed_tools=allowed_tools,
            disabled_tools=disabled_tools, ask_user=ask_user, **tier_args, **private_args,
        )
    except ChatCancelled:
        return _cancelled_result()
    finally:
        internal_auth.reset_requester(requester_token)
    own_usage = usage_log.own_row(
        result, agent_id=_AGENT_ID, agent_label=_AGENT_LABEL, gateway=SPEC.effective_gateway(),
        started_at=started_at, finished_at=agent_events.now_iso(), delegated_by=delegated_by,
        model_tier=result.model_tier, reasoning_effort=result.reasoning_effort,
    )
    await usage_log.append({**own_usage, "request_id": request_id, "depth": depth})
    reply = {
        "response": result.response,
        "tools_used": result.tools_used,
        "tool_calls": [
            {"name": c.name, "arguments": c.arguments, "result": c.result} for c in result.tool_calls
        ],
        "total_tokens": result.total_tokens,
        # Own usage first, then every delegated agent's, so callers can
        # break tokens down per agent (who, which provider/gateway, when).
        "agent_usage": [own_usage, *result.delegated_usage],
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "context_tokens": result.context_tokens,
        "context_window": agent_config.status()["context_window"],
        "provider_id": result.provider_id,
        "model": result.model,
        "cancelled": False,
    }
    if result.model_tier:
        # The tier model's own window, not the pinned model's.
        reply["context_window"] = context_window_for(result.model)
        reply["model_tier"] = result.model_tier
    if result.model_note:
        reply["model_note"] = result.model_note
    if result.reasoning_effort:
        reply["reasoning_effort"] = result.reasoning_effort
    if result.effort_note:
        reply["effort_note"] = result.effort_note
    errors = getattr(result, "private_extension_errors", None)
    if errors:
        reply["private_extension_errors"] = errors
    return reply


@mcp.custom_route("/registry", methods=["GET"])
async def registry(_request: Request) -> JSONResponse:
    """The agent registry (the same JSON as .data/agent_registry.json), so
    ember_api can find agents by URL instead of by file path, plus `defined`:
    every agent in agents/ (running or not, from agent_definitions.json). Behind the
    internal token like /mcp (see internal_auth.PROTECTED_PATHS)."""
    await asyncio.to_thread(agent_registry.reload)
    defined = await asyncio.to_thread(agent_registry.read_definitions)
    return JSONResponse({"agents": agent_registry.all_agents(), "defined": defined})


def _store_error(error: agent_store.AgentStoreError) -> JSONResponse:
    return JSONResponse({"error": str(error)}, status_code=error.status)


async def _json_object(request: Request) -> dict[str, Any] | None:
    try:
        body = await request.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


@mcp.custom_route("/agents/gateways", methods=["GET"])
async def agent_gateways(_request: Request) -> JSONResponse:
    """Providers and their gateways, for the admin UI's pickers."""
    try:
        return JSONResponse({"providers": await asyncio.to_thread(agent_store.gateway_catalog)})
    except agent_store.AgentStoreError as error:
        return _store_error(error)


@mcp.custom_route("/agents/files", methods=["GET"])
async def agent_files_list(_request: Request) -> JSONResponse:
    """Every agents/<id>.json. The supervisor applies changes within seconds."""
    return JSONResponse({"agents": await asyncio.to_thread(agent_store.list_agents)})


@mcp.custom_route("/agents/files", methods=["POST"])
async def agent_files_create(request: Request) -> JSONResponse:
    """Body: {"id": "...", "config": {...agent file...}}."""
    body = await _json_object(request)
    config = body.get("config") if body else None
    if body is None or not isinstance(config, dict):
        return JSONResponse({"error": "body must be {\"id\": ..., \"config\": {...}}"}, status_code=400)
    try:
        created = await asyncio.to_thread(agent_store.create_agent, body.get("id"), config)
    except agent_store.AgentStoreError as error:
        return _store_error(error)
    return JSONResponse(created, status_code=201)


@mcp.custom_route("/agents/files/{agent_id}", methods=["GET"])
async def agent_files_get(request: Request) -> JSONResponse:
    try:
        return JSONResponse(await asyncio.to_thread(agent_store.get_agent, request.path_params["agent_id"]))
    except agent_store.AgentStoreError as error:
        return _store_error(error)


@mcp.custom_route("/agents/files/{agent_id}", methods=["PUT"])
async def agent_files_update(request: Request) -> JSONResponse:
    """Body: the whole agent file (replaces the old one)."""
    config = await _json_object(request)
    if config is None:
        return JSONResponse({"error": "body must be a JSON object"}, status_code=400)
    try:
        return JSONResponse(await asyncio.to_thread(agent_store.update_agent, request.path_params["agent_id"], config))
    except agent_store.AgentStoreError as error:
        return _store_error(error)


@mcp.custom_route("/agents/files/{agent_id}", methods=["DELETE"])
async def agent_files_delete(request: Request) -> JSONResponse:
    try:
        await asyncio.to_thread(agent_store.delete_agent, request.path_params["agent_id"])
    except agent_store.AgentStoreError as error:
        return _store_error(error)
    return JSONResponse({"deleted": request.path_params["agent_id"]})


@mcp.custom_route("/agents/prompts", methods=["GET"])
async def agent_prompts_get(_request: Request) -> JSONResponse:
    """The shared prompt texts every agent's system prompt is built from."""
    return JSONResponse(await asyncio.to_thread(agent_store.get_prompts))


@mcp.custom_route("/agents/prompts", methods=["PUT"])
async def agent_prompts_put(request: Request) -> JSONResponse:
    """Body: {key: text | null}; null (or blank) resets a text to its default.
    The supervisor restarts every agent to apply it."""
    changes = await _json_object(request)
    if changes is None:
        return JSONResponse({"error": "body must be a JSON object"}, status_code=400)
    try:
        return JSONResponse(await asyncio.to_thread(agent_store.set_prompts, changes))
    except agent_store.AgentStoreError as error:
        return _store_error(error)


@mcp.custom_route("/agents/prompt-preview", methods=["POST"])
async def agent_prompt_preview(request: Request) -> JSONResponse:
    """Body: {"id": ..., "config": {...draft agent file...}, "caveman": false}
    -> {"prompt": the assembled system prompt}."""
    body = await _json_object(request)
    config = body.get("config") if body else None
    if body is None or not isinstance(config, dict):
        return JSONResponse({"error": "body must be {\"id\": ..., \"config\": {...}}"}, status_code=400)
    try:
        prompt = await asyncio.to_thread(
            agent_store.preview_prompt, body.get("id"), config, body.get("caveman") is True
        )
    except agent_store.AgentStoreError as error:
        return _store_error(error)
    return JSONResponse({"prompt": prompt})


@mcp.tool()
def interpret(text: str) -> dict[str, Any]:
    """One completion over `text` - no tool-calling loop, no tool calls
    offered. Used by chat_app's summarization (see services/summarization.py)
    for a plain prompt-in, text-out step; `ask()` remains what a free-form
    chat question goes through, tool selection and all."""
    started_at = agent_events.now_iso()
    result = agent_config.run_interpret(text)
    own_usage = usage_log.own_row(
        result, agent_id=_AGENT_ID, agent_label=_AGENT_LABEL, gateway=SPEC.effective_gateway(),
        started_at=started_at, finished_at=agent_events.now_iso(), delegated_by=None,
    )
    return {
        "response": result.response,
        "provider_id": result.provider_id,
        "model": result.model,
        "total_tokens": result.total_tokens,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        # Same shape as ask(), so the caller books this call under this agent.
        "agent_usage": [own_usage],
        "context_tokens": result.context_tokens,
        "context_window": agent_config.status()["context_window"],
    }


@mcp.tool()
def status() -> dict[str, Any]:
    """Live availability of this agent's pinned provider. `tool_approval`
    says ask() understands approval_mode, so a caller that needs tools asked
    about can refuse an agent that would ignore it; `tool_filter` says the same
    of disabled_tools; `user_questions` says ask() understands ask_user;
    `private_extensions` says ask() understands private_extensions."""
    return {
        **agent_config.status(),
        "tool_approval": True,
        "tool_filter": True,
        "tool_filter_all": True,
        "user_questions": True,
        # laya answers typed questions locally and never lists tools through mcp_upstream.
        "private_extensions": agent_config.PROVIDER_ID != "laya",
    }


@mcp.tool()
async def probe_extension(url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    """Connect once to the MCP server at `url` (with `headers`, which may carry
    a secret) and report `{status, error, tools}`. Used by ember_api when a user
    adds or edits a private extension. Never raises; the error is short and
    never contains a header value."""
    return await mcp_upstream.probe_private(url, headers)


@mcp.tool()
async def decide(request_id: str, step_id: str, decision: str) -> dict[str, Any]:
    """Answers a tool-approval request an ask() call in "ask" mode raised
    (an `approval_request` event): decision is "allow", "always" (allow, and
    stop asking for this tool for the rest of the turn) or "deny". Returns
    {"decided": False} when nothing is waiting for that request and step -
    unknown, already answered, or the turn ended."""
    return {"decided": approvals.BROKER.decide(request_id, step_id, decision)}


@mcp.tool()
async def answer_question(
    request_id: str,
    step_id: str,
    answers: list[dict[str, Any]] | None = None,
    skipped: bool = False,
) -> dict[str, Any]:
    """Answers the questions an ask() call raised with a `question_request`
    event: `answers` has one entry per question, in order, each
    {"selected": [option labels], "other": typed text or null}; or pass
    skipped=True to decline. Returns {"answered": False} when nothing is
    waiting for that request and step - unknown, already answered, or the
    turn ended."""
    return {"answered": questions.BROKER.answer(request_id, step_id, answers or [], skipped)}


@mcp.tool()
def cancel(request_id: str) -> dict[str, Any]:
    """Cooperatively cancel an in-flight ask() call with this request_id
    on this agent instance. Best-effort: an unknown/already-finished id
    is not an error, just a no-op (cancelled: False)."""
    return {"cancelled": agent_config.cancel(request_id)}


def main() -> None:
    if agent_config.PROVIDER_ID == "laya":
        from src.llm import laya_provider

        laya_provider.prepare()
    else:
        mcp_upstream.connect()
        mcp_upstream.warn_unmatched_tool_globs()
    agent_registry.register(
        _AGENT_ID, _AGENT_LABEL, _AGENT_URL,
        entry=SPEC.entry, orchestrator=SPEC.orchestrator, focus=SPEC.focus,
        tiers=_OWN_TIERS, efforts=_OWN_EFFORTS,
    )
    try:
        # Same app, host, port and log level mcp.run(transport="streamable-http")
        # would use, built explicitly so middleware can be added here. No CORS:
        # only servers call this agent (chat_app directly, ember_web's browser
        # via ember_api's proxy), never a browser - which is also why /mcp
        # can require the shared internal token (once one is configured).
        app = mcp.streamable_http_app()
        app.add_middleware(internal_auth.InternalTokenMiddleware, token=internal_auth.TOKEN)
        if not internal_auth.TOKEN:
            print("ai_agent: /mcp has no auth - set INTERNAL_API_TOKEN in .env", flush=True)
        uvicorn.run(app, host=HOST, port=PORT, log_level=mcp.settings.log_level.lower())
    finally:
        agent_registry.deregister(_AGENT_ID)
        if agent_config.PROVIDER_ID != "laya":
            mcp_upstream.close()


if __name__ == "__main__":
    main()
