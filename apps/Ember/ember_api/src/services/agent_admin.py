"""Edits ai_agent's agent files through ai_agent's own /agents routes.

ai_agent owns the files (agents/<id>.json) and validates every change; its
supervisor then starts, restarts or stops the matching process. This client
only forwards: the browser never names a URL, the route is found in ai_agent's
registry (the entry agent, else any running one), and the internal token and
the admin's identity go along like they do for the MCP proxy.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import httpx

from src.models import Account
from src.services.agent_directory import NO_AGENT_RUNNING, AgentDirectory
from src.services.mcp_server_info import base_url
from src.services.traffic import TrafficRecorder

logger = logging.getLogger(__name__)


class AgentAdminUnavailable(Exception):
    """No agent is running, or the one asked did not answer (maps to 502)."""


class AgentAdminRefused(Exception):
    """ai_agent refused the change (4xx); `message` is its own, safe to show."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class AgentAdmin:
    def __init__(
        self,
        client: httpx.AsyncClient,
        directory: AgentDirectory,
        internal_token: str | None,
        traffic: TrafficRecorder | None = None,
    ) -> None:
        self._client = client
        self._directory = directory
        self._internal_token = internal_token
        self._traffic = traffic or TrafficRecorder()

    def _headers(self, account: Account) -> dict[str, str]:
        headers = {"X-Requester-Username": account.username, "X-Requester-Email": account.email}
        if account.uid:
            headers["X-Requester-Uid"] = account.uid
        if self._internal_token:
            headers["X-Internal-Token"] = self._internal_token
        return headers

    async def _base(self) -> str:
        agent = await self._directory.entry() or next(iter(await self._directory.all()), None)
        if agent is None:
            raise AgentAdminUnavailable(NO_AGENT_RUNNING)
        return base_url(agent.url)

    async def _request(self, method: str, path: str, account: Account, json: Any = None) -> Any:
        base = await self._base()
        try:
            with self._traffic.timed("ai_agent", f"{method} /agents") as timing:
                response = await self._client.request(
                    method, f"{base}{path}", json=json, headers=self._headers(account), timeout=15.0
                )
                timing.ok = response.status_code < 500
        except httpx.HTTPError as error:
            logger.warning("ai_agent %s %s unreachable: %s", method, path, error)
            raise AgentAdminUnavailable(str(error)) from error
        try:
            body = response.json()
        except ValueError:
            body = None
        if 400 <= response.status_code < 500:
            message = body.get("error") if isinstance(body, dict) else None
            raise AgentAdminRefused(response.status_code, str(message or f"ai_agent answered {response.status_code}"))
        if response.status_code >= 500 or body is None:
            raise AgentAdminUnavailable(f"ai_agent answered {response.status_code}")
        return body

    async def gateways(self, account: Account) -> dict[str, Any]:
        body = await self._request("GET", "/agents/gateways", account)
        providers = body.get("providers") if isinstance(body, dict) else None
        return providers if isinstance(providers, dict) else {}

    async def list(self, account: Account) -> list[dict[str, Any]]:
        body = await self._request("GET", "/agents/files", account)
        agents = body.get("agents") if isinstance(body, dict) else None
        return [a for a in agents if isinstance(a, dict)] if isinstance(agents, list) else []

    async def create(self, account: Account, agent_id: str, config: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/agents/files", account, json={"id": agent_id, "config": config})

    async def update(self, account: Account, agent_id: str, config: dict[str, Any]) -> dict[str, Any]:
        return await self._request("PUT", f"/agents/files/{quote(agent_id, safe='')}", account, json=config)

    async def delete(self, account: Account, agent_id: str) -> None:
        await self._request("DELETE", f"/agents/files/{quote(agent_id, safe='')}", account)

    async def prompts(self, account: Account) -> dict[str, Any]:
        body = await self._request("GET", "/agents/prompts", account)
        return body if isinstance(body, dict) else {}

    async def set_prompts(self, account: Account, changes: dict[str, str | None]) -> dict[str, Any]:
        body = await self._request("PUT", "/agents/prompts", account, json=changes)
        return body if isinstance(body, dict) else {}

    async def preview(self, account: Account, agent_id: str, config: dict[str, Any], caveman: bool) -> str:
        body = await self._request(
            "POST", "/agents/prompt-preview", account, json={"id": agent_id, "config": config, "caveman": caveman}
        )
        prompt = body.get("prompt") if isinstance(body, dict) else None
        return prompt if isinstance(prompt, str) else ""
