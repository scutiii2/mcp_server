"""mcp_client.call_tool hands a tool's live progress messages to on_progress."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch

from src.services import mcp_client


class _FakeSession:
    def __init__(self, *_args):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def initialize(self):
        pass

    async def call_tool(self, name, arguments, progress_callback=None):
        if progress_callback:
            await progress_callback(1, None, "connecting")
            await progress_callback(2, None, None)  # no message: ignored
            await progress_callback(3, None, "reading log")
        return SimpleNamespace(content=[SimpleNamespace(text="result")])


@asynccontextmanager
async def _fake_transport(*_args, **_kwargs):
    yield (None, None, None)


def test_call_tool_delivers_progress_messages():
    seen: list[str] = []
    with patch.object(mcp_client, "streamablehttp_client", _fake_transport), patch.object(
        mcp_client, "ClientSession", _FakeSession
    ):
        result = mcp_client.call_tool("t", {}, on_progress=seen.append)

    assert result == "result"
    assert seen == ["connecting", "reading log"]


def test_call_tool_without_on_progress_passes_no_callback():
    with patch.object(mcp_client, "streamablehttp_client", _fake_transport), patch.object(
        mcp_client, "ClientSession", _FakeSession
    ):
        assert mcp_client.call_tool("t", {}) == "result"
