"""AgentDirectory: reads ai_agent's registry, including the optional entry /
orchestrator / focus keys, and picks the entry agent with its fallbacks."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from src.services import agent_directory
from src.services.agent_directory import LEGACY_ENTRY_ID, NO_AGENT_RUNNING, AgentDirectory, HttpRegistrySource


def directory(tmp_path: Path, agents: list[dict]) -> AgentDirectory:
    path = tmp_path / "config_agents.json"
    path.write_text(json.dumps({"agents": agents}), encoding="utf-8")
    return AgentDirectory(path)


def agent(agent_id: str, **extra) -> dict:
    return {"id": agent_id, "label": agent_id.title(), "url": f"http://{agent_id}/mcp", **extra}


def test_no_agent_running_message_is_the_one_the_routes_use() -> None:
    assert NO_AGENT_RUNNING == "No agent is running"


def test_entries_without_the_new_keys_read_as_plain_agents(tmp_path: Path) -> None:
    found = asyncio.run(directory(tmp_path, [agent("old")]).all())

    assert found[0].entry is False
    assert found[0].orchestrator is False
    assert found[0].focus == ""


def test_new_keys_are_read(tmp_path: Path) -> None:
    found = asyncio.run(
        directory(tmp_path, [agent("main", entry=True, orchestrator=True, focus="Coordinates.")]).all()
    )

    assert (found[0].entry, found[0].orchestrator, found[0].focus) == (True, True, "Coordinates.")


def test_bad_types_for_the_new_keys_fall_back_to_defaults(tmp_path: Path) -> None:
    found = asyncio.run(directory(tmp_path, [agent("odd", entry="yes", orchestrator=1, focus=5)]).all())

    assert (found[0].entry, found[0].orchestrator, found[0].focus) == (False, False, "")


def test_entry_prefers_the_flagged_agent(tmp_path: Path) -> None:
    d = directory(tmp_path, [agent("claude-agent"), agent("orch", orchestrator=True), agent("main", entry=True)])

    assert asyncio.run(d.entry()).id == "main"


def test_entry_falls_back_to_the_first_orchestrator(tmp_path: Path) -> None:
    d = directory(tmp_path, [agent("claude-agent"), agent("orch", orchestrator=True)])

    assert asyncio.run(d.entry()).id == "orch"


def test_entry_falls_back_to_the_legacy_agent(tmp_path: Path) -> None:
    d = directory(tmp_path, [agent("other"), agent(LEGACY_ENTRY_ID)])

    assert asyncio.run(d.entry()).id == LEGACY_ENTRY_ID


def test_entry_is_none_when_nothing_qualifies_or_the_file_is_missing(tmp_path: Path) -> None:
    assert asyncio.run(directory(tmp_path, [agent("other")]).entry()) is None
    assert asyncio.run(AgentDirectory(tmp_path / "missing.json").entry()) is None


# --- URL source (ai_agent GET /registry) ---


def http_directory(handler, token: str | None = None) -> tuple[AgentDirectory, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return AgentDirectory(HttpRegistrySource("http://agents.test/registry", client, token)), client


def test_the_url_source_lists_the_agents_and_sends_the_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"agents": [agent("main", entry=True)]})

    async def run():
        d, client = http_directory(handler, token="s3cret")
        try:
            return await d.entry()
        finally:
            await client.aclose()

    found = asyncio.run(run())

    assert found.id == "main"
    assert seen[0].headers["X-Internal-Token"] == "s3cret"


def test_the_url_source_sends_no_token_header_when_none_is_configured() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"agents": []})

    async def run():
        d, client = http_directory(handler)
        try:
            await d.all()
        finally:
            await client.aclose()

    asyncio.run(run())

    assert "X-Internal-Token" not in seen[0].headers


def test_the_url_source_caches_for_a_few_seconds() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"agents": [agent("main")]})

    async def run():
        d, client = http_directory(handler)
        try:
            await d.all()
            await d.all()
        finally:
            await client.aclose()

    asyncio.run(run())

    assert len(calls) == 1


def test_the_url_source_is_empty_on_a_refusal_or_a_bad_body() -> None:
    for response in (httpx.Response(401, json={"error": "no"}), httpx.Response(200, text="not json")):

        async def run(response=response):
            d, client = http_directory(lambda request: response)
            try:
                return await d.all()
            finally:
                await client.aclose()

        assert asyncio.run(run()) == []


def test_the_url_source_keeps_the_last_good_list_when_the_agent_stops_answering(monkeypatch) -> None:
    clock = [1000.0]
    monkeypatch.setattr(agent_directory.time, "monotonic", lambda: clock[0])
    up = [True]

    def handler(request: httpx.Request) -> httpx.Response:
        if up[0]:
            return httpx.Response(200, json={"agents": [agent("main")]})
        raise httpx.ConnectError("down")

    async def run():
        d, client = http_directory(handler)
        try:
            first = await d.all()
            up[0] = False
            clock[0] += agent_directory._CACHE_SECONDS + 1
            stale = await d.all()
            clock[0] += agent_directory._STALE_SECONDS + 1
            expired = await d.all()
            return first, stale, expired
        finally:
            await client.aclose()

    first, stale, expired = asyncio.run(run())

    assert [a.id for a in first] == ["main"]
    assert [a.id for a in stale] == ["main"]
    assert expired == []
