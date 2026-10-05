# Chat folders and pins: ember_api (phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ember_api stores one-level chat folders and a pinned flag per chat, and exposes them through new routes and the existing chat routes.

**Architecture:** A new `chat_folders` table plus `chats.folder_id` (nullable FK, `ON DELETE CASCADE`) and `chats.pinned`. A `FolderService` owns folder rules (limit, unique name, delete with its chats). `ChatService.update` handles title, folder and pin changes. New router `/api/chat-folders`; the existing `PATCH /api/chats/{id}` accepts `folder_id` and `pinned`.

**Tech Stack:** FastAPI, async SQLAlchemy 2 (SQLite, `PRAGMA foreign_keys=ON`), Alembic (batch mode), pytest with Starlette `TestClient`.

**Spec:** `docs/superpowers/specs/2026-10-05-chat-folders-pins-design.md` (this plan covers its "ember_api" section and phase 1 only; the web phases get their own plans).

## Global Constraints

- One folder level only; at most 30 folders per account.
- Folder name: trimmed, whitespace collapsed, 1 to 60 characters; a duplicate name (ignoring case) is 409.
- Every route needs `chat.use` (`require_permission(CHAT_USE)`); POST/PATCH bodies are JSON.
- A folder or chat id the account does not own is 404 ("Folder not found" / "Chat not found").
- Deleting a folder deletes its chats and their share links in one transaction; it is 409 while any chat in it has a running turn.
- A branched chat inherits the source's `folder_id` and is not pinned.
- Changing folder or pin does not change `updated_at`.
- Run ember_api tests from `ember_api/` with `.venv_ember_api/Scripts/python -m pytest`. The full suite takes about 6 minutes; run targeted files while working and the full suite once at the end.
- Work on branch `feat/chat-folders-pins`. Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

Deviation from the spec, on purpose: the database unique constraint is `(account_id, name)` (case-sensitive), and the case-insensitive check is done in `FolderService`. A functional index on `lower(name)` would make the migration and `tests/test_migrations.py` harder to keep in step for no real gain.

## File Structure

- Create `ember_api/src/models/chat_folder.py`: the `ChatFolder` model.
- Modify `ember_api/src/models/chat.py`: add `folder_id`, `pinned`.
- Modify `ember_api/src/models/__init__.py`: export `ChatFolder`.
- Create `ember_api/migrations/versions/0005_chat_folders.py`: the migration.
- Create `ember_api/src/services/folder_service.py`: `FolderService`, its exceptions, limits.
- Modify `ember_api/src/services/chat_service.py`: `update()`, branch inheritance.
- Create `ember_api/src/routes/chat_folders.py`: the folder routes.
- Modify `ember_api/src/routes/chats.py`: `ChatSummaryOut` fields, `UpdateChatRequest`, the PATCH route.
- Modify `ember_api/src/app.py`: include the new router.
- Create `ember_api/tests/test_chat_folders.py`: all new tests.
- Modify `ember_api/README.md`: API table.

---

### Task 1: Model, migration and list fields

**Files:**
- Create: `ember_api/src/models/chat_folder.py`
- Modify: `ember_api/src/models/chat.py`
- Modify: `ember_api/src/models/__init__.py`
- Create: `ember_api/migrations/versions/0005_chat_folders.py`
- Modify: `ember_api/src/routes/chats.py` (`ChatSummaryOut`, around line 243)
- Test: `ember_api/tests/test_chat_folders.py`

**Interfaces:**
- Produces: `ChatFolder(id, account_id, name, position, created_at)`; `Chat.folder_id: int | None`; `Chat.pinned: bool`; `ChatSummaryOut.folder_id: int | None`, `ChatSummaryOut.pinned: bool`.

- [ ] **Step 1: Write the failing test**

Create `ember_api/tests/test_chat_folders.py`:

```python
from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from tests.test_registration import as_admin


def make_chat(client: TestClient, title: str = "A chat") -> str:
    chat_id = str(uuid.uuid4())
    response = client.put(
        f"/api/chats/{chat_id}",
        json={
            "title": title,
            "agent_id": None,
            "messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}],
        },
    )
    assert response.status_code == 200, response.text
    return chat_id


def test_a_new_chat_is_unfiled_and_not_pinned(client: TestClient) -> None:
    as_admin(client)
    chat_id = make_chat(client)

    row = next(c for c in client.get("/api/chats").json() if c["id"] == chat_id)

    assert row["folder_id"] is None
    assert row["pinned"] is False
    full = client.get(f"/api/chats/{chat_id}").json()
    assert (full["folder_id"], full["pinned"]) == (None, False)
```

- [ ] **Step 2: Run it to see it fail**

Run: `.venv_ember_api/Scripts/python -m pytest tests/test_chat_folders.py -q`
Expected: FAIL with `KeyError: 'folder_id'`.

