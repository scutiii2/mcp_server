"""delegate_to_agent - lets one ai_agent instance hand a focused
sub-question to another configured instance (or itself) mid-loop.

Not every "subagent" needs a new ai_agent process: delegating to a
different already-running instance, or to itself for a fresh,
unpolluted sub-conversation, both go through this one generic tool.
A genuinely distinct specialized subagent (its own system prompt/tool
scope/model) is still a new ai_agent instance - this module is what lets
any instance reach one once it exists, including itself.

Isolated from both provider files so neither claude_provider.py nor
openai_provider.py duplicates the tool-schema/dispatch logic - each just
calls is_available()/tool_description()/TOOL_PARAMETERS/call() from here.

Cancellation is NOT propagated into a delegated call: chat_app's Stop
button only knows the top-level agent's request_id/URL, with no
visibility into a nested delegate call. A delegated call always passes
request_id=None (cancellation.py already treats a falsy id as
"uncancellable") - a documented limitation, not a bug.
"""

from __future__ import annotations

import asyncio
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from src import agent_registry

TOOL_NAME = "delegate_to_agent"

# Each hop is itself a full up-to-6-round ask() call, so this bounds a
# worst case that's real but not tiny. 2 hops makes a genuine multi-step
# handoff possible (A -> B -> C, or A -> B -> A) without allowing
# unbounded fan-out or a delegation cycle running forever.
_MAX_DELEGATION_DEPTH = 2

TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "agent_id": {"type": "string", "description": "Which configured agent to delegate to."},
        "question": {"type": "string", "description": "The focused sub-question to ask it."},
    },
    "required": ["agent_id", "question"],
}


def is_available() -> bool:
    return bool(agent_registry.all_agents())


def tool_description() -> str:
    agents = agent_registry.all_agents()
    listing = ", ".join(f"{a['id']} ({a['label']})" for a in agents)
    return (
        f"Delegate a focused sub-question to another configured agent: {listing}. "
        "Useful for a fresh, unpolluted sub-conversation or a different model's "
        "perspective - not for parallelism, this is a sequential call that adds latency."
    )


async def _call_tool(url: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    # Same shape as chat_app/src/services/ai_agent_client.py's _call_tool,
    # including its fix: raise only AFTER both async with blocks exit,
    # never inside them - an exception raised while either is still open
    # gets wrapped in a BaseExceptionGroup by anyio on unwind, which the
    # caller's plain `except Exception` would then fail to stringify
    # usefully.
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments)

    if result.isError:
        parts = [getattr(block, "text", str(block)) for block in result.content]
        raise RuntimeError("\n".join(parts) if parts else f"{name} failed")
    return result.structuredContent or {}


def call(agent_id: str, question: str, depth: int) -> str:
    if depth >= _MAX_DELEGATION_DEPTH:
        raise ValueError(f"max delegation depth ({_MAX_DELEGATION_DEPTH}) reached")

    agent = agent_registry.get_agent(agent_id)
    if agent is None:
        configured = ", ".join(agent_registry.list_agent_ids()) or "(none configured)"
        raise ValueError(f"unknown agent_id {agent_id!r} - configured agents: {configured}")

    result = asyncio.run(
        _call_tool(
            agent["url"],
            "ask",
            {
                "question": question,
                "history": [],
                "enabled_extensions": [],
                "request_id": None,
                "depth": depth + 1,
            },
        )
    )
    return result.get("response", "")
