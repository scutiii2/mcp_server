"""mcp_server's plain HTTP routes next to its /mcp endpoint: the command
registry (/commands), capability help (/commands/help) and the capability
switchboard (/capabilities) - the same routes chat_app's Chat and
Capabilities pages use.

Only these fixed paths are reachable, with the same identity and
internal-token headers as the MCP proxy; the browser never names a URL.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from src.models import Account

logger = logging.getLogger(__name__)


class McpServerUnavailable(Exception):
    """mcp_server couldn't be reached (maps to 502)."""


class McpServerRefused(Exception):
    """mcp_server answered 4xx; `message` is its own, safe to show."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def base_url(mcp_url: str) -> str:
    """http://host:port/mcp -> http://host:port (the routes' root)."""
    parts = urlsplit(mcp_url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


class McpServerInfo:
    def __init__(self, client: httpx.AsyncClient, mcp_url: str, internal_token: str | None) -> None:
        self._client = client
        self._base = base_url(mcp_url)
        self._internal_token = internal_token

    def _headers(self, account: Account) -> dict[str, str]:
        headers = {"X-Requester-Username": account.username, "X-Requester-Email": account.email}
        if self._internal_token:
            headers["X-Internal-Token"] = self._internal_token
        return headers

    async def _request(
        self, method: str, path: str, account: Account, params: dict[str, str] | None = None, json: Any = None
    ) -> Any:
        try:
            response = await self._client.request(
                method, f"{self._base}{path}", params=params, json=json, headers=self._headers(account), timeout=30.0
            )
        except httpx.HTTPError as error:
            logger.warning("mcp_server %s %s unreachable: %s", method, path, error)
            raise McpServerUnavailable(str(error)) from error
        try:
            body = response.json()
        except ValueError:
            body = None
        if 400 <= response.status_code < 500:
            message = body.get("error") if isinstance(body, dict) else None
            raise McpServerRefused(response.status_code, str(message or f"mcp_server answered {response.status_code}"))
        if response.status_code >= 500 or body is None:
            raise McpServerUnavailable(f"mcp_server answered {response.status_code}")
        return body

    async def commands(self, account: Account) -> list[dict[str, Any]]:
        body = await self._request("GET", "/commands", account)
        return body if isinstance(body, list) else []

    async def help_index(self, account: Account) -> Any:
        return await self._request("GET", "/commands/help", account)

    async def help(self, account: Account, capability: str, target: str, command: str | None) -> Any:
        params = {"target": target, **({"command": command} if command else {})}
        return await self._request("GET", f"/commands/help/{quote(capability, safe='')}", account, params=params)

    async def capabilities(self, account: Account) -> list[dict[str, Any]]:
        body = await self._request("GET", "/capabilities", account)
        return body if isinstance(body, list) else []

    async def set_capability(self, account: Account, name: str, enabled: bool) -> dict[str, Any]:
        return await self._request("PATCH", f"/capabilities/{quote(name, safe='')}", account, json={"enabled": enabled})