- [ ] **Step 3: Add the model, columns and migration**

Create `ember_api/src/models/chat_folder.py`:

```python
from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base, utcnow


class ChatFolder(Base):
    """A named group of one account's chats. One level only: a folder holds
    chats, never other folders. Deleting a folder deletes its chats (the
    foreign key on `chats.folder_id` cascades); FolderService also removes the
    chats' share links first, as ChatService.delete does."""

    __tablename__ = "chat_folders"
    __table_args__ = (UniqueConstraint("account_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    # Lower first; ties are broken by id.
    position: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
```

In `ember_api/src/models/chat.py`, change the import line and add two columns after `message_count`:

```python
from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, false
```

```python
    message_count: Mapped[int] = mapped_column(default=0)
    # None: not in a folder. Deleting the folder deletes the chat.
    folder_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_folders.id", ondelete="CASCADE"), index=True, default=None
    )
    pinned: Mapped[bool] = mapped_column(default=False, server_default=false())
```

In `ember_api/src/models/__init__.py`, add `from src.models.chat_folder import ChatFolder` after the `Chat` import and `"ChatFolder",` after `"Chat",` in `__all__`.

Create `ember_api/migrations/versions/0005_chat_folders.py`:

```python
"""Chat folders and pinned chats (chat_folders, chats.folder_id, chats.pinned).

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_folders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("account_id", "name"),
    )
    op.create_index("ix_chat_folders_account_id", "chat_folders", ["account_id"])
    with op.batch_alter_table("chats") as batch:
        batch.add_column(sa.Column("folder_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.create_foreign_key("fk_chats_folder_id", "chat_folders", ["folder_id"], ["id"], ondelete="CASCADE")
        batch.create_index("ix_chats_folder_id", ["folder_id"])


def downgrade() -> None:
    with op.batch_alter_table("chats") as batch:
        batch.drop_index("ix_chats_folder_id")
        batch.drop_constraint("fk_chats_folder_id", type_="foreignkey")
        batch.drop_column("pinned")
        batch.drop_column("folder_id")
    op.drop_index("ix_chat_folders_account_id", table_name="chat_folders")
    op.drop_table("chat_folders")
```

In `ember_api/src/routes/chats.py`, extend `ChatSummaryOut`:

```python
class ChatSummaryOut(BaseModel):
    id: str
    title: str
    agent_id: str | None
    message_count: int
    created_at: datetime
    updated_at: datetime
    # An answer is being written for this chat right now.
    running: bool = False
    # The folder this chat is filed in (chat-folders id), and whether it is pinned.
    folder_id: int | None = None
    pinned: bool = False

    @classmethod
    def of(cls, chat: Chat, running: bool = False) -> ChatSummaryOut:
        return cls(
            id=chat.chat_id,
            title=chat.title,
            agent_id=chat.agent_id,
            message_count=chat.message_count,
            created_at=chat.created_at,
            updated_at=chat.updated_at,
            running=running,
            folder_id=chat.folder_id,
            pinned=chat.pinned,
        )
```

- [ ] **Step 4: Run the new test and the migration test**

Run: `.venv_ember_api/Scripts/python -m pytest tests/test_chat_folders.py tests/test_migrations.py tests/test_chats.py -q`
Expected: all pass. If `test_migrations.py` reports drift, compare the migration with the model (index names, nullability) and fix the migration, not the test.

- [ ] **Step 5: Commit**

```bash
git add ember_api/src/models ember_api/migrations ember_api/src/routes/chats.py ember_api/tests/test_chat_folders.py
git commit -m "feat(ember_api): chat_folders table, chats.folder_id and chats.pinned"
```

---

### Task 2: Folder service and routes (create, list, rename, reorder)

**Files:**
- Create: `ember_api/src/services/folder_service.py`
- Create: `ember_api/src/routes/chat_folders.py`
- Modify: `ember_api/src/app.py` (import and `include_router`, next to `chats.router`)
- Test: `ember_api/tests/test_chat_folders.py`

**Interfaces:**
- Produces (service): `MAX_FOLDERS_PER_ACCOUNT = 30`, `NAME_MAX = 60`; `FolderNotFound`, `FolderLimitError`, `FolderNameTaken`, `FolderBusy` exceptions; `FolderRow(folder: ChatFolder, chat_count: int)`; `FolderService(session, account_id)` with `async list() -> list[FolderRow]`, `async create(name: str) -> ChatFolder`, `async rename(folder_id: int, name: str) -> ChatFolder`, `async reorder(folder_id: int, position: int) -> ChatFolder`, `async count_chats(folder: ChatFolder) -> int`, `async delete(folder_id: int, running: set[str]) -> tuple[str, int]` (added in Task 4).
- Produces (HTTP): `GET/POST /api/chat-folders`, `PATCH/DELETE /api/chat-folders/{id}`; response `FolderOut {id, name, position, chat_count}`.

