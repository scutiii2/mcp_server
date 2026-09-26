"""/api/commands, /api/capabilities and /api/extensions: mcp_server's command
registry, capability help, capability switchboard and extensions, passed
through. Reading needs tools.use (extensions: chat.use or tools.use, since
the chat picks which ones the agent may use); switching a capability or
adding/removing an extension changes mcp_server for everyone, so it needs
admin.manage and is written to the activity log."""

from __future__ import annotations

from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from pydantic import BaseModel, Field, field_validator

from src.config import Settings
from src.deps import get_log_writer, get_settings, require_any_permission, require_permission
from src.models import Account
from src.services.log_service import LogWriter
from src.services.mcp_server_info import McpServerInfo, McpServerRefused, McpServerUnavailable
from src.services.permissions import ADMIN_MANAGE, CHAT_USE, TOOLS_USE

router = APIRouter(prefix="/api", tags=["server-info"])

require_tools = require_permission(TOOLS_USE)
require_admin = require_permission(ADMIN_MANAGE)
require_chat_or_tools = require_any_permission(CHAT_USE, TOOLS_USE)

# Capability ids and command names as mcp_server defines them (one Path()
# per route: FastAPI binds a shared instance to the first parameter name).
NAME_PATTERN = r"^[A-Za-z0-9_.-]{1,64}$"
# Extension ids are mcp_server-made slugs of their label.
EXTENSION_ID_PATTERN = r"^[a-z0-9_]{1,64}$"


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


class ExtensionOut(BaseModel):
    id: str
    label: str
    description: str = ""
    # "connected" or "error"
    status: str
    error: str | None = None
    tools: list[str] = []


class ExtensionCreate(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=500)

    @field_validator("label", "url", "description")
    @classmethod
    def strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("url")
    @classmethod
    def http_url(cls, url: str) -> str:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError("must be an http:// or https:// URL")
        return url


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
    logs: LogWriter = Depends(get_log_writer),
) -> CapabilityOut:
    """Turns a capability's tools on or off for every mcp_server client
    (chat_app, ai_agent and ember alike), so admins only."""
    capability = CapabilityOut(**await _call(info.set_capability(account, name, body.enabled)))
    await logs.action(account, "mcp.capability", f"Turned capability '{name}' {'on' if body.enabled else 'off'}")
    return capability


@router.get("/extensions")
async def list_extensions(
    account: Account = Depends(require_chat_or_tools), info: McpServerInfo = Depends(get_server_info)
) -> list[ExtensionOut]:
    return [ExtensionOut(**r) for r in await _call(info.extensions(account)) if isinstance(r, dict)]


@router.post("/extensions", status_code=status.HTTP_201_CREATED)
async def add_extension(
    body: ExtensionCreate,
    account: Account = Depends(require_admin),
    info: McpServerInfo = Depends(get_server_info),
    logs: LogWriter = Depends(get_log_writer),
) -> ExtensionOut:
    """mcp_server connects to the MCP server at `url` and offers its tools
    to every client, so admins only. Added even if unreachable right now."""
    extension = ExtensionOut(**await _call(info.add_extension(account, body.label, body.url, body.description)))
    await logs.action(account, "mcp.extension_add", f"Added extension '{extension.id}' ({body.url})")
    return extension


@router.delete("/extensions/{extension_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_extension(
    extension_id: str = Path(pattern=EXTENSION_ID_PATTERN),
    account: Account = Depends(require_admin),
    info: McpServerInfo = Depends(get_server_info),
    logs: LogWriter = Depends(get_log_writer),
) -> Response:
    await _call(info.remove_extension(account, extension_id))
    await logs.action(account, "mcp.extension_remove", f"Removed extension '{extension_id}'")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
