"""/api/account-capabilities: which built-in capabilities and server-listed
extensions the logged-in account has added (any logged-in account; private to
it). The reply also carries `disabled_tools`, the tools of every capability the
account has not added, which ember_web sends with each question."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.deps import current_account, get_db_session, get_log_writer
from src.models import Account
from src.routes.server_info import _call, get_server_info
from src.services.account_capability_service import (
    AccountCapabilities,
    AccountCapabilityService,
    Kind,
    TooManyItems,
    tools_to_disable,
)
from src.services.log_service import LogWriter
from src.services.mcp_server_info import McpServerInfo

router = APIRouter(prefix="/api/account-capabilities", tags=["account-capabilities"])

KEY_PATTERN = r"^[A-Za-z0-9_.-]{1,64}$"


def get_service(
    account: Account = Depends(current_account),
    session: AsyncSession = Depends(get_db_session),
) -> AccountCapabilityService:
    return AccountCapabilityService(session, account.id)


class EnabledBody(BaseModel):
    enabled: bool


class AccountCapabilitiesOut(BaseModel):
    capabilities: list[str]
    extensions: list[str]
    disabled_tools: list[str]

    @classmethod
    def of(cls, state: AccountCapabilities, listed: list[dict[str, Any]]) -> AccountCapabilitiesOut:
        return cls(
            capabilities=state.capabilities,
            extensions=state.extensions,
            disabled_tools=tools_to_disable(listed, state.capabilities),
        )


@router.get("")
async def read_account_capabilities(
    account: Account = Depends(current_account),
    service: AccountCapabilityService = Depends(get_service),
    info: McpServerInfo = Depends(get_server_info),
) -> AccountCapabilitiesOut:
    state = await service.get()
    return AccountCapabilitiesOut.of(state, await _call(info.capabilities(account)))


@router.put("/{kind}/{key}")
async def set_account_capability(
    body: EnabledBody,
    kind: Literal["capability", "extension"],
    key: str = Path(pattern=KEY_PATTERN),
    account: Account = Depends(current_account),
    service: AccountCapabilityService = Depends(get_service),
    info: McpServerInfo = Depends(get_server_info),
    logs: LogWriter = Depends(get_log_writer),
) -> AccountCapabilitiesOut:
    """Adds or removes one item; returns the whole set as stored."""
    # Read mcp_server first: if it is down, nothing has been changed yet.
    listed = await _call(info.capabilities(account))
    kind_name: Kind = kind
    try:
        state = await service.set_enabled(kind_name, key, body.enabled)
    except TooManyItems as error:
        raise HTTPException(status.HTTP_409_CONFLICT, "Too many items added to this account") from error
    verb = "Added" if body.enabled else "Disabled"
    await logs.action(account, f"account.{kind}_{'enable' if body.enabled else 'disable'}", f"{verb} {kind} '{key}'")
    return AccountCapabilitiesOut.of(state, listed)
