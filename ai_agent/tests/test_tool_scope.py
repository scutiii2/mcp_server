"""Per-agent tool scope (agents/<id>.json "tools"): out-of-scope tools are
never offered, refused if called anyway, and a glob matching nothing is
warned about once at startup."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src import agent_spec, mcp_upstream
from src.agent_spec import AgentSpec, LlmSpec, ToolScope


def _tool(name):
    return SimpleNamespace(name=name, description="", inputSchema={})


@pytest.fixture
def scoped(monkeypatch):
    spec = AgentSpec(id="calc", label="Calculator", port=9103, llm=LlmSpec(provider="anthropic"),
                     tools=ToolScope(allow=("calc_*",), deny=("calc_secret",)))
    monkeypatch.setattr(agent_spec, "_current", spec)


def test_list_tools_keeps_only_tools_in_scope(scoped):
    tools = [_tool("main__calc_add"), _tool("main__calc_secret"), _tool("main__weather_now")]
    with patch.object(mcp_upstream.client, "list_tools", return_value=tools):
        names = [t.name for t in mcp_upstream.list_tools()]
    assert names == ["main__calc_add"]


def test_call_tool_refuses_a_tool_out_of_scope(scoped):
    with patch.object(mcp_upstream.client, "call_tool") as call_tool:
        with pytest.raises(PermissionError, match="main__weather_now"):
            mcp_upstream.call_tool("main__weather_now", {})
    call_tool.assert_not_called()


def test_warn_unmatched_tool_globs(monkeypatch, caplog):
    spec = AgentSpec(id="calc", label="Calculator", port=9103, llm=LlmSpec(provider="anthropic"),
                     tools=ToolScope(allow=("calc_*", "convrt_*")))
    monkeypatch.setattr(agent_spec, "_current", spec)
    with patch.object(mcp_upstream.client, "list_tools", return_value=[_tool("main__calc_add")]), \
         caplog.at_level(logging.WARNING, logger="src.mcp_upstream"):
        mcp_upstream.warn_unmatched_tool_globs()
    assert "convrt_*" in caplog.text
    assert "calc_*" not in caplog.text


def test_unprefixed():
    assert mcp_upstream.unprefixed("main__calc_add") == "calc_add"
    assert mcp_upstream.unprefixed("other") == "other"
