"""Turns a domain result into a chat-readable ``CallToolResult``.

FastMCP's default conversion (``mcp.server.fastmcp.utilities.func_metadata
._convert_to_content``) runs any non-``str`` return value through
``pydantic_core.to_json`` to build the tool call's visible text - which
would make every call here show up as a raw JSON blob in chat_app's Chat
page, even though every ``contract.py`` result already carries a
``report`` or ``message`` field written specifically to be relayed to a
person verbatim.

``respond()`` is what actually makes a tool return that field as the
visible text instead of the JSON envelope around it, while still
attaching the full typed result as ``structuredContent`` for a client
that wants to parse it. Ported verbatim from mcp_server's own
``tool_response.py`` - see that project if this one's copy ever needs
updating in lockstep.
"""

from __future__ import annotations

from typing import Any

from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel


def respond(result: BaseModel) -> CallToolResult:
    """Wrap a domain result for return from a tool function.

    Visible text is ``result.report`` or ``result.message`` when the
    model has one. Falls back to one ``field: value`` line per field for
    a result with neither, so nothing ever regresses to a JSON dump. The
    tool function's own return-type annotation should stay the result
    model (e.g. ``-> WorldStatusResult``), not ``CallToolResult`` -
    FastMCP builds the advertised output schema from that annotation and
    separately validates ``structuredContent`` against it at call time.
    """
    if hasattr(result, "report"):
        text = result.report
    elif hasattr(result, "message"):
        text = result.message
    else:
        text = _fallback_text(result)

    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structuredContent=result.model_dump(mode="json", by_alias=True),
    )


def _fallback_text(result: BaseModel) -> str:
    dumped = result.model_dump(mode="json", by_alias=True)
    lines = [f"{field}: {_render_value(value)}" for field, value in dumped.items()]
    return "\n".join(lines) if lines else "(no output)"


def _render_value(value: Any) -> str:
    if isinstance(value, list):
        if not value:
            return "(none)"
        return "".join(f"\n  - {_render_value(item)}" for item in value)
    if isinstance(value, dict):
        if not value:
            return "(none)"
        return "".join(f"\n  {key}: {_render_value(val)}" for key, val in value.items())
    return str(value)