- [ ] **Step 1: Write the failing tests**

Append to `ember_api/tests/test_chat_folders.py` (move every `import` line in this and later test blocks to the top of the file, keeping them grouped):

```python
import pytest

from src.services import folder_service
from tests.conftest import FakeEmailSender
from tests.test_admin import login, make_member


def new_folder(client: TestClient, name: str = "Work"):
    return client.post("/api/chat-folders", json={"name": name})


def folders(client: TestClient) -> list[dict]:
    response = client.get("/api/chat-folders")
    assert response.status_code == 200, response.text
    return response.json()


# --- access --------------------------------------------------------------------


def test_folders_need_login_and_chat_use(client: TestClient, email: FakeEmailSender) -> None:
    assert client.get("/api/chat-folders").status_code == 401
    assert new_folder(client).status_code == 401
    assert client.patch("/api/chat-folders/1", json={"name": "x"}).status_code == 401
    assert client.delete("/api/chat-folders/1").status_code == 401

    make_member(client, email, verify=False)
    login(client, "alice")
    assert client.get("/api/chat-folders").status_code == 403  # unverified: no permissions


# --- create and list -------------------------------------------------------------


def test_create_and_list(client: TestClient) -> None:
    as_admin(client)

    response = new_folder(client, "  Work   stuff ")

    assert response.status_code == 201
    assert response.json()["name"] == "Work stuff"  # trimmed, spaces collapsed
    assert response.json()["chat_count"] == 0
    new_folder(client, "Home")
    assert [f["name"] for f in folders(client)] == ["Work stuff", "Home"]  # creation order


@pytest.mark.parametrize("name", ["", "   ", "x" * 61])
def test_bad_names_are_refused(client: TestClient, name: str) -> None:
    as_admin(client)

    assert new_folder(client, name).status_code == 422


def test_a_duplicate_name_is_refused_ignoring_case(client: TestClient) -> None:
    as_admin(client)
    assert new_folder(client, "Work").status_code == 201

    assert new_folder(client, "work").status_code == 409
    assert len(folders(client)) == 1


def test_the_folder_limit(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(folder_service, "MAX_FOLDERS_PER_ACCOUNT", 2)
    as_admin(client)
    assert new_folder(client, "a").status_code == 201
    assert new_folder(client, "b").status_code == 201

    response = new_folder(client, "c")

    assert response.status_code == 409
    assert "2" in response.json()["detail"]


def test_folders_are_private_to_their_account(client: TestClient, email: FakeEmailSender) -> None:
    as_admin(client)
    folder_id = new_folder(client, "Secret").json()["id"]
    client.post("/api/auth/logout", json={})
    make_member(client, email)
    login(client, "alice")

    assert folders(client) == []
    assert client.patch(f"/api/chat-folders/{folder_id}", json={"name": "Mine"}).status_code == 404
    assert client.delete(f"/api/chat-folders/{folder_id}").status_code == 404
    assert new_folder(client, "Secret").status_code == 201  # same name is fine for another account


# --- rename and reorder ----------------------------------------------------------


def test_rename(client: TestClient) -> None:
    as_admin(client)
    folder_id = new_folder(client, "Work").json()["id"]
    new_folder(client, "Home")

    response = client.patch(f"/api/chat-folders/{folder_id}", json={"name": "Office"})

    assert response.status_code == 200
    assert response.json()["name"] == "Office"
    assert client.patch(f"/api/chat-folders/{folder_id}", json={"name": "home"}).status_code == 409


def test_renaming_to_its_own_name_with_other_case_is_allowed(client: TestClient) -> None:
    as_admin(client)
    folder_id = new_folder(client, "work").json()["id"]

    assert client.patch(f"/api/chat-folders/{folder_id}", json={"name": "Work"}).json()["name"] == "Work"


def test_reorder_moves_a_folder(client: TestClient) -> None:
    as_admin(client)
    first = new_folder(client, "a").json()["id"]
    new_folder(client, "b")
    new_folder(client, "c")

    assert client.patch(f"/api/chat-folders/{first}", json={"position": 10}).status_code == 200

    assert [f["name"] for f in folders(client)] == ["b", "c", "a"]


def test_a_patch_must_change_something(client: TestClient) -> None:
    as_admin(client)
    folder_id = new_folder(client).json()["id"]

    assert client.patch(f"/api/chat-folders/{folder_id}", json={}).status_code == 422
    assert client.patch(f"/api/chat-folders/{folder_id}", json={"position": -1}).status_code == 422
```

- [ ] **Step 2: Run to see them fail**

Run: `.venv_ember_api/Scripts/python -m pytest tests/test_chat_folders.py -q`
Expected: FAIL (`ModuleNotFoundError: src.services.folder_service`).

- [ ] **Step 3: Write the service**

