"""Regression coverage: every built-in tool declares `meta["keywords"]`,
consumed by chat_app's staged-pipeline tool filter (see
docs/superpowers/specs/2026-08-17-ollama-staged-pipeline-design.md). Uses
the real `mcp_server.server.mcp` FastMCP instance - importing each tool
module is what runs its @mcp.tool() decorator and registers it there (see
run.py's own comment on why these imports "look unused").
"""

from __future__ import annotations

import pytest

from mcp_server.capabilities.host_health import tool as host_health_tool  # noqa: F401
from mcp_server.capabilities.otp import tool as otp_tool  # noqa: F401
from mcp_server.server import mcp


@pytest.mark.anyio
async def test_every_built_in_tool_declares_keywords():
    tools = await mcp.list_tools()
    by_name = {t.name: t for t in tools}

    for name in ("get_host_health_tool", "request_otp_tool", "verify_otp_tool"):
        assert name in by_name, f"{name} not registered"
        meta = by_name[name].meta
        assert meta is not None and meta.get("keywords"), f"{name} has no declared keywords"
