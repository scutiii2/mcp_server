"""Regression coverage: every built-in tool declares `meta["keywords"]`,
consumed by chat_app's staged-pipeline tool filter (see
docs/superpowers/specs/2026-08-17-ollama-staged-pipeline-design.md). Uses
the real `src.server.mcp` FastMCP instance - importing each tool
module is what runs its @mcp.tool() decorator and registers it there (see
run.py's own comment on why these imports "look unused").
"""

from __future__ import annotations

import pytest

from src.capabilities.server_manager import tool as server_manager_tool  # noqa: F401
from src.server import mcp


@pytest.mark.anyio
async def test_every_built_in_tool_declares_keywords():
    tools = await mcp.list_tools()
    by_name = {t.name: t for t in tools}

    assert by_name, "no tools registered"
    for name, tool in by_name.items():
        meta = tool.meta
        assert meta is not None and meta.get("keywords"), f"{name} has no declared keywords"