Create `ember_api/src/services/folder_service.py`:

```python
"""Per-account chat folders (one level: a folder holds chats, never folders).

Every lookup filters by account, so another user's folder id behaves exactly
like a nonexistent one.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Chat, ChatFolder, SharedChat

MAX_FOLDERS_PER_ACCOUNT = 30
NAME_MAX = 60  # the chat_folders.name column


class FolderNotFound(Exception):
    """Unknown id, or another account's (deliberately indistinguishable)."""


class FolderLimitError(Exception):
    """Too many folders (maps to 409)."""


class FolderNameTaken(Exception):
    """Another folder of this account already has the name, ignoring case."""


class FolderBusy(Exception):
    """A chat in the folder has an answer being written (maps to 409)."""


@dataclass(frozen=True)
class FolderRow:
    folder: ChatFolder
    chat_count: int


class FolderService:
    def __init__(self, session: AsyncSession, account_id: int) -> None:
        self._session = session
        self._account_id = account_id

    async def list(self) -> list[FolderRow]:
        """In display order (position, then id), each with its chat count."""
        rows = await self._session.execute(
            select(ChatFolder, func.count(Chat.id))
            .outerjoin(Chat, Chat.folder_id == ChatFolder.id)
            .where(ChatFolder.account_id == self._account_id)
            .group_by(ChatFolder.id)
            .order_by(ChatFolder.position, ChatFolder.id)
        )
        return [FolderRow(folder, count) for folder, count in rows]

    async def create(self, name: str) -> ChatFolder:
        """Appended after the existing folders."""
        count = await self._session.scalar(
            select(func.count()).select_from(ChatFolder).where(ChatFolder.account_id == self._account_id)
        )
        if (count or 0) >= MAX_FOLDERS_PER_ACCOUNT:
            raise FolderLimitError(f"At most {MAX_FOLDERS_PER_ACCOUNT} folders per account - delete some first")
        await self._ensure_name_free(name, except_id=None)
        last = await self._session.scalar(
            select(func.coalesce(func.max(ChatFolder.position), -1)).where(ChatFolder.account_id == self._account_id)
        )
        folder = ChatFolder(account_id=self._account_id, name=name, position=(last or 0) + 1)
        self._session.add(folder)
        await self._commit_unique()
        return folder

    async def rename(self, folder_id: int, name: str) -> ChatFolder:
        folder = await self._get(folder_id)
        await self._ensure_name_free(name, except_id=folder.id)
        folder.name = name
        await self._commit_unique()
        return folder

    async def reorder(self, folder_id: int, position: int) -> ChatFolder:
        folder = await self._get(folder_id)
        folder.position = position
        await self._session.commit()
        return folder

    async def count_chats(self, folder: ChatFolder) -> int:
        count = await self._session.scalar(
            select(func.count()).select_from(Chat).where(Chat.folder_id == folder.id)
        )
        return count or 0

    async def _get(self, folder_id: int) -> ChatFolder:
        folder = await self._session.scalar(
            select(ChatFolder).where(ChatFolder.id == folder_id, ChatFolder.account_id == self._account_id)
        )
        if folder is None:
            raise FolderNotFound(folder_id)
        return folder

    async def _ensure_name_free(self, name: str, except_id: int | None) -> None:
        query = select(ChatFolder.id).where(
            ChatFolder.account_id == self._account_id, func.lower(ChatFolder.name) == name.lower()
        )
        if except_id is not None:
            query = query.where(ChatFolder.id != except_id)
        if await self._session.scalar(query) is not None:
            raise FolderNameTaken(name)

    async def _commit_unique(self) -> None:
        try:
            await self._session.commit()
        except IntegrityError as error:
            # Lost a race with a concurrent create or rename of the same name.
            await self._session.rollback()
            raise FolderNameTaken("name") from error
```

(`delete` and `SharedChat` are imported for Task 4; leave them in.)

- [ ] **Step 4: Write the routes and register them**

Create `ember_api/src/routes/chat_folders.py`:

```python
"""/api/chat-folders: the logged-in account's chat folders (chat.use)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from src.deps import get_db_session, get_log_writer, require_permission
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
```

In `ember_api/src/app.py`, add `chat_folders,` to the routes import list (alphabetical, next to `chats,`) and `app.include_router(chat_folders.router)` right after `app.include_router(chats.router)`.

(`Response`, `FolderBusy` are imported for Task 4.)

- [ ] **Step 5: Run the tests**

Run: `.venv_ember_api/Scripts/python -m pytest tests/test_chat_folders.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add ember_api/src/services/folder_service.py ember_api/src/routes/chat_folders.py ember_api/src/app.py ember_api/tests/test_chat_folders.py
git commit -m "feat(ember_api): chat folder routes (create, list, rename, reorder)"
```

---

### Task 3: Move and pin chats; branches keep the folder

