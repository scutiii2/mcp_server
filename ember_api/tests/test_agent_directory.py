"""AgentDirectory: reads ai_agent's registry, including the optional entry /
orchestrator / focus keys, and picks the entry agent with its fallbacks."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from src.services.agent_directory import LEGACY_ENTRY_ID, NO_AGENT_RUNNING, AgentDirectory


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
