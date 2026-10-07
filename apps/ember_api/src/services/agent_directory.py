"""Which ai_agent instances exist: ai_agent's registry, from a file or a URL.

Every running ai_agent registers itself in ai_agent/data/agent_registry.json
(see ai_agent/src/agents/agent_registry.py) and serves the same JSON at
GET /registry. Reading that registry means ember_api needs no tool call to
discover agents, and - more importantly - the proxy can only ever reach URLs
it lists, never one the browser names. It also says which listed agent is the
entry agent that new questions go to.

The file source fits ai_agent on the same machine; the URL source fits one in
another directory or on another machine.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

logger = logging.getLogger(__name__)


NO_AGENT_RUNNING = "No agent is running"
# An ai_agent registry written before agent files existed marks no entry
# agent; the one instance every older setup had was this id.
LEGACY_ENTRY_ID = "claude-agent"
DEFINITIONS_FILE = "agent_definitions.json"

# A registry fetch must fail fast: every chat request waits on it.
_FETCH_TIMEOUT = httpx.Timeout(3.0)
# A fetched registry is reused this long, so a burst of requests is one fetch.
_CACHE_SECONDS = 5.0
# When ai_agent stops answering, the last good list is served this long (a
# blip should not empty the chat page), then the list is empty.
_STALE_SECONDS = 60.0


@dataclass(frozen=True)
class AgentEntry:
    id: str
    label: str
    url: str
    # Optional in the registry (older ai_agent versions do not write them).
    entry: bool = False
    orchestrator: bool = False
    focus: str = ""


@dataclass(frozen=True)
class AgentDefinition:
    """An agent ai_agent's supervisor knows from agents/<id>.json, running or
    not (the registry lists only the running ones)."""

    id: str
    label: str
    entry: bool = False
    orchestrator: bool = False
    focus: str = ""
    enabled: bool = True


@dataclass(frozen=True)
class AgentListing:
    """One row of the Agents page. No URL: that stays server-side."""

    id: str
    label: str
    entry: bool
    orchestrator: bool
    focus: str
    status: str  # "running" | "offline" (defined, not running) | "disabled"


def parse_definitions(raw: Any) -> list[AgentDefinition]:
    """The agents a document's `defined` list names; incomplete entries are left out."""
    found = []
    for item in raw.get("defined", []) if isinstance(raw, dict) else []:
        if isinstance(item, dict) and all(isinstance(item.get(k), str) for k in ("id", "label")):
            focus = item.get("focus")
            found.append(
                AgentDefinition(
                    id=item["id"],
                    label=item["label"],
                    entry=item.get("entry") is True,
                    orchestrator=item.get("orchestrator") is True,
                    focus=focus if isinstance(focus, str) else "",
                    enabled=item.get("enabled") is not False,
                )
            )
    return found


def parse_registry(raw: Any) -> list[AgentEntry]:
    """The agents a registry document lists; entries that are not complete are left out."""
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


class RegistrySource(Protocol):
    async def read(self) -> list[AgentEntry]: ...

    async def definitions(self) -> list[AgentDefinition]: ...


class FileRegistrySource:
    """ai_agent's registry file, re-read per call (agents come and go); a
    missing or broken file is an empty list, not an error."""

    def __init__(self, path: Path) -> None:
        self._path = path
        # ai_agent's supervisor writes this next to the registry.
        self._definitions_path = path.with_name(DEFINITIONS_FILE)

    async def read(self) -> list[AgentEntry]:
        return parse_registry(await asyncio.to_thread(self._load, self._path))

    async def definitions(self) -> list[AgentDefinition]:
        return parse_definitions(await asyncio.to_thread(self._load, self._definitions_path))

    @staticmethod
    def _load(path: Path) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as error:
            logger.warning("could not read %s: %s", path, error)
            return {}


class HttpRegistrySource:
    """ai_agent's GET /registry. Cached for a few seconds; when a fetch fails
    the last good list is kept for a minute, then the list is empty."""

    def __init__(self, url: str, client: httpx.AsyncClient, internal_token: str | None) -> None:
        self._url = url
        self._client = client
        self._headers = {"X-Internal-Token": internal_token} if internal_token else {}
        self._agents: list[AgentEntry] = []
        self._defined: list[AgentDefinition] = []
        self._fetched_at = 0.0  # last attempt, ok or not
        self._good_at = 0.0  # last success
        self._lock = asyncio.Lock()

    async def read(self) -> list[AgentEntry]:
        return await self._refreshed(lambda: self._agents)

    async def definitions(self) -> list[AgentDefinition]:
        return await self._refreshed(lambda: self._defined)

    async def _refreshed(self, pick):
        async with self._lock:
            now = time.monotonic()
            if self._fetched_at and now - self._fetched_at < _CACHE_SECONDS:
                return self._current(now, pick)
            self._fetched_at = now
            try:
                response = await self._client.get(self._url, headers=self._headers, timeout=_FETCH_TIMEOUT)
                response.raise_for_status()
                body = response.json()
                self._agents = parse_registry(body)
                self._defined = parse_definitions(body)
                self._good_at = now
            except (httpx.HTTPError, ValueError) as error:
                logger.warning("could not fetch agent registry %s: %s", self._url, error)
            return self._current(now, pick)

    def _current(self, now: float, pick):
        return pick() if self._good_at and now - self._good_at < _STALE_SECONDS else []


class AgentDirectory:
    def __init__(self, source: RegistrySource | Path) -> None:
        self._source = FileRegistrySource(source) if isinstance(source, Path) else source

    async def all(self) -> list[AgentEntry]:
        return await self._source.read()

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

    async def listing(self) -> list[AgentListing]:
        """Every agent for the Agents page: the running ones, plus those
        defined but stopped ("offline") or switched off ("disabled"). Running
        first, then offline, then disabled; the entry agent leads its group.
        Without definitions (ai_agent started without its supervisor) only
        the running agents are listed."""
        running = await self.all()
        entry = await self.entry()
        defined = await self._source.definitions()
        rows = {
            a.id: AgentListing(a.id, a.label, entry is not None and a.id == entry.id, a.orchestrator, a.focus, "running")
            for a in running
        }
        for d in defined:
            if d.id not in rows:
                status = "offline" if d.enabled else "disabled"
                rows[d.id] = AgentListing(d.id, d.label, d.entry, d.orchestrator, d.focus, status)
        order = {"running": 0, "offline": 1, "disabled": 2}
        return sorted(rows.values(), key=lambda r: (order[r.status], not r.entry))