**Files:**
- Modify: `ember_api/src/services/chat_service.py` (imports, new `update`, `branch`)
- Modify: `ember_api/src/routes/chats.py` (imports, `UpdateChatRequest`, the PATCH route at about line 458)
- Test: `ember_api/tests/test_chat_folders.py`

**Interfaces:**
- Consumes: `FolderNotFound` from `src.services.folder_service`, `ChatFolder` model.
- Produces: `ChatService.update(chat_id: str, *, title: str | None = None, folder_id: int | None | object = UNSET, pinned: bool | None = None) -> Chat`; `chat_service.UNSET` sentinel; `PATCH /api/chats/{id}` body `{title?, folder_id?, pinned?}` (at least one).

- [ ] **Step 1: Write the failing tests**

Append to `ember_api/tests/test_chat_folders.py`:

```python
# --- moving and pinning chats ------------------------------------------------------


def listed(client: TestClient, chat_id: str) -> dict:
    return next(c for c in client.get("/api/chats").json() if c["id"] == chat_id)


def test_a_chat_can_be_moved_into_a_folder_and_out_again(client: TestClient) -> None:
    as_admin(client)
    chat_id = make_chat(client)
    folder_id = new_folder(client).json()["id"]

    moved = client.patch(f"/api/chats/{chat_id}", json={"folder_id": folder_id})

    assert moved.status_code == 200
    assert moved.json()["folder_id"] == folder_id
    assert listed(client, chat_id)["folder_id"] == folder_id
    assert folders(client)[0]["chat_count"] == 1

    out = client.patch(f"/api/chats/{chat_id}", json={"folder_id": None})

    assert out.json()["folder_id"] is None
    assert folders(client)[0]["chat_count"] == 0


def test_pinning_keeps_the_folder(client: TestClient) -> None:
    as_admin(client)
    chat_id = make_chat(client)
    folder_id = new_folder(client).json()["id"]
    client.patch(f"/api/chats/{chat_id}", json={"folder_id": folder_id})

    pinned = client.patch(f"/api/chats/{chat_id}", json={"pinned": True}).json()

    assert (pinned["pinned"], pinned["folder_id"]) == (True, folder_id)
    assert client.patch(f"/api/chats/{chat_id}", json={"pinned": False}).json()["pinned"] is False
    assert listed(client, chat_id)["folder_id"] == folder_id


def test_moving_or_pinning_does_not_change_the_order(client: TestClient) -> None:
    as_admin(client)
    chat_id = make_chat(client)
    before = listed(client, chat_id)["updated_at"]
    folder_id = new_folder(client).json()["id"]

    client.patch(f"/api/chats/{chat_id}", json={"folder_id": folder_id, "pinned": True})

    assert listed(client, chat_id)["updated_at"] == before


def test_a_rename_still_works_and_can_be_combined(client: TestClient) -> None:
    as_admin(client)
    chat_id = make_chat(client)
    folder_id = new_folder(client).json()["id"]

    body = client.patch(f"/api/chats/{chat_id}", json={"title": "  New   title ", "folder_id": folder_id}).json()

    assert (body["title"], body["folder_id"]) == ("New title", folder_id)


def test_an_empty_or_blank_patch_is_refused(client: TestClient) -> None:
    as_admin(client)
    chat_id = make_chat(client)

    assert client.patch(f"/api/chats/{chat_id}", json={}).status_code == 422
    assert client.patch(f"/api/chats/{chat_id}", json={"title": None}).status_code == 422
    assert client.patch(f"/api/chats/{chat_id}", json={"title": "   "}).status_code == 422


def test_moving_into_someone_elses_or_a_missing_folder_is_404(client: TestClient, email: FakeEmailSender) -> None:
    as_admin(client)
    foreign = new_folder(client, "Admin only").json()["id"]
    client.post("/api/auth/logout", json={})
    make_member(client, email)
    login(client, "alice")
    chat_id = make_chat(client)

    assert client.patch(f"/api/chats/{chat_id}", json={"folder_id": foreign}).status_code == 404
    assert client.patch(f"/api/chats/{chat_id}", json={"folder_id": 99999}).status_code == 404
    assert listed(client, chat_id)["folder_id"] is None


def test_a_branch_stays_in_the_source_folder_and_is_not_pinned(client: TestClient) -> None:
    as_admin(client)
    chat_id = make_chat(client)
    folder_id = new_folder(client).json()["id"]
    client.patch(f"/api/chats/{chat_id}", json={"folder_id": folder_id, "pinned": True})

    branch = client.post(f"/api/chats/{chat_id}/branch", json={"upto": 1})

    assert branch.status_code == 201, branch.text
    assert (branch.json()["folder_id"], branch.json()["pinned"]) == (folder_id, False)
```

- [ ] **Step 2: Run to see them fail**

