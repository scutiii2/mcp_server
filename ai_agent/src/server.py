"""ai_agent entry point - a FastMCP server exposing ask/status/cancel
tools to chat_app, backed by one pinned LLM provider (agent_config.py)
that itself talks to mcp_server as an MCP client (mcp_upstream.py).

Run with:
    python -m src.server
"""

from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from src import agent_config, mcp_upstream
from src.llm.base import ChatCancelled

HOST = os.getenv("AI_AGENT_HOST", "127.0.0.1")
PORT = int(os.getenv("AI_AGENT_PORT", "9100"))

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
        "provider_id": agent_config.PROVIDER_ID,
        "model": agent_config.MODEL or agent_config.status()["model"],
        "cancelled": True,
    }


@mcp.tool()
def ask(
    question: str,
    history: list[dict[str, Any]] | None = None,
    enabled_extensions: list[str] | None = None,
    request_id: str | None = None,
    depth: int = 0,
) -> dict[str, Any]:
    """Ask this agent a question. Runs its own tool-calling loop against
    mcp_server (up to 6 rounds) before returning a final answer.
    request_id, if given, can be passed to cancel() to stop this turn
    cooperatively before its next round. depth is set only by a
    delegating peer's own delegate_to_agent call (see delegation.py) -
    chat_app never sets it, so it defaults to 0 for every top-level call."""
    try:
        result = agent_config.run_chat(question, history or [], enabled_extensions or [], request_id, depth)
    except ChatCancelled:
        return _cancelled_result()
    return {
        "response": result.response,
        "tools_used": result.tools_used,
        "tool_calls": [
            {"name": c.name, "arguments": c.arguments, "result": c.result} for c in result.tool_calls
        ],
        "total_tokens": result.total_tokens,
        "provider_id": result.provider_id,
        "model": result.model,
        "cancelled": False,
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
    try:
        mcp.run(transport="streamable-http")
    finally:
        mcp_upstream.close()


if __name__ == "__main__":
    main()
