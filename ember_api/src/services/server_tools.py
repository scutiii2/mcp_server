"""ember_api's own MCP client for mcp_server, for pages that gather data
from several tools at once (the Watchers page), so the browser doesn't
need tools.use and the result is one permission-checked request.

The Protocol is what routes depend on; tests swap in a fake.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from mcp.types import PaginatedRequestParams

from src.services.agent_gateway import Caller
from src.services.mcp_session import identity_headers, mcp_session, root_cause

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(30.0, read=60.0)
# A capability with background watchers exposes tool_<alias>_listWatchers
# returning {"watchers": [...]} (chat_app's Watchers page convention).
LIST_WATCHERS_TOOL = re.compile(r"^tool_([A-Za-z0-9]+)_listWatchers$")


class ServerUnavailable(Exception):
    """mcp_server couldn't be reached."""


@dataclass
class WatcherReport:
    # Every watcher row, tagged with its "capability" alias.
    watchers: list[dict[str, Any]] = field(default_factory=list)
    # "<alias>: <problem>" for each capability that failed to answer.
    errors: list[str] = field(default_factory=list)


class ServerTools(Protocol):
    async def watchers(self, caller: Caller) -> WatcherReport: ...


class McpServerTools:
    def __init__(self, url: str, internal_token: str | None) -> None:
        self._url = url
        self._internal_token = internal_token

    async def watchers(self, caller: Caller) -> WatcherReport:
        """Finds every listWatchers tool and calls them all concurrently on
        one session. One capability failing is reported, not raised."""
        headers = identity_headers(caller.username, caller.email, self._internal_token)
        outcomes: list[tuple[str, Any]] = []
        try:
            async with mcp_session(self._url, headers, _TIMEOUT) as session:
                aliases = sorted(
                    {m.group(1) for name in await _tool_names(session) if (m := LIST_WATCHERS_TOOL.match(name))}
                )
                results = await asyncio.gather(
                    *(session.call_tool(f"tool_{alias}_listWatchers", {}) for alias in aliases),
                    return_exceptions=True,
                )
                outcomes = list(zip(aliases, results, strict=True))
        except Exception as error:  # noqa: BLE001 - any transport failure is one "unreachable" outcome
            logger.warning("mcp_server watchers failed: %s", error)
            raise ServerUnavailable(root_cause(error)) from error

        report = WatcherReport()
        for alias, result in outcomes:
            rows, problem = _watcher_rows(result)
            if problem:
                report.errors.append(f"{alias}: {problem}")
            report.watchers.extend({**row, "capability": alias} for row in rows)
        return report


async def _tool_names(session) -> list[str]:
    names: list[str] = []
    cursor: str | None = None
    while True:
        page = await session.list_tools(params=PaginatedRequestParams(cursor=cursor) if cursor else None)
        names.extend(tool.name for tool in page.tools)
        cursor = page.nextCursor
        if not cursor:
            return names


def _watcher_rows(result: Any) -> tuple[list[dict[str, Any]], str | None]:
    if isinstance(result, BaseException):
        return [], root_cause(result)
    text = "\n".join(getattr(block, "text", "") for block in result.content)
    if result.isError:
        return [], text or "the tool failed"
    data = result.structuredContent
    if not isinstance(data, dict) or "watchers" not in data:
        try:
            data = json.loads(text)
        except ValueError:
            return [], text[:300] or "no JSON in the reply"
    rows = data.get("watchers") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return [], "the reply has no watchers list"
    return [row for row in rows if isinstance(row, dict)], None
