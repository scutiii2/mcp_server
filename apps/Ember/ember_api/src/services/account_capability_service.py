"""Per-account choice of which built-in capabilities and server-listed
extensions the account has added. Every lookup filters by account. A row means
enabled; the service never stores a "disabled" row.

It holds only ids and does not know which ones exist: the browser and mcp_server
own that. `tools_to_disable` is the one place that looks at mcp_server's list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import AccountCapability

Kind = Literal["capability", "extension"]
MAX_ITEMS = 200


class TooManyItems(Exception):
    """The account already has MAX_ITEMS things added."""


@dataclass(frozen=True)
class AccountCapabilities:
    capabilities: list[str] = field(default_factory=list)
    extensions: list[str] = field(default_factory=list)


class AccountCapabilityService:
    def __init__(self, session: AsyncSession, account_id: int) -> None:
        self._session = session
        self._account_id = account_id

    async def get(self) -> AccountCapabilities:
        rows = (
            await self._session.execute(
                select(AccountCapability.kind, AccountCapability.item_id).where(
                    AccountCapability.account_id == self._account_id
                )
            )
        ).all()
        return AccountCapabilities(
            capabilities=sorted(item for kind, item in rows if kind == "capability"),
            extensions=sorted(item for kind, item in rows if kind == "extension"),
        )

    async def set_enabled(self, kind: Kind, item_id: str, enabled: bool) -> AccountCapabilities:
        """Adds or removes one row and returns the whole set. Asking for the
        state it already has changes nothing."""
        existing = await self._session.get(AccountCapability, (self._account_id, kind, item_id))
        if enabled and existing is None:
            count = await self._session.scalar(
                select(func.count()).select_from(AccountCapability).where(AccountCapability.account_id == self._account_id)
            )
            if (count or 0) >= MAX_ITEMS:
                raise TooManyItems
            self._session.add(AccountCapability(account_id=self._account_id, kind=kind, item_id=item_id))
            await self._session.commit()
        elif not enabled and existing is not None:
            await self._session.delete(existing)
            await self._session.commit()
        return await self.get()


async def forget_extension(session: AsyncSession, extension_id: str) -> None:
    """Drops an extension from every account (it was removed from mcp_server)."""
    await session.execute(
        delete(AccountCapability).where(AccountCapability.kind == "extension", AccountCapability.item_id == extension_id)
    )
    await session.commit()


def tools_to_disable(capabilities: list[dict[str, Any]], enabled: list[str]) -> list[str]:
    """The sorted tool names of every capability in mcp_server's list that is
    not in `enabled`. Extension tools are not capabilities and are never listed."""
    on = set(enabled)
    names = {
        tool
        for capability in capabilities
        if isinstance(capability, dict) and capability.get("name") not in on
        for tool in capability.get("tools", [])
        if isinstance(tool, str)
    }
    return sorted(names)
