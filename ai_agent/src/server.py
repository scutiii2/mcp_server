"""ai_agent entry point - a FastMCP server exposing ask/status tools to
chat_app, backed by one pinned LLM provider (agent_config.py) that
itself talks to mcp_server as an MCP client (mcp_upstream.py).

Run with:
    python -m src.server
"""

from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from src import agent_config, mcp_upstream

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


@mcp.tool()
def ask(
    question: str,
    history: list[dict[str, Any]] | None = None,
    enabled_extensions: list[str] | None = None,
) -> dict[str, Any]:
    """Ask this agent a question. Runs its own tool-calling loop against
    mcp_server (up to 6 rounds) before returning a final answer."""
    result = agent_config.run_chat(question, history or [], enabled_extensions or [])
    return {
        "response": result.response,
        "tools_used": result.tools_used,
        "tool_calls": [
            {"name": c.name, "arguments": c.arguments, "result": c.result} for c in result.tool_calls
        ],
        "total_tokens": result.total_tokens,
        "provider_id": result.provider_id,
        "model": result.model,
    }


@mcp.tool()
def status() -> dict[str, Any]:
    """Live availability of this agent's pinned provider."""
    return agent_config.status()


def main() -> None:
    mcp_upstream.connect()
    try:
        mcp.run(transport="streamable-http")
    finally:
        mcp_upstream.close()


if __name__ == "__main__":
    main()
