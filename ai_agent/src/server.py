"""ai_agent entry point - a FastMCP server exposing ask/status/cancel
tools to chat_app, backed by one pinned LLM provider (agent_config.py)
that itself talks to mcp_server as an MCP client (mcp_upstream.py).

Run with:
    python -m src.server
    python -m src.server --gateway openrouter
    python -m src.server --role ops_specialist
    python -m src.server --mcp-url http://127.0.0.1:8010/mcp
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument(
    "--gateway",
    help=(
        "Override this run's gateway block (configs/config_llms.json), "
        "e.g. openrouter/bedrock/vertex/litellm/helicone/portkey for "
        "anthropic, or azure/together/groq/fireworks/deepinfra/"
        "perplexity/ollama/vllm for openai. Takes precedence over "
        "AI_AGENT_GATEWAY. Set before importing "
        "agent_config, since the provider resolves its client/default "
        "model from the gateway at import time."
    ),
)
_parser.add_argument(
    "--role",
    help=(
        "Override this run's persona role (configs/config_ai_agent_roles.json), "
        "e.g. ops_specialist. Takes precedence over AI_AGENT_ROLE. Set "
        "before importing agent_config, since agent_roles resolves "
        "SYSTEM_PROMPT from the role at import time, same as --gateway "
        "above."
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
if _args.role:
    os.environ["AI_AGENT_ROLE"] = _args.role
if _args.mcp_url:
    os.environ["MCP_SERVER_URL"] = _args.mcp_url

from mcp.server.fastmcp import Context, FastMCP

from src import agent_config, agent_registry, mcp_upstream
from src.llm.base_provider import ChatCancelled

HOST = os.getenv("AI_AGENT_HOST", "127.0.0.1")
PORT = int(os.getenv("AI_AGENT_PORT", "9100"))

# HOST may be a bind-all address (0.0.0.0) that isn't itself reachable -
# the URL this instance registers under (see register()/deregister()
# below) needs an address a peer on the same machine can actually
# connect to, so it falls back to loopback rather than publishing 0.0.0.0.
_AGENT_ID = agent_registry.agent_id_for(agent_config.PROVIDER_ID)
_AGENT_URL = f"http://{HOST if HOST not in ('0.0.0.0', '') else '127.0.0.1'}:{PORT}/mcp"

mcp = FastMCP(
    name=f"ai-agent-{agent_config.PROVIDER_ID}",
    instructions=(
        f"Chat agent backed by {agent_config.PROVIDER_ID} "
        f"({agent_config.MODEL or 'provider default'}), with tool access to "
        "mcp_server. Call ask() with a question."
    ),
    host=HOST,
    port=PORT,
)


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
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Ask this agent a question. Runs its own tool-calling loop against
    mcp_server (up to max_tool_rounds from config_token_limits.json) before returning a final answer.
    request_id, if given, can be passed to cancel() to stop this turn
    cooperatively before its next round. depth is set only by a
    delegating peer's own delegate_to_agent call (see delegation.py) -
    chat_app never sets it, so it defaults to 0 for every top-level call.
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
            await ctx.report_progress(0, None, json.dumps(event))

    try:
        result = await agent_config.run_chat(
            question, history or [], enabled_extensions or [], request_id, depth,
            on_event=on_event,
        )
    except ChatCancelled:
        return _cancelled_result()
    return {
        "response": result.response,
        "tools_used": result.tools_used,
        "tool_calls": [
            {"name": c.name, "arguments": c.arguments, "result": c.result} for c in result.tool_calls
        ],
        "total_tokens": result.total_tokens,
        "context_tokens": result.context_tokens,
        "context_window": agent_config.status()["context_window"],
        "provider_id": result.provider_id,
        "model": result.model,
        "cancelled": False,
    }


@mcp.tool()
def interpret(text: str) -> dict[str, Any]:
    """One completion over `text` - no tool-calling loop, no tool calls
    offered. Used by chat_app's summarization (see services/summarization.py)
    for a plain prompt-in, text-out step; `ask()` remains what a free-form
    chat question goes through, tool selection and all."""
    result = agent_config.run_interpret(text)
    return {
        "response": result.response,
        "provider_id": result.provider_id,
        "model": result.model,
        "total_tokens": result.total_tokens,
        "context_tokens": result.context_tokens,
        "context_window": agent_config.status()["context_window"],
    }


@mcp.tool()
def status() -> dict[str, Any]:
    """Live availability of this agent's pinned provider."""
    return agent_config.status()


@mcp.tool()
def cancel(request_id: str) -> dict[str, Any]:
    """Cooperatively cancel an in-flight ask() call with this request_id
    on this agent instance. Best-effort: an unknown/already-finished id
    is not an error, just a no-op (cancelled: False)."""
    return {"cancelled": agent_config.cancel(request_id)}


def main() -> None:
    mcp_upstream.connect()
    agent_registry.register(_AGENT_ID, f"{agent_config.status()['vendor_label']} Agent", _AGENT_URL)
    try:
        mcp.run(transport="streamable-http")
    finally:
        agent_registry.deregister(_AGENT_ID)
        mcp_upstream.close()


if __name__ == "__main__":
    main()
