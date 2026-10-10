"""ember_api's client for mcp_server's ticket routes.

Only fixed paths are built here and every id is an int, so the browser never
names a URL. Identity and the internal token come from McpServerInfo's headers.
mcp_server's own refusals keep their message (see routes/tickets.py for the
status mapping); nothing here reads or logs ticket text.
"""

from __future__ import annotations

from typing import Any

from src.models import Account
from src.services.mcp_server_info import McpServerInfo


def _params(filters: dict[str, Any]) -> dict[str, str]:
    """Query values for mcp_server: None dropped, `possible` as "1", the rest as text."""
    params: dict[str, str] = {}
    for key, value in filters.items():
        if value is None or value is False:
            continue
        params[key] = "1" if value is True else str(value)
    return params


class TicketGateway:
    def __init__(self, info: McpServerInfo) -> None:
        self._info = info

    # ---- reporter routes (the account's own tickets) ----------------------

    async def create(self, account: Account, body: dict[str, Any]) -> dict[str, Any]:
        return await self._info.request("POST", "/tickets", account, json=body)

    async def list_own(self, account: Account, status: str | None = None) -> dict[str, Any]:
        return await self._info.request("GET", "/tickets", account, params=_params({"status": status}))

    async def get_own(self, account: Account, ticket_id: int) -> dict[str, Any]:
        return await self._info.request("GET", f"/tickets/{int(ticket_id)}", account)

    async def comment_own(self, account: Account, ticket_id: int, body: str) -> dict[str, Any]:
        return await self._info.request("POST", f"/tickets/{int(ticket_id)}/comments", account, json={"body": body})

    async def close_own(self, account: Account, ticket_id: int) -> dict[str, Any]:
        return await self._info.request("POST", f"/tickets/{int(ticket_id)}/close", account)

    # ---- staff routes (everything) ----------------------------------------

    async def list_all(self, account: Account, filters: dict[str, Any]) -> dict[str, Any]:
        return await self._info.request("GET", "/ticket-admin/tickets", account, params=_params(filters))

    async def get_any(self, account: Account, ticket_id: int) -> dict[str, Any]:
        return await self._info.request("GET", f"/ticket-admin/tickets/{int(ticket_id)}", account)

    async def update(self, account: Account, ticket_id: int, changes: dict[str, Any]) -> dict[str, Any]:
        return await self._info.request("PATCH", f"/ticket-admin/tickets/{int(ticket_id)}", account, json=changes)

    async def comment_staff(self, account: Account, ticket_id: int, body: str) -> dict[str, Any]:
        return await self._info.request(
            "POST", f"/ticket-admin/tickets/{int(ticket_id)}/comments", account, json={"body": body}
        )

    async def move(self, account: Account, ticket_id: int, group_id: int | None) -> dict[str, Any]:
        return await self._info.request(
            "POST", f"/ticket-admin/tickets/{int(ticket_id)}/move", account, json={"group_id": group_id}
        )

    async def list_groups(self, account: Account, filters: dict[str, Any]) -> dict[str, Any]:
        return await self._info.request("GET", "/ticket-admin/groups", account, params=_params(filters))

    async def update_group(self, account: Account, group_id: int, changes: dict[str, Any]) -> dict[str, Any]:
        return await self._info.request("PATCH", f"/ticket-admin/groups/{int(group_id)}", account, json=changes)

    async def stats(self, account: Account) -> dict[str, Any]:
        return await self._info.request("GET", "/ticket-admin/stats", account)