Run: `.venv_ember_api/Scripts/python -m pytest tests/test_chat_folders.py -q`
Expected: the new tests FAIL (the PATCH requires `title`, answers 422 or ignores the fields).

- [ ] **Step 3: Add `ChatService.update` and branch inheritance**

In `ember_api/src/services/chat_service.py`, change the imports and add the sentinel:

```python
from src.models import Chat, ChatFolder, SharedChat
from src.services.folder_service import FolderNotFound
```

```python
TITLE_MAX = 120  # the chats.title column
# "folder_id was not sent", as opposed to None ("take it out of its folder").
UNSET: Any = object()
```

Add the method after `rename`:

```python
    async def update(
        self, chat_id: str, *, title: str | None = None, folder_id: int | None = UNSET, pinned: bool | None = None
    ) -> Chat:
        """Changes whichever of title, folder and pin are given. `folder_id`
        None takes the chat out of its folder; a folder of another account is
        FolderNotFound. Does not touch updated_at: filing a chat is not
        activity, and must not reorder the list."""
        chat = await self.get(chat_id)
        if folder_id is not UNSET:
            if folder_id is not None:
                owned = await self._session.scalar(
                    select(ChatFolder.id).where(ChatFolder.id == folder_id, ChatFolder.account_id == self._account_id)
                )
                if owned is None:
                    raise FolderNotFound(folder_id)
            chat.folder_id = folder_id
        if title is not None:
            chat.title = title
        if pinned is not None:
            chat.pinned = pinned
        await self._session.commit()
        return chat
```

Change the last line of `branch` from `return await self.put(...)` to:

```python
        branched = await self.put(str(uuid.uuid4()), title, source.agent_id, messages[: upto + 1])
        if source.folder_id is not None:
            branched.folder_id = source.folder_id
            await self._session.commit()
        return branched
```

Also update the `branch` docstring's last sentence to: `It keeps the source's agent and folder (never its pin) and is titled "Branch of <title>".`

- [ ] **Step 4: Replace the PATCH route**

In `ember_api/src/routes/chats.py`: add `model_validator` to the pydantic import (`from pydantic import BaseModel, Field, field_validator, model_validator`), add `UNSET` to the `chat_service` import list, add `from src.services.folder_service import FolderNotFound`, then add the request model after `RenameRequest` is defined (keep `RenameRequest`, `PutChatRequest` uses it):

```python
class UpdateChatRequest(BaseModel):
    """Any of: a new title, a folder (null: out of its folder), a pin."""

    title: str | None = Field(default=None, max_length=TITLE_MAX)
    folder_id: int | None = None
    pinned: bool | None = None

    @field_validator("title")
    @classmethod
    def clean_title(cls, title: str | None) -> str | None:
        return None if title is None else _clean_title(title)

    @model_validator(mode="after")
    def something_to_change(self) -> UpdateChatRequest:
        if self.title is None and self.pinned is None and "folder_id" not in self.model_fields_set:
            raise ValueError("send a title, a folder_id or pinned")
        return self
```

Replace the PATCH route:

```python
@router.patch("/{chat_id}")
async def update_chat(
    body: UpdateChatRequest,
    chat_id: str = ChatId,
    account: Account = Depends(require_chat),
    chats: ChatService = Depends(get_chat_service),
    turns: TurnRegistry = Depends(get_turns),
) -> ChatSummaryOut:
    """Renames, files (folder_id; null takes it out of its folder) or pins a
    chat. Allowed while an answer is being written: it changes no messages."""
    changes: dict[str, Any] = {"title": body.title, "pinned": body.pinned}
    if "folder_id" in body.model_fields_set:
        changes["folder_id"] = body.folder_id
    try:
        chat = await chats.update(chat_id, **changes)
    except ChatNotFound as error:
        raise _not_found() from error
    except FolderNotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Folder not found") from error
    return ChatSummaryOut.of(chat, turns.is_running(account.id, chat_id))
```

`ChatService.rename` stays (other callers and tests may use it).

- [ ] **Step 5: Run the folder tests and the existing chat tests**

Run: `.venv_ember_api/Scripts/python -m pytest tests/test_chat_folders.py tests/test_chats.py tests/test_branch.py tests/test_shares.py -q`
Expected: all pass. If an existing rename test now fails on a status code, read its assertion first; the contract for `{"title": ...}` is unchanged.

- [ ] **Step 6: Commit**

```bash
git add ember_api/src/services/chat_service.py ember_api/src/routes/chats.py ember_api/tests/test_chat_folders.py
git commit -m "feat(ember_api): move and pin chats; branches keep the folder"
```

---

### Task 4: Delete a folder with its chats

**Files:**
- Modify: `ember_api/src/services/folder_service.py` (add `delete`)
- Modify: `ember_api/src/routes/chat_folders.py` (add the DELETE route)
- Test: `ember_api/tests/test_chat_folders.py`

**Interfaces:**
- Consumes: `FolderBusy`, `TurnRegistry.running_chat_ids(account_id) -> set[str]` and `TurnRegistry.discard(account_id, chat_id)` from `src.services.turns`, `get_turns` from `src.deps`.
- Produces: `FolderService.delete(folder_id: int, running: set[str]) -> tuple[str, int]` returning the folder's name and how many chats went with it; `DELETE /api/chat-folders/{id}` answering 204, 404, or 409 when a chat in it is answering.

- [ ] **Step 1: Write the failing tests**

Append to `ember_api/tests/test_chat_folders.py`:

```python
from tests.conftest import FakeAgent
from tests.test_turns import events, start


