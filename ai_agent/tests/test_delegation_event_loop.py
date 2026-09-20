import anyio
import pytest

from src import delegation


@pytest.mark.anyio
async def test_call_works_when_dispatched_from_a_running_event_loop(monkeypatch):
    async def fake_call_tool(url, name, arguments):
        return {"response": "delegated answer"}

    monkeypatch.setattr(delegation.agent_registry, "get_agent", lambda agent_id: {"url": "http://x/mcp"})
    monkeypatch.setattr(delegation, "_call_tool", fake_call_tool)

    result = await anyio.to_thread.run_sync(delegation.call, "openai-agent", "q", 0)

    assert result == "delegated answer"
