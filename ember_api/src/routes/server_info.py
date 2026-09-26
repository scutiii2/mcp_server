"""/api/commands and /api/capabilities: mcp_server's command registry,
capability help and capability switchboard, passed through (tools.use to
read, admin.manage to switch a capability on or off)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from pydantic import BaseModel

from src.config import Settings
from src.deps import get_settings, require_permission
from src.models import Account
from src.services.mcp_server_info import McpServerInfo, McpServerRefused, McpServerUnavailable
from src.services.permissions import ADMIN_MANAGE, TOOLS_USE

router = APIRouter(prefix="/api", tags=["server-info"])

require_tools = require_permission(TOOLS_USE)
require_admin = require_permission(ADMIN_MANAGE)

# Capability ids and command names as mcp_server defines them (one Path()
# per route: FastAPI binds a shared instance to the first parameter name).
NAME_PATTERN = r"^[A-Za-z0-9_.-]{1,64}$"


def get_server_info(request: Request, settings: Settings = Depends(get_settings)) -> McpServerInfo:
    return McpServerInfo(request.app.state.upstream, settings.mcp_server_url, request.app.state.internal_token)


async def _call(awaitable) -> Any:
    try:
        return await awaitable
    except McpServerUnavailable as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "mcp_server is unreachable") from error
    except McpServerRefused as error:
        code = status.HTTP_404_NOT_FOUND if error.status == 404 else status.HTTP_400_BAD_REQUEST
        raise HTTPException(code, str(error)) from error


class CommandOut(BaseModel):
    capability: str
    name: str
    description: str
    tool_name: str


class CapabilityOut(BaseModel):
    name: str
    enabled: bool
    label: str | None = None
    tools: list[str] = []
    resources: list[str] = []


class CapabilitySwitch(BaseModel):
    enabled: bool


@router.get("/commands")
async def list_commands(
    account: Account = Depends(require_tools), info: McpServerInfo = Depends(get_server_info)
) -> list[CommandOut]:
    """Slash commands of the enabled capabilities: /<capability> <name>."""
    rows = await _call(info.commands(account))
    return [CommandOut(**{k: str(r.get(k, "")) for k in CommandOut.model_fields}) for r in rows if isinstance(r, dict)]


@router.get("/commands/help")
async def help_index(account: Account = Depends(require_tools), info: McpServerInfo = Depends(get_server_info)) -> Any:
    """What /help shows: every enabled capability and its commands."""
    return await _call(info.help_index(account))


@router.get("/commands/help/{capability}")
async def capability_help(
    capability: str = Path(pattern=NAME_PATTERN),
    target: Literal["all", "tools", "commands", "workflow"] = Query(default="all"),
    command: str | None = Query(default=None, pattern=r"^[A-Za-z0-9_.-]{1,64}$"),
    account: Account = Depends(require_tools),
    info: McpServerInfo = Depends(get_server_info),
) -> Any:
    """What /<capability> help shows."""
    return await _call(info.help(account, capability, target, command))


@router.get("/capabilities")
async def list_capabilities(
    account: Account = Depends(require_tools), info: McpServerInfo = Depends(get_server_info)
) -> list[CapabilityOut]:
    return [CapabilityOut(**r) for r in await _call(info.capabilities(account)) if isinstance(r, dict)]


@router.patch("/capabilities/{name}")
async def switch_capability(
    body: CapabilitySwitch,
    name: str = Path(pattern=NAME_PATTERN),
    account: Account = Depends(require_admin),
    info: McpServerInfo = Depends(get_server_info),
) -> CapabilityOut:
    """Turns a capability's tools on or off for every mcp_server client
    (chat_app, ai_agent and ember alike), so admins only."""
    return CapabilityOut(**await _call(info.set_capability(account, name, body.enabled)))
