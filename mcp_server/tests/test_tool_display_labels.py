"""Regression coverage: every tool declares `meta["display_label"]`,
consumed by chat_app's live tool-call trace (see
docs/superpowers/specs/2026-09-13-live-agent-trace-streaming-design.md). Uses
the real `src.server.mcp` FastMCP instance - importing each tool
module is what runs its @mcp.tool() decorator and registers it there.
"""

from __future__ import annotations

import pytest

from src.capabilities.server_manager import tool as server_manager_tool  # noqa: F401
from src.server import mcp


@pytest.mark.anyio
async def test_every_tool_has_a_display_label():
    """Every tool must have a display_label in meta."""
    tools = await mcp.list_tools()
    by_name = {t.name: t for t in tools}

    # Tools: they have keywords in their meta
    keyworded_tools = {
        name: tool for name, tool in by_name.items()
        if (tool.meta or {}).get("keywords")
    }

    assert keyworded_tools, "no tools registered"

    missing = [
        name for name, tool in keyworded_tools.items()
        if not (tool.meta or {}).get("display_label")
    ]

    assert missing == [], f"tools missing display_label: {missing}"
