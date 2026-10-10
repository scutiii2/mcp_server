"""ember_api's own MCP client for mcp_server tool parameter options.

The Protocol is what routes depend on; tests swap in a fake.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

import httpx
from mcp.types import PaginatedRequestParams

from src.services.agent_gateway import Caller
from src.services.mcp_session import identity_headers, mcp_session, root_cause
from src.services.traffic import TrafficRecorder

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(30.0, read=60.0)


class ServerUnavailable(Exception):
    """mcp_server couldn't be reached."""


class ServerTools(Protocol):
    async def options_templates(self, caller: Caller) -> set[str]: ...


class McpServerTools:
    def __init__(self, url: str, internal_token: str | None, traffic: TrafficRecorder | None = None) -> None:
        self._url = url
        self._internal_token = internal_token
        self._traffic = traffic or TrafficRecorder()

    async def options_templates(self, caller: Caller) -> set[str]:
        """Every `options_url` a tool parameter declares (chat_app's command
        form hint): the only paths /api/commands/options may fetch."""
        headers = identity_headers(caller.username, caller.email, self._internal_token)
        try:
            with self._traffic.timed("mcp_server", "options_templates"):
                async with mcp_session(self._url, headers, _TIMEOUT) as session:
                    tools = await _tools(session)
        except Exception as error:  # noqa: BLE001 - any transport failure is one "unreachable" outcome
            logger.warning("mcp_server tool list failed: %s", error)
            raise ServerUnavailable(root_cause(error)) from error
        templates: set[str] = set()
        for tool in tools:
            properties = (tool.inputSchema or {}).get("properties") or {}
            for schema in properties.values():
                url = schema.get("options_url") if isinstance(schema, dict) else None
                if isinstance(url, str) and url:
                    templates.add(url)
        return templates


async def _tools(session) -> list[Any]:
    tools: list[Any] = []
    cursor: str | None = None
    while True:
        page = await session.list_tools(params=PaginatedRequestParams(cursor=cursor) if cursor else None)
        tools.extend(page.tools)
        cursor = page.nextCursor
        if not cursor:
            return tools
