"""Which ai_agent instances exist: ai_agent's own registry file.

Every running ai_agent registers itself in ai_agent/data/agent_registry.json
(see ai_agent/src/agent_registry.py). Reading that file directly means
ember_api needs no tool call to discover agents, and - more importantly - the
proxy can only ever reach URLs that file lists, never one the browser names.
It also says which listed agent is the entry agent that new questions go to.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


NO_AGENT_RUNNING = "No agent is running"
# An ai_agent registry written before agent files existed marks no entry
# agent; the one instance every older setup had was this id.
LEGACY_ENTRY_ID = "claude-agent"


@dataclass(frozen=True)
class AgentEntry:
    id: str
    label: str
    url: str
    # Optional in the registry (older ai_agent versions do not write them).
    entry: bool = False
    orchestrator: bool = False
    focus: str = ""


class AgentDirectory:
    def __init__(self, registry_path: Path) -> None:
        self._path = registry_path

    async def all(self) -> list[AgentEntry]:
        """Re-read per call (agents come and go); a missing or broken file is
        an empty list, not an error."""
        return await asyncio.to_thread(self._read)

    async def get(self, agent_id: str) -> AgentEntry | None:
        return next((a for a in await self.all() if a.id == agent_id), None)

    async def entry(self) -> AgentEntry | None:
        """The agent every new question goes to: the one flagged `entry`, else
        the first orchestrator, else the legacy single agent, else None."""
        agents = await self.all()
        return (
            next((a for a in agents if a.entry), None)
            or next((a for a in agents if a.orchestrator), None)
            or next((a for a in agents if a.id == LEGACY_ENTRY_ID), None)
        )

    def _read(self) -> list[AgentEntry]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as error:
            logger.warning("could not read agent registry %s: %s", self._path, error)
            return []
        entries = []
        for item in raw.get("agents", []) if isinstance(raw, dict) else []:
            if isinstance(item, dict) and all(isinstance(item.get(k), str) for k in ("id", "label", "url")):
                focus = item.get("focus")
                entries.append(
                    AgentEntry(
                        id=item["id"],
                        label=item["label"],
                        url=item["url"],
                        entry=item.get("entry") is True,
                        orchestrator=item.get("orchestrator") is True,
                        focus=focus if isinstance(focus, str) else "",
                    )
                )
        return entries
