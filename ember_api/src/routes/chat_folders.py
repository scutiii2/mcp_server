"""/api/chat-folders: the logged-in account's chat folders (chat.use)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from src.deps import get_db_session, get_log_writer, get_turns, require_permission
from src.models import Account, ChatFolder
from src.services.folder_service import (
    NAME_MAX,
    FolderBusy,
    FolderLimitError,
    FolderNameTaken,
    FolderNotFound,
    FolderRow,
    FolderService,
)
from src.services.log_service import LogWriter
from src.services.permissions import CHAT_USE
from src.services.turns import TurnRegistry

router = APIRouter(prefix="/api/chat-folders", tags=["chat-folders"])

require_chat = require_permission(CHAT_USE)


def get_folder_service(
    account: Account = Depends(require_chat),
    session: AsyncSession = Depends(get_db_session),
) -> FolderService:
    return FolderService(session, account.id)


def _clean_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise ValueError("name must not be blank")
    return cleaned


class CreateFolderRequest(BaseModel):
    name: str = Field(max_length=NAME_MAX)

    @field_validator("name")
    @classmethod
    def clean_name(cls, name: str) -> str:
        return _clean_name(name)


class UpdateFolderRequest(BaseModel):
    name: str | None = Field(default=None, max_length=NAME_MAX)
    position: int | None = Field(default=None, ge=0, le=100_000)

    @field_validator("name")
    @classmethod
    def clean_name(cls, name: str | None) -> str | None:
        return None if name is None else _clean_name(name)

    @model_validator(mode="after")
    def something_to_change(self) -> UpdateFolderRequest:
        if self.name is None and self.position is None:
            raise ValueError("send a name or a position")
        return self


class FolderOut(BaseModel):
    id: int
    name: str
    position: int
    chat_count: int

    @classmethod
    def of(cls, folder: ChatFolder, chat_count: int) -> FolderOut:
        return cls(id=folder.id, name=folder.name, position=folder.position, chat_count=chat_count)

    @classmethod
    def of_row(cls, row: FolderRow) -> FolderOut:
        return cls.of(row.folder, row.chat_count)


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Folder not found")


def _conflict(error: Exception) -> HTTPException:
    if isinstance(error, FolderLimitError):
        return HTTPException(status.HTTP_409_CONFLICT, str(error))
    return HTTPException(status.HTTP_409_CONFLICT, "A folder with that name already exists")


@router.get("")
async def list_folders(folders: FolderService = Depends(get_folder_service)) -> list[FolderOut]:
    return [FolderOut.of_row(row) for row in await folders.list()]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_folder(
    body: CreateFolderRequest,
    account: Account = Depends(require_chat),
    folders: FolderService = Depends(get_folder_service),
    logs: LogWriter = Depends(get_log_writer),
) -> FolderOut:
    try:
        folder = await folders.create(body.name)
    except (FolderLimitError, FolderNameTaken) as error:
        raise _conflict(error) from error
    await logs.action(account, "chat_folder.create", f'Created folder "{folder.name}"')
    return FolderOut.of(folder, 0)


@router.patch("/{folder_id}")
async def update_folder(
    folder_id: int,
    body: UpdateFolderRequest,
    account: Account = Depends(require_chat),
    folders: FolderService = Depends(get_folder_service),
    logs: LogWriter = Depends(get_log_writer),
) -> FolderOut:
    try:
        if body.name is not None:
            folder = await folders.rename(folder_id, body.name)
            await logs.action(account, "chat_folder.rename", f'Renamed a folder to "{folder.name}"')
        if body.position is not None:
            folder = await folders.reorder(folder_id, body.position)
    except FolderNotFound as error:
        raise _not_found() from error
    except FolderNameTaken as error:
        raise _conflict(error) from error
    return FolderOut.of(folder, await folders.count_chats(folder))


@router.delete("/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(
    folder_id: int,
    account: Account = Depends(require_chat),
    folders: FolderService = Depends(get_folder_service),
    turns: TurnRegistry = Depends(get_turns),
    logs: LogWriter = Depends(get_log_writer),
) -> Response:
    """Deletes the folder and every chat in it. Refused while one of those
    chats has an answer being written, so a live answer is never cut off."""
    try:
        name, chat_count = await folders.delete(folder_id, turns.running_chat_ids(account.id))
    except FolderNotFound as error:
        raise _not_found() from error
    except FolderBusy as error:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A chat in this folder is still writing an answer. Wait for it to finish."
        ) from error
    await logs.action(account, "chat_folder.delete", f'Deleted folder "{name}" and its {chat_count} chat(s)')
    return Response(status_code=status.HTTP_204_NO_CONTENT)