def put_in(client: TestClient, folder_id: int, count: int) -> list[str]:
    ids = [make_chat(client, f"chat {i}") for i in range(count)]
    for chat_id in ids:
        assert client.patch(f"/api/chats/{chat_id}", json={"folder_id": folder_id}).status_code == 200
    return ids


def test_deleting_a_folder_deletes_its_chats_and_their_shares(client: TestClient) -> None:
    as_admin(client)
    keep = make_chat(client, "unfiled")
    other = new_folder(client, "Other").json()["id"]
    (kept_elsewhere,) = put_in(client, other, 1)
    doomed = new_folder(client, "Doomed").json()["id"]
    first, second = put_in(client, doomed, 2)
    token = client.post(f"/api/chats/{first}/shares", json={}).json()["token"]
    assert client.get(f"/api/shared/{token}").status_code == 200

    response = client.delete(f"/api/chat-folders/{doomed}")

    assert response.status_code == 204
    assert [f["name"] for f in folders(client)] == ["Other"]
    remaining = {c["id"] for c in client.get("/api/chats").json()}
    assert remaining == {keep, kept_elsewhere}
    assert client.get(f"/api/chats/{second}").status_code == 404
    assert client.get(f"/api/shared/{token}").status_code == 404  # the link died with the chat


def test_deleting_an_empty_folder(client: TestClient) -> None:
    as_admin(client)
    folder_id = new_folder(client).json()["id"]

    assert client.delete(f"/api/chat-folders/{folder_id}").status_code == 204
    assert folders(client) == []
    assert client.delete(f"/api/chat-folders/{folder_id}").status_code == 404


