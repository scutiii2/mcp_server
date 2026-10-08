"""/api/user-extensions: the logged-in account's own MCP servers ("private
extensions", chat.use). Private to the account: another account's slug is 404.
The reply carries each one's live status and tools (from ai_agent, cached for a
minute) and the NAMES of its headers; a header value is never sent back."""

from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from src.deps import (
    get_db_session,
    get_extension_probe,
    get_log_writer,
    get_secret_box,
    require_permission,
)
from src.models import Account
from src.routes.mcp import get_agent_directory
from src.services.agent_directory import AgentDirectory
from src.services.agent_gateway import Caller
from src.services.extension_probe import ExtensionProbe, ProbeResult
from src.services.log_service import LogWriter
from src.services.permissions import CHAT_USE
from src.services.secret_box import SecretBox
from src.services.user_extension_service import (
    MAX_SLUG,
    SLUG_PATTERN,
    ExtensionLimit,
    ExtensionNotFound,
    InvalidExtension,
    StoredExtension,
    UserExtensionService,
)

router = APIRouter(prefix="/api/user-extensions", tags=["user-extensions"])

require_chat = require_permission(CHAT_USE)

NOT_PROBED = ProbeResult("unknown", None, ())


def get_service(
    account: Account = Depends(require_chat),
    session: AsyncSession = Depends(get_db_session),
    box: SecretBox = Depends(get_secret_box),
) -> UserExtensionService:
    return UserExtensionService(session, account.id, box)


class ExtensionCreate(BaseModel):
    label: str = Field(max_length=200)
    url: str = Field(max_length=2000)
    description: str = Field(default="", max_length=1000)
    headers: dict[str, str] | None = None


class ExtensionUpdate(BaseModel):
    label: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=2000)
    description: str | None = Field(default=None, max_length=1000)
    # When present (even empty) it replaces every header; the browser sends it only if the user retyped them.
    headers: dict[str, str] | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def something_to_change(self) -> ExtensionUpdate:
        if not self.model_fields_set:
            raise ValueError("send something to change")
        return self


class ExtensionOut(BaseModel):
    id: str
    label: str
    description: str
    url: str
    header_names: list[str]
    enabled: bool
    status: str
    error: str | None
    tools: list[str]

    @classmethod
    def of(cls, stored: StoredExtension, probe: ProbeResult) -> ExtensionOut:
        row = stored.row
        return cls(
            id=row.slug,
            label=row.label,
            description=row.description,
            url=row.url,
            header_names=stored.header_names,
            enabled=row.enabled,
            status=probe.status,
            error=probe.error,
            tools=list(probe.tools),
        )


def _caller(account: Account) -> Caller:
    return Caller(username=account.username, email=account.email)


def _host(url: str) -> str:
    return urlsplit(url).hostname or ""


async def _probe(
    stored: StoredExtension, account: Account, probe: ExtensionProbe, directory: AgentDirectory
) -> ProbeResult:
    if not stored.row.enabled:
        return NOT_PROBED
    agent = await directory.entry()
    return await probe.check(agent.url if agent else None, _caller(account), account.id, stored)


@router.get("")
async def list_extensions(
    account: Account = Depends(require_chat),
    service: UserExtensionService = Depends(get_service),
    probe: ExtensionProbe = Depends(get_extension_probe),
    directory: AgentDirectory = Depends(get_agent_directory),
) -> list[ExtensionOut]:
    stored = await service.list()
    results = await asyncio.gather(*(_probe(item, account, probe, directory) for item in stored))
    return [ExtensionOut.of(item, result) for item, result in zip(stored, results)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_extension(
    body: ExtensionCreate,
    account: Account = Depends(require_chat),
    service: UserExtensionService = Depends(get_service),
    probe: ExtensionProbe = Depends(get_extension_probe),
    directory: AgentDirectory = Depends(get_agent_directory),
    logs: LogWriter = Depends(get_log_writer),
) -> ExtensionOut:
    """Saves the extension (even if it cannot be reached right now) and probes it once."""
    try:
        stored = await service.create(
            label=body.label, url=body.url, description=body.description, headers=body.headers
        )
    except InvalidExtension as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    except ExtensionLimit as error:
        raise HTTPException(status.HTTP_409_CONFLICT, "You have added as many private extensions as allowed") from error
    await logs.action(
        account, "account.user_extension_add", f"Added private extension '{stored.row.label}' ({_host(stored.row.url)})"
    )
    return ExtensionOut.of(stored, await _probe(stored, account, probe, directory))


@router.patch("/{slug}")
async def update_extension(
    body: ExtensionUpdate,
    slug: str = Path(pattern=SLUG_PATTERN, max_length=MAX_SLUG),
    account: Account = Depends(require_chat),
    service: UserExtensionService = Depends(get_service),
    probe: ExtensionProbe = Depends(get_extension_probe),
    directory: AgentDirectory = Depends(get_agent_directory),
    logs: LogWriter = Depends(get_log_writer),
) -> ExtensionOut:
    try:
        was_enabled = (await service.get(slug)).row.enabled
        stored = await service.update(
            slug,
            label=body.label,
            description=body.description,
            url=body.url,
            headers=body.headers,
            enabled=body.enabled,
        )
    except ExtensionNotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such extension") from error
    except InvalidExtension as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    if body.url is not None or body.headers is not None:
        probe.forget(account.id, slug)
    label = stored.row.label
    only_enabled = not (body.model_fields_set - {"enabled"})
    if only_enabled and body.enabled is not None and body.enabled != was_enabled:
        message = f"{'Enabled' if body.enabled else 'Disabled'} private extension '{label}'"
    else:
        message = f"Edited private extension '{label}' ({_host(stored.row.url)})"
    await logs.action(account, "account.user_extension_edit", message)
    return ExtensionOut.of(stored, await _probe(stored, account, probe, directory))


@router.delete("/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_extension(
    slug: str = Path(pattern=SLUG_PATTERN, max_length=MAX_SLUG),
    account: Account = Depends(require_chat),
    service: UserExtensionService = Depends(get_service),
    probe: ExtensionProbe = Depends(get_extension_probe),
    logs: LogWriter = Depends(get_log_writer),
) -> Response:
    try:
        label = (await service.get(slug)).row.label
        await service.delete(slug)
    except ExtensionNotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such extension") from error
    probe.forget(account.id, slug)
    await logs.action(account, "account.user_extension_remove", f"Removed private extension '{label}'")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
