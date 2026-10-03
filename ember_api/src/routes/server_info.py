"""/api/commands, /api/capabilities and /api/extensions: mcp_server's command
registry, capability help, capability switchboard and extensions, passed
through. Reading needs tools.use (extensions: chat.use or tools.use, since
the chat picks which ones the agent may use); switching a capability or
adding/removing an extension changes mcp_server for everyone, so it needs
admin.manage and is written to the activity log.

The command form (tools.use) also gets a select's options from a path a
tool's schema declares (`options_url`, with {placeholders} filled from
`arg.<param>`), and can store a dropped file on mcp_server for a file-path
parameter (/api/uploads)."""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import AsyncIterator
from typing import Any, Literal
from urllib.parse import quote, unquote, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from src.config import Settings
from src.deps import get_log_writer, get_server_tools, get_settings, require_any_permission, require_permission
from src.models import Account
from src.services.agent_gateway import Caller
from src.services.log_service import LogWriter
from src.services.mcp_server_info import McpServerInfo, McpServerRefused, McpServerUnavailable, is_server_path
from src.services.permissions import ADMIN_MANAGE, CHAT_USE, TOOLS_USE
from src.services.server_tools import ServerTools, ServerUnavailable

router = APIRouter(prefix="/api", tags=["server-info"])

require_tools = require_permission(TOOLS_USE)
require_admin = require_permission(ADMIN_MANAGE)
require_chat_or_tools = require_any_permission(CHAT_USE, TOOLS_USE)

# Capability ids and command names as mcp_server defines them (one Path()
# per route: FastAPI binds a shared instance to the first parameter name).
NAME_PATTERN = r"^[A-Za-z0-9_.-]{1,64}$"
# Extension ids are mcp_server-made slugs of their label.
EXTENSION_ID_PATTERN = r"^[a-z0-9_]{1,64}$"
# A file for a command's file-path parameter (mcp_server's /upload decides
# which types it takes).
UPLOAD_MAX_BYTES = 15 * 1024 * 1024
_UPLOAD_MAX_BASE64 = (UPLOAD_MAX_BYTES + 2) // 3 * 4
_PLACEHOLDER = re.compile(r"\{(\w+)\}")
# The `path` of a download marker: whatever mcp_server named, without control characters.
DOWNLOAD_PATH_PATTERN = r"^[^\x00-\x1f\x7f]{1,1000}$"


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


class OptionOut(BaseModel):
    value: str
    label: str
    # Anything else the option carries, for a param's `sets` / `shows`.
    extra: dict[str, str] = {}


class UploadIn(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    data: str = Field(min_length=1, max_length=_UPLOAD_MAX_BASE64)


class UploadOut(BaseModel):
    # Where mcp_server stored it: the value for the file-path parameter.
    path: str


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


@router.get("/commands/options")
async def command_options(
    request: Request,
    template: str = Query(min_length=1, max_length=500),
    account: Account = Depends(require_tools),
    info: McpServerInfo = Depends(get_server_info),
    tools: ServerTools = Depends(get_server_tools),
) -> list[OptionOut]:
    """Options for a command-form select. `template` must be an
    `options_url` some tool declares, so this can't fetch arbitrary
    mcp_server paths; each {name} in it comes from the `arg.<name>` query
    parameter (a select that depends on another one)."""
    try:
        declared = await tools.options_templates(Caller(username=account.username, email=account.email))
    except ServerUnavailable as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "mcp_server is unreachable") from error
    if template not in declared or not is_server_path(template):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown options template")
    path = template
    for name in _PLACEHOLDER.findall(template):
        value = request.query_params.get(f"arg.{name}", "")
        if not value:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"arg.{name} is required")
        if value in (".", ".."):
            # Quoting keeps a "/" out of the value, but a dot segment would still climb a level.
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"arg.{name} is not a valid value")
        path = path.replace("{" + name + "}", quote(value, safe=""))
    options = await _call(info.options(account, path))
    return [
        OptionOut(value=o["value"], label=o["label"], extra={k: v for k, v in o.items() if k not in ("value", "label")})
        for o in options
    ]


@router.post("/uploads", status_code=status.HTTP_201_CREATED)
async def upload_file(
    body: UploadIn,
    account: Account = Depends(require_tools),
    info: McpServerInfo = Depends(get_server_info),
    logs: LogWriter = Depends(get_log_writer),
) -> UploadOut:
    """Stores a file on mcp_server for a command's file-path parameter
    (chat_app's command-form drop zone). Base64 in JSON, like attachments."""
    try:
        content = base64.b64decode(body.data, validate=True)
    except (binascii.Error, ValueError) as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "data must be base64") from error
    if len(content) > UPLOAD_MAX_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "The file is larger than 15 MB")
    filename = body.filename.replace("\\", "/").rsplit("/", 1)[-1]
    path = await _call(info.upload(account, filename, content))
    await logs.action(account, "mcp.upload", f"Uploaded '{filename}' ({len(content):,} bytes) for a command")
    return UploadOut(path=path)


_UPSTREAM_FILENAME = re.compile(r"filename\*=UTF-8''([^;]+)", re.IGNORECASE)
_FILENAME_MAX = 150


def _download_name(path: str, upstream_headers: Any) -> str:
    """The file's name: the one mcp_server gave it (its `path` is an opaque id
    that says nothing), cleaned to a bare name; else the last part of `path`."""
    match = _UPSTREAM_FILENAME.search(upstream_headers.get("content-disposition", ""))
    if match:
        name = unquote(match.group(1)).replace("\\", "/").rsplit("/", 1)[-1]
        name = "".join(c for c in name if ord(c) >= 32 and ord(c) != 127).strip()
        if name and name not in (".", ".."):
            return name[:_FILENAME_MAX]
    return path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1] or "download"


@router.get("/server/download")
async def download_file(
    path: str = Query(pattern=DOWNLOAD_PATH_PATTERN),
    account: Account = Depends(require_tools),
    info: McpServerInfo = Depends(get_server_info),
) -> StreamingResponse:
    """A file a tool offered with a `[[DOWNLOAD ...]]` marker, streamed from
    mcp_server. Always an attachment of an opaque type, whatever mcp_server says
    it is, so a file can never run as a page on ember's own origin."""
    upstream = await _call(info.download(account, path))
    name = _download_name(path, upstream.headers)
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name, safe='')}", "Cache-Control": "no-store"}
    # The length is only trustworthy as long as nothing was decoded on the way.
    length = upstream.headers.get("content-length")
    if length and "content-encoding" not in upstream.headers:
        headers["Content-Length"] = length

    async def relay() -> AsyncIterator[bytes]:
        # try/finally rather than a background task: when the browser leaves
        # the generator is closed, and the upstream request still ends.
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()

    return StreamingResponse(relay(), media_type="application/octet-stream", headers=headers)


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