def test_a_folder_with_an_answering_chat_cannot_be_deleted(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    folder_id = new_folder(client).json()["id"]
    (chat_id,) = put_in(client, folder_id, 1)
    agent.hold = True
    assert start(client, chat_id, "q3").status_code == 202

    try:
        response = client.delete(f"/api/chat-folders/{folder_id}")
        assert response.status_code == 409
        assert "answer" in response.json()["detail"]
        assert len(folders(client)) == 1  # nothing was deleted
        assert client.get(f"/api/chats/{chat_id}").status_code == 200
    finally:
        agent.release()
    events(client, chat_id)

    assert client.delete(f"/api/chat-folders/{folder_id}").status_code == 204
    assert client.get(f"/api/chats/{chat_id}").status_code == 404


def test_deleting_a_folder_writes_an_audit_entry(client: TestClient) -> None:
    as_admin(client)
    folder_id = new_folder(client, "Audit me").json()["id"]
    put_in(client, folder_id, 2)

    client.delete(f"/api/chat-folders/{folder_id}")

    entries = client.get("/api/logs").json()
    messages = [e["message"] for e in (entries["entries"] if isinstance(entries, dict) else entries)]
    assert any('Deleted folder "Audit me" and its 2 chat' in m for m in messages)
```

The last test reads `/api/logs`; before running, open `ember_api/tests/test_logs.py` (or `routes/logs.py`) and adjust the way the entries are read so it matches the real response shape and permission. If the logs route needs a parameter, pass it.

- [ ] **Step 2: Run to see them fail**

Run: `.venv_ember_api/Scripts/python -m pytest tests/test_chat_folders.py -q -k "deleting or deleted or answering"`
Expected: FAIL (405 Method Not Allowed on DELETE).

- [ ] **Step 3: Add `FolderService.delete`**

Append to `FolderService` in `ember_api/src/services/folder_service.py`:

```python
    async def delete(self, folder_id: int, running: set[str]) -> tuple[str, int]:
        """Deletes the folder and every chat in it, with those chats' share
        links, in one transaction. `running` holds this account's chat ids
        that have an answer being written: if any is in the folder nothing is
        deleted (FolderBusy). Returns (folder name, chats deleted)."""
        folder = await self._get(folder_id)
        chat_ids = list(await self._session.scalars(select(Chat.chat_id).where(Chat.folder_id == folder.id)))
        if running.intersection(chat_ids):
            raise FolderBusy(folder_id)
        name = folder.name
        if chat_ids:
            await self._session.execute(
                delete(SharedChat).where(SharedChat.account_id == self._account_id, SharedChat.chat_id.in_(chat_ids))
            )
            await self._session.execute(
                delete(Chat).where(Chat.account_id == self._account_id, Chat.folder_id == folder.id)
            )
        await self._session.delete(folder)
        await self._session.commit()
        return name, len(chat_ids)
```

- [ ] **Step 4: Add the DELETE route**

In `ember_api/src/routes/chat_folders.py`, extend the imports: `from src.deps import get_db_session, get_log_writer, get_turns, require_permission` and `from src.services.turns import TurnRegistry`. Add at the end:

```python
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
```

- [ ] **Step 5: Run the folder tests**

Run: `.venv_ember_api/Scripts/python -m pytest tests/test_chat_folders.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add ember_api/src/services/folder_service.py ember_api/src/routes/chat_folders.py ember_api/tests/test_chat_folders.py
git commit -m "feat(ember_api): delete a chat folder together with its chats"
```

---

### Task 5: README, full suite, final check

**Files:**
- Modify: `ember_api/README.md` (API table near the `/api/chats` rows, about line 150 to 170; the feature list; the layout section if it lists services and routes)

- [ ] **Step 1: Update the README**

Open `ember_api/README.md`, find the `PATCH /api/chats/{id}` row and the surrounding chat rows. Change the PATCH row to describe `{title?, folder_id?, pinned?}` (at least one; `folder_id: null` takes the chat out of its folder; `404` unknown chat or a folder that is not this account's; allowed while an answer is being written; filing and pinning do not change `updated_at`). Add `folder_id` and `pinned` to the chat list and chat rows' response shape. Add these rows after the chat rows, in the same table style:

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `GET` | `/api/chat-folders` | `chat.use` | `[{id, name, position, chat_count}]` in display order. |
| `POST` | `/api/chat-folders` | `chat.use` | `{name}` (1 to 60 characters, trimmed) -> `201` folder. `409` duplicate name (ignoring case) or 30 folders already. Logged as `chat_folder.create`. |
| `PATCH` | `/api/chat-folders/{id}` | `chat.use` | `{name?, position?}` (at least one). `404` unknown, `409` duplicate name. Logged as `chat_folder.rename` for renames. |
| `DELETE` | `/api/chat-folders/{id}` | `chat.use` | Deletes the folder **and every chat in it**, with their share links. `404` unknown, `409` while a chat in it is writing an answer. Logged as `chat_folder.delete`. |

Add one sentence to the features or notes part: folders are one level; a branch stays in its source's folder and is not pinned; the schema change is migration `0005`.

- [ ] **Step 2: Run the full suite**

Run: `.venv_ember_api/Scripts/python -m pytest -q`
Expected: all pass (about 6 minutes; 790 before this work plus the new tests).

- [ ] **Step 3: Check chat_cli is unaffected**

Run: `grep -n "patch\|PATCH" chat_cli/src/api.py` from the repo root, and confirm every PATCH call there sends only `{"title": ...}`, which this plan keeps valid. Optionally run `pytest -q` in `chat_cli/`.

- [ ] **Step 4: Commit**

```bash
git add ember_api/README.md
git commit -m "docs(ember_api): chat folders and pins in the API table"
```

- [ ] **Step 5: Report**

Report: what changed, the test results, and a short manual checklist for the user (they test by hand): with `curl` or the browser devtools, create a folder, move a chat in, pin it, branch it, try to delete the folder while an answer is running, delete it afterwards, and check the chats and their share link are gone. The web phases (2 to 5 in the spec) get their own plans.

---

## Self-review

**Spec coverage (ember_api section and phase 1):** model and migration (Task 1); name rules, limit 30, duplicate 409 (Task 2); routes list/create/patch (Task 2); delete with chats, running guard, one transaction, share links removed (Task 4); `PATCH /api/chats` accepts `folder_id` and `pinned`, 404 for foreign folders (Task 3); list rows carry both fields (Task 1); branch inherits folder and is not pinned (Task 3); audit log entries for create, rename, delete (Tasks 2 and 4); README (Task 5). Not in this plan on purpose: chat moves are not audited (the spec lists audit for folder routes only).

**Spec difference:** the unique constraint is case-sensitive in the database and the case-insensitive check lives in the service (stated under Global Constraints). The spec says moving a running chat is locked; this plan allows it in the API (it changes no messages) and leaves locking to the web UI in phase 4.

**Placeholders:** none; the one open lookup is the shape of the `/api/logs` response in Task 4 Step 1, which has an explicit instruction to read `tests/test_logs.py` and adjust.

**Type consistency:** `FolderService` methods, `FolderRow`, `UNSET`, `UpdateChatRequest`, `ChatService.update` and the exception names are used with the same names in every task.
