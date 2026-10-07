"""mcp_server's plain HTTP routes next to its /mcp endpoint: the command
registry (/commands), capability help (/commands/help), the capability
switchboard (/capabilities), the extension list (/extensions), a command
form's select options (a tool's `options_url`) and file uploads (/upload) -
the same routes chat_app's Chat and Capabilities pages use.

Only these fixed paths are reachable, with the same identity and
internal-token headers as the MCP proxy; the browser never names a URL
(an options path is one a tool's schema declares - see routes/server_info.py).
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from src.models import Account
from src.services.traffic import TrafficRecorder

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
    def __init__(
        self, client: httpx.AsyncClient, mcp_url: str, internal_token: str | None, traffic: TrafficRecorder | None = None
    ) -> None:
        self._client = client
        self._base = base_url(mcp_url)
        self._internal_token = internal_token
        self._traffic = traffic or TrafficRecorder()

    def _headers(self, account: Account) -> dict[str, str]:
        headers = {"X-Requester-Username": account.username, "X-Requester-Email": account.email}
        if self._internal_token:
            headers["X-Internal-Token"] = self._internal_token
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        account: Account,
        params: dict[str, str] | None = None,
        json: Any = None,
        files: dict[str, tuple[str, bytes]] | None = None,
        timeout: float = 30.0,
    ) -> Any:
        try:
            with self._traffic.timed("mcp_server", _traffic_name(method, path)) as timing:
                response = await self._client.request(
                    method,
                    f"{self._base}{path}",
                    params=params,
                    json=json,
                    files=files,
                    headers=self._headers(account),
                    timeout=timeout,
                )
                timing.ok = response.status_code < 500
        except httpx.HTTPError as error:
            logger.warning("mcp_server %s %s unreachable: %s", method, path, error)
            raise McpServerUnavailable(str(error)) from error
        if response.status_code == 204:
            return None
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

    async def capability_page(self, account: Account, name: str) -> dict[str, Any]:
        """A capability's GUI page (the declarative layout ember_web draws)."""
        body = await self._request("GET", f"/capabilities/{quote(name, safe='')}/gui", account)
        return body if isinstance(body, dict) else {}

    async def set_capability(self, account: Account, name: str, enabled: bool) -> dict[str, Any]:
        return await self._request("PATCH", f"/capabilities/{quote(name, safe='')}", account, json={"enabled": enabled})

    async def extensions(self, account: Account) -> list[dict[str, Any]]:
        """Extensions (other MCP servers mcp_server re-exposes, their tools
        named "<id>__<tool>"): [{id, label, description, status, error, tools}]."""
        body = await self._request("GET", "/extensions", account)
        return body if isinstance(body, list) else []

    async def add_extension(self, account: Account, label: str, url: str, description: str) -> dict[str, Any]:
        """mcp_server connects to it and saves it to its config; an
        unreachable URL is still added (status "error")."""
        body = {"label": label, "url": url, "description": description}
        return await self._request("POST", "/extensions", account, json=body)

    async def remove_extension(self, account: Account, extension_id: str) -> None:
        await self._request("DELETE", f"/extensions/{quote(extension_id, safe='')}", account)

    async def options(self, account: Account, path: str) -> list[dict[str, str]]:
        """A select's options from `path` on mcp_server (a tool's
        `options_url`, placeholders already filled), as
        [{value, label, ...extra fields}] - see normalize_options()."""
        if not is_server_path(path):
            raise ValueError(f"not a path on mcp_server: {path!r}")
        return normalize_options(await self._request("GET", path, account))

    async def upload(self, account: Account, filename: str, content: bytes) -> str:
        """Stores a file on mcp_server for a file-path tool parameter
        (mcp_server's /upload, which checks the internal token and the file
        type); returns the server-side path."""
        body = await self._request("POST", "/upload", account, files={"file": (filename, content)})
        path = body.get("path") if isinstance(body, dict) else None
        if not isinstance(path, str) or not path:
            raise McpServerUnavailable("mcp_server's upload answered without a path")
        return path

    async def upload_table(self, account: Account, filename: str, content: bytes) -> dict[str, Any]:
        """Hands a CSV/XLSX to mcp_server's /upload/table, which keeps it as an
        in-memory table for the data tools; returns
        {table_id, filename, rows, columns, sheet, notes}."""
        # A large workbook can take well over the default 30 s to parse.
        body = await self._request(
            "POST", "/upload/table", account, files={"file": (filename, content)}, timeout=120.0
        )
        if not isinstance(body, dict) or not isinstance(body.get("table_id"), str):
            raise McpServerUnavailable("mcp_server's table upload answered without a table id")
        return body

    async def download(self, account: Account, path: str) -> httpx.Response:
        """Opens mcp_server's /download for a file a tool offered (the
        `[[DOWNLOAD ...]]` marker's `path`). The body is not read: the caller
        streams it and must close the response. `path` goes as a query value,
        never as part of the URL."""
        request = self._client.build_request(
            "GET", f"{self._base}/download", params={"path": path}, headers=self._headers(account), timeout=30.0
        )
        try:
            with self._traffic.timed("mcp_server", "GET /download") as timing:
                response = await self._client.send(request, stream=True)
                timing.ok = response.status_code < 500
        except httpx.HTTPError as error:
            logger.warning("mcp_server download unreachable: %s", error)
            raise McpServerUnavailable(str(error)) from error
        if response.status_code == 200:
            return response
        await response.aclose()
        if 400 <= response.status_code < 500:
            raise McpServerRefused(response.status_code, f"mcp_server answered {response.status_code}")
        raise McpServerUnavailable(f"mcp_server answered {response.status_code}")


def _traffic_name(method: str, path: str) -> str:
    """"GET /commands/help/foo" -> "GET /commands": the first segment only, so a
    capability or extension name never becomes a counter of its own."""
    return f"{method} /{path.lstrip('/').split('/', 1)[0].split('?', 1)[0]}"


def is_server_path(path: str) -> bool:
    """A plain path on mcp_server itself: a schema must never name a host."""
    return path.startswith("/") and not path.startswith("//") and "://" not in path and "\\" not in path


def normalize_options(data: Any) -> list[dict[str, str]]:
    """chat_app's fetch_options() shapes: a list of strings, a list of
    {value, label, ...} objects (extra fields feed a param's `sets` /
    `shows`), or a {value: label} object."""
    if isinstance(data, dict):
        return [{"value": str(k), "label": str(v)} for k, v in data.items()]
    if not isinstance(data, list):
        return []
    options: list[dict[str, str]] = []
    for item in data:
        if isinstance(item, dict):
            if "value" not in item:
                continue
            options.append(
                {**{str(k): str(v) for k, v in item.items()}, "value": str(item["value"]), "label": str(item.get("label", item["value"]))}
            )
        elif item is not None:
            options.append({"value": str(item), "label": str(item)})
    return options
