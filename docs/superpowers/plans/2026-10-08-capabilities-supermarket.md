# Capabilities Supermarket (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store, per account in ember_api, which built-in capabilities and server-listed extensions the account has added; show only those on the Capabilities page; add a Supermarket page (`/capabilities/supermarket`) to add more.

**Architecture:** A new `account_capabilities` table (a row means enabled) with `GET /api/account-capabilities` and `PUT /api/account-capabilities/{kind}/{key}`. Both return the full enabled set plus `disabled_tools`, which ember_api computes from mcp_server's capability list, so chat-only accounts need no `tools.use`. ember_web gets an `accountCapabilities` Pinia store (modelled on `navPrefs`) that replaces the `localStorage` switches in the chat store, a rewritten Capabilities page, and a new Supermarket view.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy async / Alembic / pytest (ember_api); Vue 3 / TypeScript / Pinia / vue-router / vitest / Playwright (ember_web).

**Spec:** `docs/superpowers/specs/2026-10-08-capabilities-supermarket-design.md`. This plan makes one change to the spec, applied in Task 0: ember_api computes `disabled_tools` and returns it, instead of the browser reading the capability list. Reason: `GET /api/capabilities` needs `tools.use`, and accounts with only `chat.use` could not work out which tools to disable.

## Global Constraints

- Migration revision is `0007` (`down_revision = "0006"`). `0006_nav_preferences` has already merged to `main`.
- Table `account_capabilities`: `account_id` FK `accounts.id` `ON DELETE CASCADE`, `kind` String(16) (`capability` or `extension`), `item_id` String(64) (the spec's "key"; named `item_id` because `key` is an SQL keyword), `created_at` naive UTC, primary key `(account_id, kind, item_id)`. A row means enabled.
- Item keys match `^[A-Za-z0-9_.-]{1,64}$`. At most 200 rows per account.
- Routes need only a logged-in account (like `/api/nav-preferences`). `PUT` is one call per item, never "replace the whole set".
- New account default: everything disabled. No migration of the old `localStorage` keys; they are ignored.
- A user can only disable a built-in capability or server-listed extension, never remove it. Add and Remove extension stay `admin.manage` in this phase.
- Supermarket route is `/capabilities/supermarket`, declared before `/capabilities/:name`. Its filter chips (Enabled / Disabled) are mutually exclusive; clicking the active chip clears it; state lives in the URL query `?state=enabled|disabled`. No "All" tab; two stacked sections, Built-in and Extensions.
- The status dot keeps today's meaning. No status field is added in this phase.
- Chat never sends a question until the account store has loaded; it never falls back to "everything on".
- ember_web UI follows the `ember-design-system` skill: tokens only (no hex, no literal px radius), pill buttons, `:focus-visible` ring, no browser `confirm()`.
- Project workflow rules: ember_web steps are proposed to the user and approved before they are made (see each ember_web task's first step). Do not spawn browser-verification agents; the user tests the UI by hand. Never run git at `D:\User\Documents\Programming`; run git inside this repo (`Python/MCPServer`). End commit messages with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Test commands: ember_api from `apps/ember_api`: `python -m pytest <path> -q`. ember_web from `apps/ember_web`: `npx vitest run <path>`; full type check and build: `npm run build`.

## File Structure

ember_api (`apps/ember_api`):
- Create `src/models/account_capability.py`: the ORM row.
- Create `migrations/versions/0007_account_capabilities.py`.
- Create `src/services/account_capability_service.py`: `AccountCapabilityService`, `forget_extension`, `tools_to_disable`.
- Create `src/routes/account_capabilities.py`: the two routes.
- Create `tests/test_account_capabilities.py`.
- Modify `src/models/__init__.py`, `src/app.py`, `src/routes/server_info.py` (extension removal cleanup), `src/routes/chats.py` (`MAX_DISABLED_TOOLS`), `tests/test_migrations.py`, `README.md`.

ember_web (`apps/ember_web`):
- Create `src/api/AccountCapabilitiesClient.ts`, `src/stores/accountCapabilities.ts` (+ test).
- Create `src/composables/useEveryoneSwitch.ts`: the admin "turn on/off for everyone" confirm flow, shared by two views.
- Create `src/utils/capabilityIcons.ts`, `src/components/SupermarketItem.vue` (+ test), `src/views/SupermarketView.vue` (+ test).
- Modify `src/utils/capabilityGroups.ts` (+ test), `src/services/slashCommands.ts` (+ test), `src/stores/chat.ts`, `src/stores/chat.capabilities.test.ts`, `src/components/CapabilitySection.vue`, `src/views/CapabilitiesView.vue` (+ test), `src/router/index.ts` (+ test), `e2e/fakeApi.ts`, `e2e/capabilities.spec.ts`, `README.md`.

---

### Task 0: Amend the spec

**Files:**
- Modify: `docs/superpowers/specs/2026-10-08-capabilities-supermarket-design.md`

- [ ] **Step 1: Replace the route list in the "Routes" section**

In the "### Routes" section, replace the first two bullets with:

```markdown
- `GET /api/account-capabilities` returns `{"capabilities": [...], "extensions": [...], "disabled_tools": [...]}`. `disabled_tools` is the sorted list of tool names of every mcp_server capability the account has not added, worked out by ember_api from mcp_server's `/capabilities`. If mcp_server is unreachable the call answers 502 and nothing is guessed.
- `PUT /api/account-capabilities/{kind}/{key}` with body `{"enabled": bool}` returns the same shape. `kind` outside `capability` or `extension` is 422. The capability list is read first, so a 502 leaves the stored set unchanged. This is one call per item, not "replace the whole set", so two devices changing different items never overwrite each other.
```

- [ ] **Step 2: Fix the ember_web store and chat text**

In "### Stores", change the state line to `state: capabilities: string[], extensions: string[], disabled_tools: string[], ready: boolean, error: string`. Replace the second `chat.ts` bullet ("`disabledCapabilities` is replaced...") with: "The tools handed to `disabled_tools` come straight from the account store (`disabled_tools` in the server's reply). The browser no longer reads `/api/capabilities` for this, so accounts with only `chat.use` are covered." In the "Out of scope" line, delete "and moving the check of 'which tools the agent may use' from the browser to `ember_api`".

- [ ] **Step 3: Note the larger tool cap**

In the ember_api "Routes" section add a bullet: "`MAX_DISABLED_TOOLS` in `routes/chats.py` rises from 500 to 2000, because with nothing added a question carries every capability's tools."

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-10-08-capabilities-supermarket-design.md docs/superpowers/plans/2026-10-08-capabilities-supermarket.md
git commit -m "docs: supermarket spec returns disabled_tools from ember_api; add the plan" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 1: Model and migration

**Files:**
- Create: `apps/ember_api/src/models/account_capability.py`
- Create: `apps/ember_api/migrations/versions/0007_account_capabilities.py`
- Modify: `apps/ember_api/src/models/__init__.py`
- Test: `apps/ember_api/tests/test_migrations.py`

**Interfaces:**
- Produces: ORM class `AccountCapability(account_id: int, kind: str, item_id: str, created_at: datetime)` exported from `src.models`.

- [ ] **Step 1: Update the migration tests so they expect revision 0007**

In `apps/ember_api/tests/test_migrations.py` make these edits:
- `HEAD = "0006"` becomes `HEAD = "0007"`; `NEXT = "0007"` becomes `NEXT = "0008"`.
- Both occurrences of `conn.execute("DROP TABLE nav_preferences")  # likewise` (replace all) become:

```python
            conn.execute("DROP TABLE nav_preferences")  # likewise
            conn.execute("DROP TABLE account_capabilities")  # likewise
```

- In the `ignore_patterns("__pycache__", "0002*", "0003*", "0004*", "0005*", "0006*")` call add `"0007*"`.
- In the `scripts_with_a_new_migration` fixture change `"0007_add_nickname.py"` to `"0008_add_nickname.py"`, `'revision = "0007"\n'` to `'revision = "0008"\n'`, and `'down_revision = "0006"\n'` to `'down_revision = "0007"\n'`.

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `apps/ember_api`): `python -m pytest tests/test_migrations.py -q`
Expected: FAIL (the database is at `0006`, `DROP TABLE account_capabilities` has no table).

- [ ] **Step 3: Write the model**

Create `apps/ember_api/src/models/account_capability.py`:

```python
from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base, utcnow


class AccountCapability(Base):
    """One built-in capability or server-listed extension an account has added.
    A row means enabled; no row means disabled. Deleted with the account.

    `kind` is "capability" or "extension"; `item_id` is the capability name or
    extension id as mcp_server reports it. ember_api does not check it against
    mcp_server, so ids of things that no longer exist are kept and ignored."""

    __tablename__ = "account_capabilities"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
```

In `apps/ember_api/src/models/__init__.py` add `from src.models.account_capability import AccountCapability` directly after the `Account` import, and `"AccountCapability",` directly after `"Account",` in `__all__`.

- [ ] **Step 4: Write the migration**

Create `apps/ember_api/migrations/versions/0007_account_capabilities.py`:

```python
"""Per-account added capabilities and extensions (account_capabilities).

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_capabilities",
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("kind", sa.String(16), primary_key=True),
        sa.Column("item_id", sa.String(64), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("account_capabilities")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_migrations.py -q`
Expected: PASS (including `test_the_migrations_match_the_models_exactly`).

- [ ] **Step 6: Commit**

```bash
git add apps/ember_api/src/models apps/ember_api/migrations apps/ember_api/tests/test_migrations.py
git commit -m "feat(ember_api): account_capabilities table (migration 0007)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Service and routes

**Files:**
- Create: `apps/ember_api/src/services/account_capability_service.py`
- Create: `apps/ember_api/src/routes/account_capabilities.py`
- Create: `apps/ember_api/tests/test_account_capabilities.py`
- Modify: `apps/ember_api/src/app.py` (import list near line 24; `include_router` near line 169)
- Modify: `apps/ember_api/src/routes/chats.py:66` (`MAX_DISABLED_TOOLS = 500`)

**Interfaces:**
- Consumes: `AccountCapability` from Task 1; `_call`, `get_server_info` from `src.routes.server_info`; `McpServerInfo.capabilities(account) -> list[dict]` (each dict has `name`, `tools`); `current_account`, `get_db_session`, `get_log_writer` from `src.deps`.
- Produces: `AccountCapabilityService(session, account_id)` with `get() -> AccountCapabilities` and `set_enabled(kind, item_id, enabled) -> AccountCapabilities` (raises `TooManyItems`); `forget_extension(session, extension_id) -> None`; `tools_to_disable(capabilities: list[dict], enabled: list[str]) -> list[str]`; `MAX_ITEMS = 200`. HTTP shape `{"capabilities": [str], "extensions": [str], "disabled_tools": [str]}`.

- [ ] **Step 1: Write the failing tests**

Create `apps/ember_api/tests/test_account_capabilities.py`:

```python
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.conftest import FakeEmailSender, FakeUpstream
from tests.test_admin import login, make_member
from tests.test_registration import as_admin

URL = "/api/account-capabilities"
CAPABILITIES = [
    {"name": "pdf", "enabled": True, "label": "PDF files", "tools": ["tool_pdf_split", "tool_pdf_merge"], "resources": [], "has_gui": False},
    {"name": "calc", "enabled": True, "label": "Calculator", "tools": ["tool_calc"], "resources": [], "has_gui": False},
]
ALL_TOOLS = ["tool_calc", "tool_pdf_merge", "tool_pdf_split"]


def mcp_server(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/capabilities":
        return httpx.Response(200, json=CAPABILITIES)
    return httpx.Response(404, json={"error": "nope"})


@pytest.fixture(autouse=True)
def serve_capabilities(upstream: FakeUpstream) -> None:
    upstream.handler = mcp_server


def put(client: TestClient, kind: str, key: str, enabled: bool = True):
    return client.put(f"{URL}/{kind}/{key}", json={"enabled": enabled})


def test_needs_login(client: TestClient) -> None:
    assert client.get(URL).status_code == 401
    assert put(client, "capability", "pdf").status_code == 401


def test_a_new_account_has_nothing_added_so_every_tool_is_disabled(client: TestClient) -> None:
    as_admin(client)

    assert client.get(URL).json() == {"capabilities": [], "extensions": [], "disabled_tools": ALL_TOOLS}


def test_adding_a_capability_frees_its_tools(client: TestClient) -> None:
    as_admin(client)

    added = put(client, "capability", "pdf")

    assert added.status_code == 200
    expected = {"capabilities": ["pdf"], "extensions": [], "disabled_tools": ["tool_calc"]}
    assert added.json() == expected
    assert client.get(URL).json() == expected


def test_adding_an_extension_leaves_the_tools_alone(client: TestClient) -> None:
    as_admin(client)

    result = put(client, "extension", "notes").json()

    assert result == {"capabilities": [], "extensions": ["notes"], "disabled_tools": ALL_TOOLS}


def test_the_same_change_twice_is_a_no_op(client: TestClient) -> None:
    as_admin(client)

    first = put(client, "capability", "pdf").json()
    second = put(client, "capability", "pdf").json()

    assert first == second
    assert put(client, "capability", "calc", enabled=False).json() == first  # was never added


def test_disabling_takes_it_away_again(client: TestClient) -> None:
    as_admin(client)
    put(client, "capability", "pdf")
    put(client, "capability", "calc")

    result = put(client, "capability", "pdf", enabled=False).json()

    assert result == {"capabilities": ["calc"], "extensions": [], "disabled_tools": ["tool_pdf_merge", "tool_pdf_split"]}


def test_lists_are_sorted(client: TestClient) -> None:
    as_admin(client)
    put(client, "extension", "zeta")
    put(client, "extension", "alpha")

    assert client.get(URL).json()["extensions"] == ["alpha", "zeta"]


def test_a_capability_and_an_extension_can_share_an_id(client: TestClient) -> None:
    as_admin(client)
    put(client, "capability", "notes")
    put(client, "extension", "notes")

    body = client.get(URL).json()

    assert (body["capabilities"], body["extensions"]) == (["notes"], ["notes"])


def test_bad_input_is_refused(client: TestClient) -> None:
    as_admin(client)

    assert put(client, "widget", "pdf").status_code == 422
    assert put(client, "capability", "x" * 65).status_code == 422
    assert put(client, "capability", "bad key").status_code == 422
    assert client.put(f"{URL}/capability/pdf", json={}).status_code == 422
    assert client.put(f"{URL}/capability/pdf", json={"enabled": "yes please"}).status_code == 422


def test_private_per_account(client_factory, email: FakeEmailSender) -> None:
    alice = client_factory()
    make_member(alice, email)
    make_member(alice, email, "bob")
    login(alice, "alice")
    put(alice, "capability", "pdf")

    bob = client_factory()
    login(bob, "bob")

    assert bob.get(URL).json()["capabilities"] == []
    put(bob, "capability", "calc")
    put(bob, "capability", "calc", enabled=False)
    assert alice.get(URL).json()["capabilities"] == ["pdf"]


def test_at_most_max_items_per_account(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.services.account_capability_service.MAX_ITEMS", 2)
    as_admin(client)
    assert put(client, "extension", "a").status_code == 200
    assert put(client, "extension", "b").status_code == 200

    over = put(client, "extension", "c")

    assert over.status_code == 409
    assert put(client, "extension", "a").status_code == 200  # already added: not a new row
    assert put(client, "extension", "b", enabled=False).status_code == 200  # taking one away still works
    assert put(client, "extension", "c").status_code == 200


def test_mcp_server_down_means_no_answer_and_no_change(client: TestClient, upstream: FakeUpstream) -> None:
    as_admin(client)
    upstream.unreachable = True

    assert client.get(URL).status_code == 502
    assert put(client, "capability", "pdf").status_code == 502

    upstream.unreachable = False
    assert client.get(URL).json()["capabilities"] == []


def test_each_change_is_logged(client: TestClient) -> None:
    as_admin(client)
    put(client, "capability", "pdf")
    put(client, "extension", "notes")
    put(client, "capability", "pdf", enabled=False)
    me = client.get("/api/auth/me").json()["id"]

    logged = [e["message"] for e in client.get("/api/logs/action", params={"actor": me}).json()]

    assert logged[:3] == [
        "Disabled capability 'pdf'",
        "Added extension 'notes'",
        "Added capability 'pdf'",
    ]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_account_capabilities.py -q`
Expected: FAIL (404 on every route; module not found for the monkeypatch).

- [ ] **Step 3: Write the service**

Create `apps/ember_api/src/services/account_capability_service.py`:

```python
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
```

- [ ] **Step 4: Write the routes**

Create `apps/ember_api/src/routes/account_capabilities.py`:

```python
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
```

- [ ] **Step 5: Register the router and raise the tool cap**

In `apps/ember_api/src/app.py` add `account_capabilities,` to the `from src.routes import (...)` list (alphabetically, before `account,`... keep the list's order: put it directly after `account,`) and add `app.include_router(account_capabilities.router)` right after `app.include_router(nav_preferences.router)`.

In `apps/ember_api/src/routes/chats.py` change `MAX_DISABLED_TOOLS = 500` to `MAX_DISABLED_TOOLS = 2000`.

- [ ] **Step 6: Run the new tests and the related old ones**

Run: `python -m pytest tests/test_account_capabilities.py tests/test_disabled_tools.py tests/test_migrations.py -q`
Expected: PASS. If `test_disabled_tools.py` asserts the old limit of 500, change its numbers to 2000 and 2001.

- [ ] **Step 7: Commit**

```bash
git add apps/ember_api/src apps/ember_api/tests/test_account_capabilities.py apps/ember_api/tests/test_disabled_tools.py
git commit -m "feat(ember_api): /api/account-capabilities with the tools to disable" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Clean up on extension removal, and document the API

**Files:**
- Modify: `apps/ember_api/src/routes/server_info.py:321-330` (`remove_extension`)
- Modify: `apps/ember_api/tests/test_account_capabilities.py`
- Modify: `apps/ember_api/README.md` (after the `/api/nav-preferences` rows, near line 172)

**Interfaces:**
- Consumes: `forget_extension(session, extension_id)` from Task 2; `get_db_session` from `src.deps`.

- [ ] **Step 1: Write the failing test**

Append to `apps/ember_api/tests/test_account_capabilities.py`:

```python
def test_removing_an_extension_clears_it_for_every_account(
    client_factory, email: FakeEmailSender, upstream: FakeUpstream
) -> None:
    def server(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE" and request.url.path == "/extensions/notes":
            return httpx.Response(204)
        return mcp_server(request)

    upstream.handler = server
    alice = client_factory()
    make_member(alice, email)
    login(alice, "alice")
    put(alice, "extension", "notes")
    put(alice, "extension", "wiki")

    admin = as_admin(client_factory())
    put(admin, "extension", "notes")
    assert admin.delete("/api/extensions/notes").status_code == 204

    assert alice.get(URL).json()["extensions"] == ["wiki"]
    assert admin.get(URL).json()["extensions"] == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_account_capabilities.py::test_removing_an_extension_clears_it_for_every_account -q`
Expected: FAIL (alice still has `["notes", "wiki"]`).

- [ ] **Step 3: Implement the cleanup**

In `apps/ember_api/src/routes/server_info.py` add imports `from sqlalchemy.ext.asyncio import AsyncSession`, `from src.deps import get_db_session` (extend the existing `from src.deps import ...` line) and `from src.services.account_capability_service import forget_extension`. Replace `remove_extension` with:

```python
@router.delete("/extensions/{extension_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_extension(
    extension_id: str = Path(pattern=EXTENSION_ID_PATTERN),
    account: Account = Depends(require_admin),
    info: McpServerInfo = Depends(get_server_info),
    logs: LogWriter = Depends(get_log_writer),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    await _call(info.remove_extension(account, extension_id))
    # No account keeps an extension that no longer exists.
    await forget_extension(session, extension_id)
    await logs.action(account, "mcp.extension_remove", f"Removed extension '{extension_id}'")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 4: Document the routes**

In `apps/ember_api/README.md`, directly after the `DELETE /api/nav-preferences` table row, add:

```markdown
| `GET` | `/api/account-capabilities` | any logged-in account | Which built-in capabilities and server-listed extensions this account has added: `{capabilities, extensions, disabled_tools}`. A new account has nothing added. `disabled_tools` is the sorted tool names of every mcp_server capability not added, read from mcp_server's `/capabilities` (`502` if it is unreachable). |
| `PUT` | `/api/account-capabilities/{kind}/{key}` | any logged-in account | `{enabled: bool}` adds or removes one item (`kind`: `capability` or `extension`; `key` 1-64 characters of `A-Za-z0-9_.-`, else `422`). Same reply as `GET`. Repeating a change is a no-op; at most 200 items per account (`409`). Logged as `account.capability_enable` / `_disable` (or `extension`). Removing an extension through `DELETE /api/extensions/{id}` clears it from every account. |
```

- [ ] **Step 5: Run the ember_api suite**

Run: `python -m pytest -q`
Expected: PASS (whole suite).

- [ ] **Step 6: Commit**

```bash
git add apps/ember_api
git commit -m "feat(ember_api): removing an extension clears it from every account; document the routes" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: ember_web client and account store

**Checkpoint:** before editing, tell the user in two sentences what this task changes (a new API client and a new Pinia store, no UI change) and wait for a yes.

**Files:**
- Create: `apps/ember_web/src/api/AccountCapabilitiesClient.ts`
- Create: `apps/ember_web/src/stores/accountCapabilities.ts`
- Test: `apps/ember_web/src/stores/accountCapabilities.test.ts`

**Interfaces:**
- Produces: `accountCapabilitiesClient.get(): Promise<AccountCapabilities>` and `.set(kind, key, enabled)`; type `AccountCapabilities = { capabilities: string[]; extensions: string[]; disabled_tools: string[] }`; type `AccountItemKind = "capability" | "extension"`.
- Produces: `useAccountCapabilitiesStore()` returning refs `capabilities`, `extensions`, `disabledTools` (all `string[]`), `ready: boolean`, `error: string`, and functions `setCapability(name: string, on: boolean): Promise<void>`, `setExtension(id: string, on: boolean): Promise<void>`, `refresh(): Promise<void>`, `settled(): Promise<void>`.

- [ ] **Step 1: Write the client**

Create `apps/ember_web/src/api/AccountCapabilitiesClient.ts`:

```ts
import { apiRequest } from "./http";

export type AccountItemKind = "capability" | "extension";

/** What the account has added, kept in ember_api. `disabled_tools` is the tool
 * names of every capability it has not added, sent with each question. */
export interface AccountCapabilities {
  capabilities: string[];
  extensions: string[];
  disabled_tools: string[];
}

/** ember_api's /api/account-capabilities routes (any logged-in account). */
export const accountCapabilitiesClient = {
  get: () => apiRequest<AccountCapabilities>("GET", "/api/account-capabilities"),
  /** Adds or removes one item; resolves to the whole set as stored. */
  set: (kind: AccountItemKind, key: string, enabled: boolean) =>
    apiRequest<AccountCapabilities>("PUT", `/api/account-capabilities/${kind}/${encodeURIComponent(key)}`, { enabled }),
};
```

- [ ] **Step 2: Write the failing store tests**

Create `apps/ember_web/src/stores/accountCapabilities.test.ts`:

```ts
import { flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { accountCapabilitiesClient, type AccountCapabilities } from "../api/AccountCapabilitiesClient";
import type { Account } from "../api/AuthClient";
import { useAccountCapabilitiesStore } from "./accountCapabilities";
import { useAuthStore } from "./auth";

vi.mock("../api/AccountCapabilitiesClient", () => ({
  accountCapabilitiesClient: { get: vi.fn(), set: vi.fn() },
}));

const client = vi.mocked(accountCapabilitiesClient);
const ACCOUNT: Account = { id: 1, username: "lex", email: "l@e.com", email_verified: true, roles: [], permissions: [] };
const STORED: AccountCapabilities = { capabilities: ["pdf"], extensions: [], disabled_tools: ["tool_calc"] };

function setup(account: Account | null = ACCOUNT) {
  setActivePinia(createPinia());
  const auth = useAuthStore();
  auth.account = account;
  return { auth, store: useAccountCapabilitiesStore() };
}

beforeEach(() => {
  vi.resetAllMocks();
  client.get.mockResolvedValue(STORED);
  client.set.mockImplementation(async (kind, key, enabled) => ({
    capabilities: kind === "capability" ? (enabled ? ["calc", "pdf"] : []) : [],
    extensions: kind === "extension" && enabled ? [key] : [],
    disabled_tools: enabled ? [] : ["tool_calc", "tool_pdf"],
  }));
});

describe("accountCapabilities store", () => {
  it("loads what the account added at login", async () => {
    const { store } = setup();
    expect(store.ready).toBe(false);

    await flushPromises();

    expect(store.capabilities).toEqual(["pdf"]);
    expect(store.disabledTools).toEqual(["tool_calc"]);
    expect(store.ready).toBe(true);
  });

  it("asks for nothing while logged out", async () => {
    const { store } = setup(null);
    await flushPromises();

    expect(client.get).not.toHaveBeenCalled();
    expect(store.ready).toBe(false);
  });

  it("is not ready, and says why, when the load fails", async () => {
    client.get.mockRejectedValue(new Error("mcp_server is unreachable"));
    const { store } = setup();

    await flushPromises();

    expect(store.ready).toBe(false);
    expect(store.error).toBe("mcp_server is unreachable");
    expect(store.capabilities).toEqual([]);
  });

  it("shows a change at once, saves it, and takes the server's answer", async () => {
    const { store } = setup();
    await flushPromises();

    const saving = store.setCapability("calc", true);

    expect(store.capabilities).toEqual(["calc", "pdf"]);
    await saving;
    expect(client.set).toHaveBeenCalledWith("capability", "calc", true);
    expect(store.disabledTools).toEqual([]);
    expect(store.error).toBe("");
  });

  it("changes extensions the same way", async () => {
    const { store } = setup();
    await flushPromises();

    await store.setExtension("notes", true);

    expect(client.set).toHaveBeenCalledWith("extension", "notes", true);
    expect(store.extensions).toEqual(["notes"]);
  });

  it("puts the server's copy back, and says why, when a save fails", async () => {
    const { store } = setup();
    await flushPromises();
    client.set.mockRejectedValue(new Error("Too many items added to this account"));

    await store.setCapability("calc", true);

    expect(store.capabilities).toEqual(["pdf"]);
    expect(store.error).toBe("Too many items added to this account");
    expect(client.get).toHaveBeenCalledTimes(2);
    expect(store.ready).toBe(true);
  });

  it("saves changes one at a time, in order, and the last answer wins", async () => {
    const { store } = setup();
    await flushPromises();
    const order: string[] = [];
    client.set.mockImplementation(async (_kind, key, enabled) => {
      order.push(`${key}:${enabled}`);
      return { capabilities: [key], extensions: [], disabled_tools: [] };
    });

    void store.setCapability("a", true);
    await store.setCapability("b", true);

    expect(order).toEqual(["a:true", "b:true"]);
    expect(store.capabilities).toEqual(["b"]);
  });

  it("settled() waits for a save that is still going", async () => {
    const { store } = setup();
    await flushPromises();
    let finish!: (value: AccountCapabilities) => void;
    client.set.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    void store.setCapability("calc", true);
    let done = false;
    void store.settled().then(() => (done = true));

    await flushPromises();
    expect(done).toBe(false);

    finish({ capabilities: ["calc", "pdf"], extensions: [], disabled_tools: [] });
    await flushPromises();
    expect(done).toBe(true);
    expect(store.disabledTools).toEqual([]);
  });

  it("refresh() reads the server again", async () => {
    const { store } = setup();
    await flushPromises();
    client.get.mockResolvedValue({ capabilities: [], extensions: ["wiki"], disabled_tools: [] });

    await store.refresh();

    expect(store.extensions).toEqual(["wiki"]);
  });

  it("forgets everything when the account changes, and ignores a late answer for the old one", async () => {
    let finish!: (value: AccountCapabilities) => void;
    client.get.mockReturnValueOnce(new Promise((resolve) => (finish = resolve)));
    const { auth, store } = setup();

    auth.account = { ...ACCOUNT, id: 2 };
    await flushPromises();
    finish({ capabilities: ["old"], extensions: [], disabled_tools: [] });
    await flushPromises();

    expect(store.capabilities).toEqual(["pdf"]);
  });
});
```

- [ ] **Step 3: Run the tests to verify they fail**

Run (from `apps/ember_web`): `npx vitest run src/stores/accountCapabilities.test.ts`
Expected: FAIL (cannot resolve `./accountCapabilities`).

- [ ] **Step 4: Write the store**

Create `apps/ember_web/src/stores/accountCapabilities.ts`:

```ts
import { defineStore } from "pinia";
import { ref, watch } from "vue";
import {
  accountCapabilitiesClient,
  type AccountCapabilities,
  type AccountItemKind,
} from "../api/AccountCapabilitiesClient";
import { errorMessage } from "../utils/errors";
import { useAuthStore } from "./auth";

function toggled(list: readonly string[], key: string, on: boolean): string[] {
  const next = new Set(list);
  if (on) next.add(key);
  else next.delete(key);
  return [...next].sort();
}

/** The built-in capabilities and server-listed extensions this account has
 * added, kept in ember_api. Loaded at login and dropped when the account
 * changes. `ready` is true only while what is shown is what ember_api last
 * said: nothing is assumed on a failed load, and chat waits for it before
 * sending. A change shows at once and is saved in the background, one save at
 * a time and in order; if a save fails, the server's copy is loaded back and
 * `error` says why. `settled()` resolves when every started load or save has
 * finished. */
export const useAccountCapabilitiesStore = defineStore("accountCapabilities", () => {
  const auth = useAuthStore();

  const capabilities = ref<string[]>([]);
  const extensions = ref<string[]>([]);
  // Tool names of every capability not added: sent with each question.
  const disabledTools = ref<string[]>([]);
  const ready = ref(false);
  const error = ref("");
  // Bumped on every account change: answers for the previous account are ignored.
  let generation = 0;
  // The newest change; only its save's answer may replace the lists.
  let latest = 0;
  let chain: Promise<void> = Promise.resolve();

  function apply(state: AccountCapabilities): void {
    capabilities.value = state.capabilities;
    extensions.value = state.extensions;
    disabledTools.value = state.disabled_tools;
  }

  async function load(): Promise<void> {
    const started = generation;
    try {
      const loaded = await accountCapabilitiesClient.get();
      if (started !== generation) return;
      apply(loaded);
      ready.value = true;
      error.value = "";
    } catch (err) {
      if (started !== generation) return;
      ready.value = false;
      error.value = errorMessage(err);
    }
  }

  watch(
    () => auth.account?.id ?? null,
    (id) => {
      generation += 1;
      capabilities.value = [];
      extensions.value = [];
      disabledTools.value = [];
      ready.value = false;
      error.value = "";
      chain = id !== null ? load() : Promise.resolve();
    },
    { immediate: true },
  );

  function change(kind: AccountItemKind, key: string, on: boolean): Promise<void> {
    const started = generation;
    const mine = ++latest;
    const list = kind === "capability" ? capabilities : extensions;
    list.value = toggled(list.value, key, on);
    error.value = "";
    chain = chain.then(async () => {
      try {
        const saved = await accountCapabilitiesClient.set(kind, key, on);
        if (started === generation && mine === latest) {
          apply(saved);
          ready.value = true;
        }
      } catch (err) {
        if (started !== generation) return;
        const message = errorMessage(err);
        await load();
        error.value = message;
      }
    });
    return chain;
  }

  /** Adds (true) or removes (false) built-in capability `name`. */
  function setCapability(name: string, on: boolean): Promise<void> {
    return change("capability", name, on);
  }

  /** Adds (true) or removes (false) server-listed extension `id`. */
  function setExtension(id: string, on: boolean): Promise<void> {
    return change("extension", id, on);
  }

  /** Reads the server's copy again (after an extension was removed). */
  function refresh(): Promise<void> {
    chain = chain.then(load);
    return chain;
  }

  function settled(): Promise<void> {
    return chain;
  }

  return { capabilities, extensions, disabledTools, ready, error, setCapability, setExtension, refresh, settled };
});
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `npx vitest run src/stores/accountCapabilities.test.ts`
Expected: PASS (10 tests).

- [ ] **Step 6: Commit**

```bash
git add apps/ember_web/src/api/AccountCapabilitiesClient.ts apps/ember_web/src/stores/accountCapabilities.ts apps/ember_web/src/stores/accountCapabilities.test.ts
git commit -m "feat(ember_web): accountCapabilities store and client" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Chat store and slash commands use the account store

**Checkpoint:** before editing, tell the user in two sentences that the chat store stops reading `localStorage` for capability switches and reads the account store, and that questions wait for it to load. Wait for a yes.

**Files:**
- Modify: `apps/ember_web/src/services/slashCommands.ts:180-225`
- Modify: `apps/ember_web/src/services/slashCommands.test.ts:75-96`
- Modify: `apps/ember_web/src/stores/chat.ts` (lines 4, 94-113, 190-202, 416-418, 593, 612, 649-657, 690, 970-1010, 1183-1186)
- Modify (full rewrite): `apps/ember_web/src/stores/chat.capabilities.test.ts`

**Interfaces:**
- Consumes: `useAccountCapabilitiesStore()` from Task 4 (`capabilities`, `extensions`, `disabledTools`, `ready`, `error`, `settled()`).
- Produces: chat store exports `enabledExtensions` (computed `string[]`) and `enabledCapabilities` (computed `string[]`); `setExtensionEnabled`, `setCapabilityEnabled` and `disabledCapabilities` are removed. `SlashCommandRunner.list(enabledExtensions = [], enabledCapabilities: readonly string[] | null = null)` and `.run(text, enabledExtensions = [], enabledCapabilities: readonly string[] | null = null)`; `null` means "do not filter".

- [ ] **Step 1: Update the slash command tests**

In `apps/ember_web/src/services/slashCommands.test.ts` replace the whole `describe("capabilities the account switched off", ...)` block (lines 76-96) with:

```ts
describe("capabilities the account has not added", () => {
  it("leaves their commands out of the list", async () => {
    const runner = new SlashCommandRunner();

    expect((await runner.list([], null)).map((c) => c.capability)).toEqual(["files"]);
    expect((await runner.list([], ["files"])).map((c) => c.capability)).toEqual(["files"]);
    expect(await runner.list([], [])).toEqual([]);
    expect(await runner.list([], ["other"])).toEqual([]);
  });

  it("refuses to run one, and says where to add it", async () => {
    const out = await new SlashCommandRunner().run("/files export", [], []);

    expect(out).toBe('❌ "files" isn\'t added to your account. Add it in the Supermarket.');
    expect(runTool).not.toHaveBeenCalled();
  });

  it("still runs the ones that are added", async () => {
    runTool.mockResolvedValue({ text: "done", isError: false });

    expect(await new SlashCommandRunner().run("/files export", [], ["files"])).toBe("done");
  });
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npx vitest run src/services/slashCommands.test.ts`
Expected: FAIL (the old filter treats the list as disabled names).

- [ ] **Step 3: Change `SlashCommandRunner`**

In `apps/ember_web/src/services/slashCommands.ts` replace the doc comment and signature of `list` and its first two statements with:

```ts
  /** Built-in commands of the capabilities in `enabledCapabilities` (null: all
   * of them) plus the tools of `enabledExtensions`; extensions are left out
   * (not failed) when the tool list can't be read. */
  async list(
    enabledExtensions: readonly string[] = [],
    enabledCapabilities: readonly string[] | null = null,
  ): Promise<CommandInfo[]> {
    const all = await this.builtIns();
    const builtIns = enabledCapabilities ? all.filter((c) => enabledCapabilities.includes(c.capability)) : all;
```

Replace the head of `run` (signature through the `disabledCapabilities.includes(...)` check and the `list` call) with:

```ts
  async run(
    text: string,
    enabledExtensions: readonly string[] = [],
    enabledCapabilities: readonly string[] | null = null,
  ): Promise<string> {
    try {
      if (text.replace(/^\//, "").trim() === "help") return asMarkdown(await commandsClient.helpIndex());
      const parsed = parseCommand(text);
      const builtIn = (await this.builtIns()).some((c) => c.capability === parsed.capability);
      if (enabledCapabilities && builtIn && !enabledCapabilities.includes(parsed.capability)) {
        throw new CommandError(`"${parsed.capability}" isn't added to your account. Add it in the Supermarket.`);
      }
      const commands = await this.list(enabledExtensions, enabledCapabilities);
```

(Leave the rest of `run` unchanged.)

- [ ] **Step 4: Run the slash command tests**

Run: `npx vitest run src/services/slashCommands.test.ts`
Expected: PASS.

- [ ] **Step 5: Rewrite the chat capability tests**

Replace the whole content of `apps/ember_web/src/stores/chat.capabilities.test.ts` with:

```ts
import { flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { accountCapabilitiesClient, type AccountCapabilities } from "../api/AccountCapabilitiesClient";
import { chatsClient, type ChatSummary } from "../api/ChatsClient";
import { commandsClient } from "../api/CommandsClient";
import { settingsClient } from "../api/SettingsClient";
import { watchTurn } from "../services/turnStream";
import { useAccountCapabilitiesStore } from "./accountCapabilities";
import { useAuthStore } from "./auth";
import { useChatStore } from "./chat";

vi.mock("../api/AccountCapabilitiesClient", () => ({
  accountCapabilitiesClient: { get: vi.fn(), set: vi.fn() },
}));
vi.mock("../api/ChatsClient", () => ({
  chatsClient: {
    list: vi.fn(),
    get: vi.fn(),
    startTurn: vi.fn(),
    cancel: vi.fn(),
    decide: vi.fn(),
    search: vi.fn(),
    remove: vi.fn(),
  },
}));
vi.mock("../api/SettingsClient", () => ({ settingsClient: { get: vi.fn(), set: vi.fn() } }));
vi.mock("../api/CommandsClient", () => ({ commandsClient: { list: vi.fn() } }));
vi.mock("../services/turnStream", () => ({ watchTurn: vi.fn() }));

const client = vi.mocked(chatsClient);
const account = vi.mocked(accountCapabilitiesClient);
const commands = vi.mocked(commandsClient);

const ACCOUNT = { id: 1, username: "root", email: "root@example.com", email_verified: true, roles: [], permissions: ["chat.use", "tools.use"] };

const summary = (id: string): ChatSummary => ({
  id,
  title: `Chat ${id}`,
  agent_id: "a1",
  message_count: 0,
  created_at: "2026-01-01T00:00:00",
  updated_at: "2026-01-01T00:00:00",
  running: false,
});

const NOTHING: AccountCapabilities = {
  capabilities: [],
  extensions: [],
  disabled_tools: ["tool_calc", "tool_pdf_merge", "tool_pdf_split"],
};

async function store() {
  setActivePinia(createPinia());
  vi.mocked(settingsClient.get).mockResolvedValue({ force_tool_approval: false });
  useAuthStore().account = ACCOUNT;
  const chat = useChatStore();
  await flushPromises();
  return chat;
}

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  vi.mocked(watchTurn).mockResolvedValue("aborted");
  client.list.mockResolvedValue([]);
  client.search.mockResolvedValue([]);
  client.startTurn.mockResolvedValue({ chat: { ...summary("c1"), running: true }, sequence: 1 });
  commands.list.mockResolvedValue([]);
  account.get.mockResolvedValue(NOTHING);
});

describe("what the account has added decides what a question may use", () => {
  it("sends the tools of everything not added, as ember_api worked them out", async () => {
    const chat = await store();

    await chat.send("hi");

    expect(client.startTurn.mock.calls[0]![1]).toMatchObject({
      disabled_tools: ["tool_calc", "tool_pdf_merge", "tool_pdf_split"],
      enabled_extensions: [],
    });
  });

  it("sends no disabled tools when everything is added", async () => {
    account.get.mockResolvedValue({ capabilities: ["calc", "pdf"], extensions: [], disabled_tools: [] });
    const chat = await store();

    await chat.send("hi");

    expect(client.startTurn.mock.calls[0]![1]).not.toHaveProperty("disabled_tools");
  });

  it("sends the extensions the account added", async () => {
    account.get.mockResolvedValue({ capabilities: [], extensions: ["notes"], disabled_tools: [] });
    const chat = await store();

    await chat.send("hi");

    expect(client.startTurn.mock.calls[0]![1]).toMatchObject({ enabled_extensions: ["notes"] });
    expect(chat.enabledExtensions).toEqual(["notes"]);
  });

  it("uses the new answer after a change", async () => {
    const chat = await store();
    account.set.mockResolvedValue({ capabilities: ["pdf"], extensions: [], disabled_tools: ["tool_calc"] });

    await useAccountCapabilitiesStore().setCapability("pdf", true);
    await chat.send("hi");

    expect(chat.enabledCapabilities).toEqual(["pdf"]);
    expect(client.startTurn.mock.calls[0]![1]).toMatchObject({ disabled_tools: ["tool_calc"] });
  });

  it("waits for a change that is still being saved", async () => {
    const chat = await store();
    let finish!: (value: AccountCapabilities) => void;
    account.set.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    void useAccountCapabilitiesStore().setCapability("pdf", true);

    const sending = chat.send("hi");
    await flushPromises();
    expect(client.startTurn).not.toHaveBeenCalled();

    finish({ capabilities: ["pdf"], extensions: [], disabled_tools: ["tool_calc"] });
    await sending;
    expect(client.startTurn.mock.calls[0]![1]).toMatchObject({ disabled_tools: ["tool_calc"] });
  });

  it("does not send the question when the account's choices could not be read", async () => {
    account.get.mockRejectedValue(new Error("mcp_server is unreachable"));
    const chat = await store();

    const taken = await chat.send("hi");

    expect(taken).toBe(false);
    expect(client.startTurn).not.toHaveBeenCalled();
    expect(chat.sendError).toContain("mcp_server is unreachable");
    expect(chat.messages).toEqual([]);
  });
});
```

- [ ] **Step 6: Run it to verify it fails**

Run: `npx vitest run src/stores/chat.capabilities.test.ts`
Expected: FAIL (the chat store still reads `localStorage`).

- [ ] **Step 7: Change `chat.ts`**

Make these edits in `apps/ember_web/src/stores/chat.ts`:

1. Delete line 4 `import { commandsClient } from "../api/CommandsClient";` is NOT deleted blindly: `CommandInfo` is imported from the same module on a separate `import type` line (keep that one). Delete only the value import `import { commandsClient } from "../api/CommandsClient";`. Add `import { useAccountCapabilitiesStore } from "./accountCapabilities";` next to `import { useAuthStore } from "./auth";`.
2. Delete the helpers `extensionsKey`, `disabledCapabilitiesKey`, `readStringList` and `readExtensions` (lines 94-113). Check with `grep -n "readStringList\|readExtensions\|extensionsKey" src/stores/chat.ts` that nothing else uses them; if `readStringList` is used elsewhere, keep it.
3. Replace the block from `// mcp_server extensions whose tools the agent (and slash commands) may use.` through `let capabilityTools: Map<string, string[]> | null = null;` (lines 191-202) with:

```ts
  // What this account has added on the Capabilities page, kept in ember_api:
  // the extensions whose tools the agent (and slash commands) may use, and the
  // built-in capabilities it may use. Nothing is added to begin with.
  const accountCaps = useAccountCapabilitiesStore();
  const enabledExtensions = computed(() => accountCaps.extensions);
  const enabledCapabilities = computed(() => accountCaps.capabilities);
```

4. In the big `watch(...)` that resets on account change, delete the three lines `enabledExtensions.value = ...`, `disabledCapabilities.value = ...` and `capabilityTools = null;`.
5. In `loadCommands` change `commandRunner.list(enabledExtensions.value, disabledCapabilities.value)` to `commandRunner.list(enabledExtensions.value, enabledCapabilities.value)`. In `runCommand` change `commandRunner.run(text, enabledExtensions.value, disabledCapabilities.value)` to `commandRunner.run(text, enabledExtensions.value, enabledCapabilities.value)`.
6. Directly after the `loadCommands` function add:

```ts
  // The suggestions follow what the account has added.
  watch([enabledExtensions, enabledCapabilities], () => {
    void loadCommands();
  });
```

7. In `send()` replace the block from `// Which tools the account switched off: needed before anything is changed.` through the closing `}` of its `catch` with:

```ts
    // What the account added, as ember_api last saved it: needed before anything is changed.
    await accountCaps.settled();
    if (!accountCaps.ready) {
      sendError.value = `Couldn't check which capabilities you added, so nothing was sent: ${accountCaps.error || "not loaded yet"}`;
      return false;
    }
    const disabledTools = accountCaps.disabledTools;
```

8. Delete the functions `resolveDisabledTools`, `setCapabilityEnabled` and `setExtensionEnabled` (with their doc comments). Keep `refreshCommands`.
9. In the returned object replace `enabledExtensions, setExtensionEnabled, disabledCapabilities, setCapabilityEnabled,` with `enabledExtensions, enabledCapabilities,` (keep their position; keep the other entries).

- [ ] **Step 8: Run the store tests and a type check**

Run: `npx vitest run src/stores src/services/slashCommands.test.ts`
Expected: PASS. Then `npm run build` — expected: type errors only in `CapabilitiesView.vue` and its test (they still use removed members); those are fixed in Task 6. If errors appear anywhere else, fix them here.

- [ ] **Step 9: Commit**

```bash
git add apps/ember_web/src/services apps/ember_web/src/stores
git commit -m "feat(ember_web): chat and slash commands follow the account's added capabilities" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Capabilities page shows only what was added

**Checkpoint:** before editing, tell the user in three sentences what changes on the page (only added cards, the switch removes a card, a Supermarket button replaces Add extension and Remove) and wait for a yes.

**Files:**
- Create: `apps/ember_web/src/composables/useEveryoneSwitch.ts`
- Create: `apps/ember_web/src/utils/capabilityIcons.ts`
- Modify: `apps/ember_web/src/utils/capabilityGroups.ts` (+ add tests to `capabilityGroups.test.ts`)
- Modify: `apps/ember_web/src/components/CapabilitySection.vue:45-50`
- Modify (script + template): `apps/ember_web/src/views/CapabilitiesView.vue`
- Modify: `apps/ember_web/src/views/CapabilitiesView.test.ts`

**Interfaces:**
- Consumes: `useAccountCapabilitiesStore()` from Task 4.
- Produces: `addedOnly(capabilities, extensions, tools, addedCapabilities, addedExtensions): { capabilities: CapabilityInfo[]; extensions: ExtensionInfo[]; tools: ToolInfo[] }`; `CAPABILITY_ICONS: { builtin; extension; other }` (SVG path strings); `useEveryoneSwitch(onChanged)` returning refs `pending: CapabilityInfo | null`, `switching: string | null`, `error: string`, `copy: { title; message; label }` and functions `ask(c)`, `cancel()`, `confirm()`.

- [ ] **Step 1: Write failing tests for `addedOnly`**

Append to `apps/ember_web/src/utils/capabilityGroups.test.ts` (it already defines a `tool(name, title, ...)` helper at the top; the other fixtures are local):

```ts
describe("addedOnly", () => {
  const caps = [
    { name: "pdf", enabled: true, label: "PDF files", tools: ["tool_pdf_merge"], resources: [] },
    { name: "calc", enabled: true, label: "Calculator", tools: ["tool_calc"], resources: [] },
  ];
  const exts = [
    { id: "notes", label: "Notes", description: "", status: "connected", error: null, tools: ["notes__add"] },
    { id: "wiki", label: "Wiki", description: "", status: "connected", error: null, tools: [] },
  ];
  const all = [tool("tool_pdf_merge", "Merge"), tool("tool_calc", "Calc"), tool("notes__add", "Add"), tool("wiki__find", "Find"), tool("stray", "Stray")];

  it("keeps only the added capabilities and extensions", () => {
    const out = addedOnly(caps, exts, all, ["pdf"], ["notes"]);

    expect(out.capabilities.map((c) => c.name)).toEqual(["pdf"]);
    expect(out.extensions.map((e) => e.id)).toEqual(["notes"]);
  });

  it("drops the tools of what is not added so they do not show up as other tools", () => {
    const out = addedOnly(caps, exts, all, ["pdf"], ["notes"]);

    expect(out.tools.map((t) => t.name)).toEqual(["tool_pdf_merge", "notes__add", "stray"]);
  });

  it("drops an extension's tools found by its namespace too", () => {
    expect(addedOnly(caps, exts, all, [], []).tools.map((t) => t.name)).toEqual(["stray"]);
  });

  it("ignores added ids that no longer exist", () => {
    expect(addedOnly(caps, exts, all, ["gone"], ["gone"]).capabilities).toEqual([]);
  });
});
```

Add `addedOnly` to that file's import from `./capabilityGroups`.

- [ ] **Step 2: Run to verify failure, then implement `addedOnly`**

Run: `npx vitest run src/utils/capabilityGroups.test.ts` — Expected: FAIL (`addedOnly` is not exported).

Add to `apps/ember_web/src/utils/capabilityGroups.ts` after `inExtensionNamespace`/`ownedByExtension`:

```ts
export interface AddedOnly {
  capabilities: CapabilityInfo[];
  extensions: ExtensionInfo[];
  tools: ToolInfo[];
}

/** What the account has added: only those capabilities and extensions, and the
 * tools left once the ones of everything not added are removed, so they do not
 * turn up as "other tools". */
export function addedOnly(
  capabilities: CapabilityInfo[],
  extensions: ExtensionInfo[],
  tools: ToolInfo[],
  addedCapabilities: readonly string[],
  addedExtensions: readonly string[],
): AddedOnly {
  const capabilityIds = new Set(addedCapabilities);
  const extensionIds = new Set(addedExtensions);
  const hiddenTools = new Set(capabilities.filter((c) => !capabilityIds.has(c.name)).flatMap((c) => c.tools));
  const hiddenExtensions = extensions.filter((e) => !extensionIds.has(e.id));
  return {
    capabilities: capabilities.filter((c) => capabilityIds.has(c.name)),
    extensions: extensions.filter((e) => extensionIds.has(e.id)),
    tools: tools.filter((t) => !hiddenTools.has(t.name) && !hiddenExtensions.some((e) => ownedByExtension(e, t))),
  };
}
```

Run: `npx vitest run src/utils/capabilityGroups.test.ts` — Expected: PASS.

- [ ] **Step 3: Extract the icons**

Create `apps/ember_web/src/utils/capabilityIcons.ts`:

```ts
/** 16px grid, stroke only: a box (built-in capability), a plug (extension), a wrench (other tools). */
export const CAPABILITY_ICONS = {
  builtin: "M8 1.5l5.5 3v7L8 14.5l-5.5-3v-7zM2.5 4.5L8 7.5l5.5-3M8 7.5v7",
  extension: "M6 2v3M10 2v3M4.5 5h7v3a3.5 3.5 0 0 1-7 0zM8 11.5V14",
  other: "M10.5 2.5a3 3 0 0 0-3.2 4L2.5 11.3 4.7 13.5 9.5 8.7a3 3 0 0 0 4-3.2l-1.8 1.8-1.7-.5-.5-1.7z",
} as const;
```

In `apps/ember_web/src/components/CapabilitySection.vue` delete the local `ICONS` constant and its comment (lines 45-50), add `import { CAPABILITY_ICONS } from "../utils/capabilityIcons";` to the imports, and change `ICONS[icon]` in the template to `CAPABILITY_ICONS[icon]`.

- [ ] **Step 4: Write the shared "everyone" switch**

Create `apps/ember_web/src/composables/useEveryoneSwitch.ts`:

```ts
import { computed, ref } from "vue";
import { commandsClient, type CapabilityInfo } from "../api/CommandsClient";
import { errorMessage } from "../utils/errors";

/** The admin's "turn a built-in capability on or off for everyone" flow: ask
 * first (the caller shows a ConfirmModal while `pending` is set), then switch it
 * in mcp_server and hand the updated capability to `onChanged`. */
export function useEveryoneSwitch(onChanged: (updated: CapabilityInfo) => void | Promise<void>) {
  const pending = ref<CapabilityInfo | null>(null);
  const switching = ref<string | null>(null);
  const error = ref("");

  const copy = computed(() => {
    const capability = pending.value;
    if (!capability) return { title: "", message: "", label: "" };
    const verb = capability.enabled ? "Turn off" : "Turn on";
    return {
      title: `${verb} capability`,
      message: `${verb} "${capability.label ?? capability.name}" for every mcp_server client (chat_app, agents, ember)?`,
      label: verb,
    };
  });

  function ask(capability: CapabilityInfo): void {
    pending.value = capability;
  }

  function cancel(): void {
    pending.value = null;
  }

  async function confirm(): Promise<void> {
    const capability = pending.value;
    pending.value = null;
    if (!capability) return;
    error.value = "";
    switching.value = capability.name;
    try {
      await onChanged(await commandsClient.setCapability(capability.name, !capability.enabled));
    } catch (err) {
      error.value = errorMessage(err);
    } finally {
      switching.value = null;
    }
  }

  return { pending, switching, error, copy, ask, cancel, confirm };
}
```

- [ ] **Step 5: Update the view's tests first**

In `apps/ember_web/src/views/CapabilitiesView.test.ts`:

a) In the hoisted `mocks` add `accountGet: vi.fn(), accountSet: vi.fn(),` and after the other `vi.mock` calls add:

```ts
vi.mock("../api/AccountCapabilitiesClient", () => ({
  accountCapabilitiesClient: { get: mocks.accountGet, set: mocks.accountSet },
}));
```

b) Remove `import { useChatStore } from "../stores/chat";`. Add `import { useAccountCapabilitiesStore } from "../stores/accountCapabilities";`.

c) In `show()`'s options type add `added?: { capabilities?: string[]; extensions?: string[] }`. Before `const router = createRouter(...)` insert:

```ts
  const listedExtensions = (await Promise.resolve(mocks.extensions()).catch(() => [])) as { id: string }[];
  mocks.accountGet.mockResolvedValue({
    capabilities: options.added?.capabilities ?? CAPS.map((c) => c.name),
    extensions: options.added?.extensions ?? listedExtensions.map((e) => e.id),
    disabled_tools: [],
  });
```

d) In the router routes of `show()` add `{ path: "/capabilities/supermarket", component: { template: "<div />" } },` before the `/capabilities/:name` route.

e) In `beforeEach` add `mocks.accountSet.mockImplementation(async (_kind, _key, _on) => ({ capabilities: [], extensions: [], disabled_tools: [] }));`.

f) Replace these existing tests (by name) with the versions below. In `describe("CapabilitiesView")`, replace `it("shows other users a plain On/Off badge and no switch", ...)` with:

```ts
  it("gives every card a switch that is on, whatever the permissions", async () => {
    const w = await show();

    const boxes = w.findAll("input[type=checkbox]");
    expect(boxes).toHaveLength(3);
    expect(boxes.every((b) => (b.element as HTMLInputElement).checked)).toBe(true);
    expect(w.findAll(".badge")).toHaveLength(0);
  });

  it("lists only what the account added", async () => {
    const w = await show({ added: { capabilities: ["pdf"] } });

    expect(sectionNames(w)).toEqual(["PDF files"]);
  });

  it("keeps the tools of what is not added out of 'Other tools'", async () => {
    const w = await show({ added: { capabilities: ["pdf"] } });

    expect(sectionNames(w)).not.toContain("Other tools");
  });

  it("links to the Supermarket, and offers no Add extension button", async () => {
    const w = await show({ admin: true });

    expect(w.get("a.shop").attributes("href")).toBe("/capabilities/supermarket");
    expect(w.text()).not.toContain("Add extension");
  });

  it("says so, and points to the Supermarket, when nothing is added", async () => {
    const w = await show({ added: { capabilities: [], extensions: [] } });

    expect(sections(w)).toHaveLength(0);
    expect(w.text()).toContain("Nothing added yet");
    expect(w.findAll("a").some((a) => a.attributes("href") === "/capabilities/supermarket")).toBe(true);
  });
```

In `describe("CapabilitiesView extension cards")` replace the tests `"gives each extension a switch for your chats that applies at once"`, `"does not give an extension a switch without chat.use"` and `"lets only admins add and remove extensions"` with:

```ts
  it("turns an extension off for the account at once, and its card goes", async () => {
    mocks.extensions.mockResolvedValue([ext("pdf2")]);
    const w = await show({ permissions: WITH_CHAT, attach: true });
    const box = w.findAll("input[type=checkbox]").at(-1)!.element as HTMLInputElement;
    expect(box.checked).toBe(true);
    expect(w.findAll(".scope").map((s) => s.text())).toContain("Account");

    box.click();
    await flushPromises();

    expect(mocks.accountSet).toHaveBeenCalledWith("extension", "pdf2", false);
    expect(useAccountCapabilitiesStore().extensions).not.toContain("pdf2");
    expect(sectionNames(w)).not.toContain("PDF2");
    expect(w.findComponent(ConfirmModal).exists()).toBe(false);
    w.unmount();
  });

  it("has no Remove button on an extension card, even for admins (Remove lives in the Supermarket)", async () => {
    mocks.extensions.mockResolvedValue([ext("pdf2")]);
    const admin = await show({ permissions: [...WITH_CHAT, "admin.manage"] });
    await head(admin, "PDF2").trigger("click");

    expect(admin.find("button.danger").exists()).toBe(false);
  });
```

In `describe("the page layout")`: change the expectation `expect(w.get("details.how p").text()).toContain("remembered on this device");` to `toContain("follows your account");`, and the titles test's expected array to `["Built-in", "Extensions", "Other"]`.

Replace the whole `describe("built-in switches for your own chats", ...)` with:

```ts
describe("built-in switches for your own account", () => {
  const WITH_CHAT = ["tools.use", "chat.use"];
  const boxes = (w: Wrapper) => w.findAll("input[type=checkbox]");

  it("turns one off for the account at once, without asking, and the card goes", async () => {
    const w = await show({ permissions: WITH_CHAT, attach: true });

    // Native activation includes checkbox changes and canceled-click rollback.
    (boxes(w)[0]!.element as HTMLInputElement).click();
    await flushPromises();

    expect(mocks.accountSet).toHaveBeenCalledWith("capability", "pdf", false);
    expect(mocks.setCapability).not.toHaveBeenCalled();
    expect(w.findComponent(ConfirmModal).exists()).toBe(false);
    expect(sectionNames(w)).not.toContain("PDF files");
    w.unmount();
  });

  it("lets the switch of a capability that is off for everyone be turned off too", async () => {
    const w = await show({ permissions: WITH_CHAT });

    const legacy = boxes(w)[2]!.element as HTMLInputElement;
    expect(legacy.checked).toBe(true);
    expect(legacy.disabled).toBe(false);
    expect(head(w, "Legacy").text()).toContain("off");
  });

  it("leaves the everyone switch to admins, inside the card", async () => {
    const w = await show({ permissions: [...WITH_CHAT, "admin.manage"] });
    await head(w, "PDF files").trigger("click");

    expect(w.get("button.everyone").text()).toBe("Turn off for everyone");
  });
});
```

Also in the existing admin "everyone" tests nothing else changes (they use `show({ admin: true })`).

- [ ] **Step 6: Run the view tests to verify they fail**

Run: `npx vitest run src/views/CapabilitiesView.test.ts`
Expected: FAIL (the view still uses the old store members).

- [ ] **Step 7: Rewrite the view's `<script setup>`**

Replace the whole `<script setup lang="ts">...</script>` block of `apps/ember_web/src/views/CapabilitiesView.vue` with:

```vue
<script setup lang="ts">
import { computed, nextTick, onMounted, ref, useTemplateRef } from "vue";
import { RouterLink, useRoute } from "vue-router";
import { commandsClient, type CapabilityInfo } from "../api/CommandsClient";
import { extensionsClient, type ExtensionInfo } from "../api/ExtensionsClient";
import { McpServerClient } from "../api/McpServerClient";
import type { ResourceInfo, ToolInfo, ToolRunResult } from "../api/types";
import ConfirmModal from "../components/admin/ConfirmModal.vue";
import CapabilitySection, { type SectionPage } from "../components/CapabilitySection.vue";
import MarkdownContent from "../components/MarkdownContent.vue";
import SegmentedControl from "../components/SegmentedControl.vue";
import ToolCard from "../components/ToolCard.vue";
import ToolRunModal from "../components/ToolRunModal.vue";
import { useEveryoneSwitch } from "../composables/useEveryoneSwitch";
import { useAccountCapabilitiesStore } from "../stores/accountCapabilities";
import { useAuthStore } from "../stores/auth";
import { addedOnly, groupTools, inExtensionNamespace } from "../utils/capabilityGroups";
import { errorMessage } from "../utils/errors";
import { formatToolResult } from "../utils/toolResultFormat";
import { safeWebUrl } from "../utils/webUrl";

/** What the account has added from the Supermarket, as one list of identical
 * cards: built-in capabilities and extensions (other MCP servers). Each card
 * brings tools (run them in place) and resources to read, may have an Open
 * button, and has a switch: turning it off removes the card (the item goes back
 * to the Supermarket). Admins can also turn a built-in capability off for
 * everyone, from inside its card. Collapsed by default, opened while a filter is
 * typed. A tool is a row (label and name); a click opens its description and
 * run form in a modal. */

const auth = useAuthStore();
const account = useAccountCapabilitiesStore();
const server = new McpServerClient();

const capabilities = ref<CapabilityInfo[]>([]);
const tools = ref<ToolInfo[]>([]);
const resources = ref<ResourceInfo[]>([]);
const extensions = ref<ExtensionInfo[]>([]);
const loading = ref(true);
const loadError = ref("");
const actionError = ref("");
// Which kind of card is listed.
type Kind = "all" | "builtin" | "extensions";
const kind = ref<Kind>("all");

// ?q= prefills the filter (links to a single tool use it).
const initialQuery = useRoute().query.q;
const query = ref(typeof initialQuery === "string" ? initialQuery : "");
const filtering = computed(() => query.value.trim() !== "");

/** Which sections the user opened; while filtering, every shown one is open. */
const openSections = ref(new Set<string>());
const OTHER = "\0other";
function isOpen(key: string): boolean {
  return filtering.value || openSections.value.has(key);
}
function toggleSection(key: string): void {
  const next = new Set(openSections.value);
  if (!next.delete(key)) next.add(key);
  openSections.value = next;
}

// The tool whose modal is open; its last result stays until re-run or closed.
const openTool = ref<string | null>(null);
const running = ref(false);
const result = ref<ToolRunResult | null>(null);

// The resource being read and what came back.
const reading = ref<string | null>(null);
const readUri = ref("");
const readResult = ref<{ uri: string; text: string } | null>(null);
const readError = ref("");
const reader = useTemplateRef<HTMLElement>("reader");

const isAdmin = computed(() => auth.hasPermission("admin.manage"));
// Capabilities, tools and resources need tools.use; extensions need only chat.use.
const canTools = computed(() => auth.hasPermission("tools.use"));
const showBuiltin = computed(() => canTools.value && kind.value !== "extensions");
const showExtensions = computed(() => kind.value !== "builtin");
// Headings tell the groups apart; only when both can show.
const groupHeadings = computed(() => canTools.value && kind.value === "all");
const added = computed(() =>
  addedOnly(capabilities.value, extensions.value, tools.value, account.capabilities, account.extensions),
);
const grouped = computed(() => groupTools(added.value.capabilities, added.value.tools, query.value, added.value.extensions));
const selectedTool = computed(() => tools.value.find((t) => t.name === openTool.value) ?? null);
// The account's choices load beside the page's own data.
const accountLoading = computed(() => !account.ready && account.error === "");

/** Resources no capability claims (of every capability, added or not). */
const unclaimedResources = computed(() => {
  const claimed = new Set(capabilities.value.flatMap((c) => c.resources));
  return resources.value.filter((r) => !claimed.has(r.name) && !claimed.has(r.uri));
});
/** Those namespaced under an extension ("<id>__<name>") belong to it. */
const extensionResources = computed(() => {
  const owned = new Map<string, ResourceInfo[]>();
  for (const e of extensions.value) {
    owned.set(e.id, unclaimedResources.value.filter((r) => inExtensionNamespace(e.id, r.name)));
  }
  return owned;
});
const otherResources = computed(() => {
  const owned = new Set([...extensionResources.value.values()].flat());
  return unclaimedResources.value.filter((r) => !owned.has(r));
});
const showOther = computed(() => grouped.value.otherTools.length > 0 || (!filtering.value && otherResources.value.length > 0));

const extensionKey = (id: string): string => `\0ext:${id}`;
function resourcesOfExtension(extension: ExtensionInfo): ResourceInfo[] {
  return filtering.value ? [] : (extensionResources.value.get(extension.id) ?? []);
}

function resourcesOf(capability: CapabilityInfo): ResourceInfo[] {
  const names = new Set(capability.resources);
  return resources.value.filter((r) => names.has(r.name) || names.has(r.uri));
}

const nothingShown = computed(
  () =>
    (!showBuiltin.value || (grouped.value.groups.length === 0 && !showOther.value)) &&
    (!showExtensions.value || grouped.value.extensionGroups.length === 0),
);
// Nothing at all is added (not just filtered away): invite the user to the Supermarket.
const nothingAdded = computed(
  () => added.value.capabilities.length === 0 && added.value.extensions.length === 0 && added.value.tools.length === 0,
);

const countText = (tools: number, resources: number): string =>
  `${tools} tool${tools === 1 ? "" : "s"}${resources ? ` · ${resources} resource${resources === 1 ? "" : "s"}` : ""}`;

function capabilitySummary(capability: CapabilityInfo, tools: number): string {
  return capability.enabled ? countText(tools, resourcesOf(capability).length) : "off";
}

/** Where a capability's Open button leads: its own page, while it is on. */
function capabilityPage(capability: CapabilityInfo): SectionPage | null {
  return capability.has_gui && capability.enabled
    ? { to: `/capabilities/${encodeURIComponent(capability.name)}`, external: false }
    : null;
}

/** Where an extension's Open button leads: its own web UI when it names a
 * usable one (a new tab), else nowhere (its tools are listed in its card). */
function extensionPage(e: ExtensionInfo): SectionPage | null {
  const web = safeWebUrl(e.web_url);
  return web ? { to: web, external: true, label: "Open app" } : null;
}

function extensionSummary(g: { extension: ExtensionInfo; tools: ToolInfo[] }): string {
  if (g.extension.status !== "connected") return "Not connected";
  return countText(canTools.value ? g.tools.length : g.extension.tools.length, resourcesOfExtension(g.extension).length);
}

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    // Without tools.use only the extensions are listed.
    const [caps, toolList, res, exts] = await Promise.all([
      canTools.value ? commandsClient.capabilities() : [],
      canTools.value ? server.listTools() : [],
      canTools.value ? server.listResources().catch(() => [] as ResourceInfo[]) : [],
      // Without it the extension tools would sit under "Other tools".
      canTools.value ? extensionsClient.list().catch(() => [] as ExtensionInfo[]) : extensionsClient.list(),
    ]);
    capabilities.value = caps;
    tools.value = [...toolList].sort((a, b) => a.title.localeCompare(b.title));
    resources.value = res;
    extensions.value = exts;
  } catch (err) {
    loadError.value = errorMessage(err);
  } finally {
    loading.value = false;
  }
}

// Switching a capability for everyone reaches every mcp_server client, so it
// asks first, in the confirmation dialog (turning one off is the riskier way round).
const {
  pending: pendingSwitch,
  switching,
  error: switchError,
  copy: switchCopy,
  ask: askSwitch,
  cancel: cancelSwitch,
  confirm: confirmSwitch,
} = useEveryoneSwitch(async (updated) => {
  capabilities.value = capabilities.value.map((c) => (c.name === updated.name ? updated : c));
  // Switching changes which tools and resources the server offers.
  const [toolList, res] = await Promise.all([
    server.listTools().catch(() => tools.value),
    server.listResources().catch(() => resources.value),
  ]);
  tools.value = [...toolList].sort((a, b) => a.title.localeCompare(b.title));
  resources.value = res;
});

function openToolModal(name: string): void {
  openTool.value = name;
  result.value = null;
}

async function run(name: string, args: Record<string, unknown>): Promise<void> {
  running.value = true;
  result.value = null;
  try {
    const outcome = await server.runTool(name, args);
    // The modal was closed (or another tool opened) while it ran: drop the result.
    if (openTool.value === name) result.value = outcome;
  } catch (err) {
    // Transport/protocol failure - shown the same way as a tool-side error.
    if (openTool.value === name) result.value = { text: String(err), isError: true };
  } finally {
    running.value = false;
  }
}

function startRead(resource: ResourceInfo): void {
  readResult.value = null;
  readError.value = "";
  readUri.value = resource.uri;
  if (!resource.template) void read(resource.uri);
  else reading.value = resource.uri; // fill in the {placeholders} first
  // The reader sits below the list: bring it into view.
  void nextTick(() => reader.value?.scrollIntoView?.({ block: "nearest" }));
}

async function read(uri: string): Promise<void> {
  reading.value = uri;
  readError.value = "";
  try {
    readResult.value = { uri, text: await server.readResource(uri) };
    reading.value = null;
  } catch (err) {
    readError.value = errorMessage(err);
  }
}

/** Shown formatted when it's a JSON object, else as Markdown text. */
const readShown = computed(() => (readResult.value ? (formatToolResult(readResult.value.text) ?? readResult.value.text) : ""));

onMounted(load);
</script>
```

- [ ] **Step 8: Rewrite the view's `<template>` and add one style**

Replace the whole `<template>...</template>` block with:

```vue
<template>
  <section class="caps-view">
    <div class="column">
      <div class="head">
        <h2>
          Capabilities <span v-if="added.tools.length" class="count">{{ added.tools.length }} tools</span>
        </h2>
        <div class="head-actions">
          <RouterLink to="/capabilities/supermarket" class="shop">Supermarket</RouterLink>
        </div>
      </div>
      <p class="muted intro">What you've added: built-in capabilities and extensions. Open one to run its tools, or add more in the Supermarket.</p>
      <details class="how muted">
        <summary>How switches work</summary>
        <p>
          Each switch decides whether the agent and the <code>/</code> commands may use that capability or extension in
          your chats. What you've added follows your account to other devices. Turning one off here takes it off this
          page and puts it back in the Supermarket. Nothing is deleted. Admins can also turn a built-in capability off for
          everyone, from inside its card.
        </p>
      </details>
      <div v-if="!loading && !loadError" class="toolbar">
        <label class="search-box">
          <svg class="search-icon" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
            <path d="M7 12a5 5 0 1 0 0-10 5 5 0 0 0 0 10M11 11l3.5 3.5" />
          </svg>
          <input v-model="query" type="search" class="search" placeholder="Filter tools" aria-label="Filter tools" />
        </label>
        <SegmentedControl
          v-if="canTools"
          v-model="kind"
          class="kinds"
          aria-label="Show"
          :options="[
            { value: 'all', label: 'All' },
            { value: 'builtin', label: 'Built-in' },
            { value: 'extensions', label: 'Extensions' },
          ]"
        />
      </div>

      <p v-if="loading || accountLoading" class="muted">loading ...</p>
      <p v-else-if="loadError" class="error">error: {{ loadError }}</p>
      <p v-else-if="!account.ready" class="error">error: {{ account.error }}</p>
      <p v-if="actionError || switchError || (account.ready && account.error)" class="error">
        {{ actionError || switchError || account.error }}
      </p>

      <template v-if="!loading && !loadError && account.ready">
        <p v-if="nothingShown && filtering" class="muted">Nothing matches "{{ query.trim() }}".</p>
        <div v-else-if="nothingShown && nothingAdded" class="empty">
          <p class="muted">Nothing added yet. Open the Supermarket to add capabilities and extensions.</p>
          <RouterLink to="/capabilities/supermarket" class="shop">Open the Supermarket</RouterLink>
        </div>
        <p v-else-if="nothingShown" class="muted">No capabilities, extensions or tools in this view.</p>

        <template v-if="showBuiltin">
          <h4 v-if="groupHeadings && grouped.groups.length" class="group-title">Built-in</h4>
          <CapabilitySection
            v-for="g in grouped.groups"
            :key="g.capability.name"
            :label="g.capability.label ?? g.capability.name"
            :name="g.capability.name"
            icon="builtin"
            :open="isOpen(g.capability.name)"
            :summary="capabilitySummary(g.capability, g.tools.length)"
            :status="g.capability.enabled ? 'ok' : 'off'"
            :dimmed="!g.capability.enabled"
            :page="capabilityPage(g.capability)"
            control="switch"
            :checked="true"
            scope="Account"
            switch-title="Turn off for your account. It moves back to the Supermarket."
            @toggle="toggleSection(g.capability.name)"
            @switch="account.setCapability(g.capability.name, false)"
          >
            <p v-if="!g.capability.enabled" class="muted">Turned off for everyone: its tools and resources aren't offered to anyone.</p>
            <template v-else>
              <p v-if="g.tools.length === 0 && resourcesOf(g.capability).length === 0" class="muted">Nothing registered.</p>
              <ul v-if="g.tools.length" class="cards">
                <ToolCard v-for="t in g.tools" :key="t.name" :tool="t" @open="openToolModal(t.name)" />
              </ul>
              <p v-if="resourcesOf(g.capability).length" class="res-label">Resources</p>
              <ul v-if="resourcesOf(g.capability).length" class="resources">
                <li v-for="r in resourcesOf(g.capability)" :key="r.uri">
                  <svg class="res-icon" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M4 2h5l3 3v9H4zM9 2v3h3" /></svg>
                  <button type="button" class="link" @click="startRead(r)">{{ r.name }}</button>
                  <code class="name">{{ r.uri }}</code>
                  <span v-if="r.description" class="muted">{{ r.description }}</span>
                </li>
              </ul>
            </template>
            <div v-if="isAdmin" class="card-foot">
              <button
                type="button"
                class="everyone"
                :disabled="switching === g.capability.name"
                @click="askSwitch(g.capability)"
              >
                {{ g.capability.enabled ? "Turn off for everyone" : "Turn on for everyone" }}
              </button>
            </div>
          </CapabilitySection>
        </template>

        <template v-if="showExtensions">
          <h4 v-if="groupHeadings && grouped.extensionGroups.length" class="group-title">Extensions</h4>
          <CapabilitySection
            v-for="g in grouped.extensionGroups"
            :key="g.extension.id"
            :label="g.extension.label"
            :name="g.extension.id"
            icon="extension"
            :open="isOpen(extensionKey(g.extension.id))"
            :summary="extensionSummary(g)"
            :status="g.extension.status === 'connected' ? 'ok' : 'bad'"
            :page="extensionPage(g.extension)"
            control="switch"
            :checked="true"
            scope="Account"
            switch-title="Turn off for your account. It moves back to the Supermarket."
            @toggle="toggleSection(extensionKey(g.extension.id))"
            @switch="account.setExtension(g.extension.id, false)"
          >
            <p v-if="g.extension.description" class="muted">{{ g.extension.description }}</p>
            <p v-if="g.extension.status !== 'connected'" class="error">
              Not connected{{ g.extension.error ? `: ${g.extension.error}` : "" }}
            </p>
            <p
              v-else-if="canTools && g.tools.length === 0 && resourcesOfExtension(g.extension).length === 0"
              class="muted"
            >
              Nothing registered.
            </p>
            <ul v-if="canTools && g.tools.length" class="cards">
              <ToolCard v-for="t in g.tools" :key="t.name" :tool="t" @open="openToolModal(t.name)" />
            </ul>
            <p v-if="resourcesOfExtension(g.extension).length" class="res-label">Resources</p>
            <ul v-if="resourcesOfExtension(g.extension).length" class="resources">
              <li v-for="r in resourcesOfExtension(g.extension)" :key="r.uri">
                <svg class="res-icon" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M4 2h5l3 3v9H4zM9 2v3h3" /></svg>
                <button type="button" class="link" @click="startRead(r)">{{ r.name }}</button>
                <code class="name">{{ r.uri }}</code>
                <span v-if="r.description" class="muted">{{ r.description }}</span>
              </li>
            </ul>
          </CapabilitySection>
        </template>

        <h4 v-if="groupHeadings && showBuiltin && showOther" class="group-title">Other</h4>
        <CapabilitySection
          v-if="showBuiltin && showOther"
          label="Other tools"
          name="extensions"
          icon="other"
          :open="isOpen(OTHER)"
          :summary="countText(grouped.otherTools.length, filtering ? 0 : otherResources.length)"
          @toggle="toggleSection(OTHER)"
        >
          <ul v-if="grouped.otherTools.length" class="cards">
            <ToolCard v-for="t in grouped.otherTools" :key="t.name" :tool="t" @open="openToolModal(t.name)" />
          </ul>
          <p v-if="!filtering && otherResources.length" class="res-label">Resources</p>
          <ul v-if="!filtering && otherResources.length" class="resources">
            <li v-for="r in otherResources" :key="r.uri">
              <svg class="res-icon" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M4 2h5l3 3v9H4zM9 2v3h3" /></svg>
              <button type="button" class="link" @click="startRead(r)">{{ r.name }}</button>
              <code class="name">{{ r.uri }}</code>
            </li>
          </ul>
        </CapabilitySection>

        <section v-if="reading || readResult || readError" ref="reader" class="reader">
          <form v-if="reading" class="uri" @submit.prevent="read(readUri)">
            <label>
              URI
              <input v-model="readUri" type="text" spellcheck="false" />
            </label>
            <button class="primary">Read</button>
          </form>
          <p v-if="readError" class="error">{{ readError }}</p>
          <template v-if="readResult">
            <h3><code>{{ readResult.uri }}</code></h3>
            <MarkdownContent :text="readShown" />
          </template>
        </section>
      </template>
    </div>

    <ConfirmModal
      v-if="pendingSwitch"
      open
      :title="switchCopy.title"
      :message="switchCopy.message"
      :confirm-label="switchCopy.label"
      :danger="pendingSwitch.enabled"
      @confirm="confirmSwitch"
      @close="cancelSwitch"
    />

    <ToolRunModal
      :tool="selectedTool"
      :running="running"
      :result="result"
      @close="openTool = null"
      @run="(args) => selectedTool && run(selectedTool.name, args)"
    />
  </section>
</template>
```

In the same file's `<style scoped>` add after the `.head-actions` rule:

```css
.shop {
  padding: 6px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  font-size: 0.9em;
  color: var(--text);
  text-decoration: none;
}
.shop:hover {
  border-color: var(--accent);
}
.shop:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.empty {
  display: grid;
  justify-items: start;
  gap: 10px;
}
```

and delete the now unused `.primary` rule only if `.primary` is no longer used in the template (it is still used by the resource reader's Read button: keep it).

- [ ] **Step 9: Run the tests and the type check**

Run: `npx vitest run src/views/CapabilitiesView.test.ts src/utils src/components/CapabilitySection` then `npm run build`.
Expected: PASS and a clean build. Fix any remaining failing old assertion by reading the failure: the cause will be a card that is hidden because the test's account store has not added it (use `show({ added: ... })`) or a count that changed with the added filter.

- [ ] **Step 10: Commit**

```bash
git add apps/ember_web/src
git commit -m "feat(ember_web): Capabilities page lists only what the account added" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Supermarket page

**Checkpoint:** before editing, tell the user in three sentences what the page shows (two sections, filter chips, Add/Disable per row, admin extension add/remove) and wait for a yes.

**Files:**
- Create: `apps/ember_web/src/components/SupermarketItem.vue`
- Create: `apps/ember_web/src/views/SupermarketView.vue`
- Modify: `apps/ember_web/src/router/index.ts:39-45`
- Test: `apps/ember_web/src/components/SupermarketItem.test.ts`, `apps/ember_web/src/views/SupermarketView.test.ts`, `apps/ember_web/src/router/index.test.ts`

**Interfaces:**
- Consumes: `useAccountCapabilitiesStore()` (Task 4), `useEveryoneSwitch` and `CAPABILITY_ICONS` (Task 6), `AddExtensionModal` (props `open`; emits `close`, `added(ExtensionInfo)`), `ConfirmModal`, `useChatStore().refreshCommands()`.
- Produces: component `SupermarketItem` with props `label: string`, `name: string`, `icon: "builtin" | "extension"`, `summary: string`, `added: boolean`, `locked?: boolean`, `failed?: boolean`, emits `add`, `disable`, and slot `actions`.

- [ ] **Step 1: Write the failing tests for the row**

Create `apps/ember_web/src/components/SupermarketItem.test.ts`:

```ts
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import SupermarketItem from "./SupermarketItem.vue";

const base = { label: "PDF files", name: "pdf", icon: "builtin" as const, summary: "2 tools", added: false };

describe("SupermarketItem", () => {
  it("offers Add to something not added, and says what it is", () => {
    const w = mount(SupermarketItem, { props: base });

    expect(w.get("h3").text()).toBe("PDF files");
    expect(w.get("code").text()).toBe("pdf");
    expect(w.get(".summary").text()).toBe("2 tools");
    expect(w.get("button.add").attributes("aria-label")).toBe("Add PDF files");
    expect(w.find("button.secondary").exists()).toBe(false);
  });

  it("emits add", async () => {
    const w = mount(SupermarketItem, { props: base });

    await w.get("button.add").trigger("click");

    expect(w.emitted("add")).toHaveLength(1);
  });

  it("shows Added and a Disable button for something added", async () => {
    const w = mount(SupermarketItem, { props: { ...base, added: true } });

    expect(w.get(".added").text()).toContain("Added");
    expect(w.find("button.add").exists()).toBe(false);
    await w.get("button.secondary").trigger("click");
    expect(w.emitted("disable")).toHaveLength(1);
  });

  it("offers no Add for a capability that is off for everyone", () => {
    const w = mount(SupermarketItem, { props: { ...base, locked: true } });

    expect(w.get(".badge").text()).toBe("Off for everyone");
    expect(w.find("button.add").exists()).toBe(false);
  });

  it("still lets something added be disabled when it is off for everyone", () => {
    const w = mount(SupermarketItem, { props: { ...base, added: true, locked: true } });

    expect(w.find("button.secondary").exists()).toBe(true);
  });

  it("renders extra actions from the slot", () => {
    const w = mount(SupermarketItem, { props: base, slots: { actions: '<button class="extra">Remove</button>' } });

    expect(w.find("button.extra").exists()).toBe(true);
  });
});
```

- [ ] **Step 2: Run to verify failure, then write the component**

Run: `npx vitest run src/components/SupermarketItem.test.ts` — Expected: FAIL (component missing).

Create `apps/ember_web/src/components/SupermarketItem.vue`:

```vue
<script setup lang="ts">
import { CAPABILITY_ICONS } from "../utils/capabilityIcons";

/** One row of the Supermarket: a built-in capability or an extension, what it
 * brings, and whether it is added to the account. The parent decides what Add
 * and Disable mean; extra actions (an admin's Remove) go in the `actions` slot. */
defineProps<{
  label: string;
  name: string;
  icon: "builtin" | "extension";
  summary: string;
  added: boolean;
  /** Off for everyone (an administrator turned it off): it cannot be added. */
  locked?: boolean;
  /** The summary is a problem (an extension that is not connected). */
  failed?: boolean;
}>();
const emit = defineEmits<{ add: []; disable: [] }>();
</script>

<template>
  <article :class="['item', { off: locked && !added }]">
    <span class="tile" aria-hidden="true">
      <svg viewBox="0 0 16 16" width="18" height="18"><path :d="CAPABILITY_ICONS[icon]" /></svg>
    </span>
    <span class="heading">
      <h3>{{ label }}</h3>
      <code class="name">{{ name }}</code>
    </span>
    <span :class="['summary', failed ? 'bad' : 'muted']">{{ summary }}</span>
    <span class="actions">
      <slot name="actions" />
      <template v-if="added">
        <span class="added">
          <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M3 8.5l3.2 3L13 4.5" /></svg>
          Added
        </span>
        <button type="button" class="secondary" :aria-label="`Disable ${label}`" @click="emit('disable')">Disable</button>
      </template>
      <span v-else-if="locked" class="badge">Off for everyone</span>
      <button v-else type="button" class="add" :aria-label="`Add ${label}`" @click="emit('add')">Add</button>
    </span>
  </article>
</template>

<style scoped>
.item {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 12px;
  margin-bottom: 8px;
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface);
}
.item.off {
  opacity: 0.75;
}
.tile {
  display: grid;
  flex: none;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: var(--radius-md);
  background: var(--bg);
}
.tile svg {
  fill: none;
  stroke: var(--accent);
  stroke-width: 1.6;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.heading {
  display: flex;
  flex: 1 1 140px;
  flex-direction: column;
  min-width: 0;
}
h3 {
  margin: 0;
  font-size: 1em;
}
.name {
  font-family: var(--mono);
  font-size: 0.8em;
  color: var(--muted);
  overflow-wrap: anywhere;
}
.summary {
  padding: 1px 8px;
  border-radius: var(--radius-full);
  font-size: 0.75em;
  white-space: nowrap;
  background: var(--bg);
}
.muted {
  color: var(--muted);
}
.bad {
  color: var(--danger);
}
.actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}
.added {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.85em;
  color: var(--success);
}
.added svg {
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.badge {
  padding: 1px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  font-size: 0.75em;
  color: var(--muted);
}
button {
  padding: 4px 14px;
  border-radius: var(--radius-full);
  cursor: pointer;
  font-size: 0.85em;
}
button.add {
  border: 1px solid var(--accent);
  font-weight: 600;
  color: var(--accent-contrast);
  background: var(--accent);
}
button.secondary {
  border: 1px solid var(--border);
  color: var(--text);
  background: transparent;
}
button.secondary:hover {
  border-color: var(--accent);
}
button:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
</style>
```

Run: `npx vitest run src/components/SupermarketItem.test.ts` — Expected: PASS.

- [ ] **Step 3: Write the failing tests for the page**

Create `apps/ember_web/src/views/SupermarketView.test.ts`:

```ts
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import type { Account } from "../api/AuthClient";
import type { CapabilityInfo } from "../api/CommandsClient";
import ConfirmModal from "../components/admin/ConfirmModal.vue";
import { useAuthStore } from "../stores/auth";
import SupermarketView from "./SupermarketView.vue";

const mocks = vi.hoisted(() => ({
  capabilities: vi.fn(),
  setCapability: vi.fn(),
  extensions: vi.fn(),
  removeExtension: vi.fn(),
  accountGet: vi.fn(),
  accountSet: vi.fn(),
}));

vi.mock("../api/CommandsClient", () => ({
  commandsClient: { capabilities: mocks.capabilities, setCapability: mocks.setCapability },
}));
vi.mock("../api/ExtensionsClient", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/ExtensionsClient")>()),
  extensionsClient: { list: mocks.extensions, remove: mocks.removeExtension, add: vi.fn() },
}));
vi.mock("../api/AccountCapabilitiesClient", () => ({
  accountCapabilitiesClient: { get: mocks.accountGet, set: mocks.accountSet },
}));

const CAPS: CapabilityInfo[] = [
  { name: "pdf", enabled: true, label: "PDF files", tools: ["tool_pdf_merge", "tool_pdf_split"], resources: [] },
  { name: "calc", enabled: true, label: "Calculator", tools: ["tool_calc"], resources: [] },
  { name: "legacy", enabled: false, label: "Legacy", tools: [], resources: [] },
];
const EXT = { id: "notes", label: "Notes", description: "", status: "connected", error: null, tools: ["notes__add"] };
const BROKEN = { id: "wiki", label: "Wiki", description: "", status: "error", error: "refused", tools: [] };

const ACCOUNT: Account = { id: 1, username: "lex", email: "l@e.com", email_verified: true, roles: [], permissions: [] };

async function show(options: { permissions?: string[]; query?: string; added?: { capabilities?: string[]; extensions?: string[] } } = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().account = { ...ACCOUNT, permissions: options.permissions ?? ["tools.use", "chat.use"] };
  mocks.accountGet.mockResolvedValue({
    capabilities: options.added?.capabilities ?? ["pdf"],
    extensions: options.added?.extensions ?? [],
    disabled_tools: [],
  });
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/capabilities", component: { template: "<div />" } },
      { path: "/capabilities/supermarket", component: SupermarketView },
    ],
  });
  await router.push(`/capabilities/supermarket${options.query ? `?${options.query}` : ""}`);
  const wrapper = mount(SupermarketView, { global: { plugins: [pinia, router] } });
  await flushPromises();
  return { w: wrapper, router };
}

type Wrapper = Awaited<ReturnType<typeof show>>["w"];
const rows = (w: Wrapper) => w.findAll("article.item");
const names = (w: Wrapper) => rows(w).map((r) => r.find("h3").text());
const row = (w: Wrapper, label: string) => rows(w).find((r) => r.find("h3").text() === label)!;
const chip = (w: Wrapper, label: string) => w.findAll("button.chip").find((b) => b.text() === label)!;

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
  vi.clearAllMocks();
  mocks.capabilities.mockResolvedValue(CAPS);
  mocks.extensions.mockResolvedValue([EXT, BROKEN]);
  mocks.accountSet.mockImplementation(async () => ({ capabilities: ["pdf", "calc"], extensions: [], disabled_tools: [] }));
});

describe("SupermarketView", () => {
  it("lists built-in capabilities and extensions in two sections", async () => {
    const { w } = await show();

    expect(w.findAll("h4.group-title").map((h) => h.text())).toEqual(["Built-in", "Extensions"]);
    expect(names(w)).toEqual(["Calculator", "Legacy", "PDF files", "Notes", "Wiki"]);
    expect(row(w, "PDF files").find(".summary").text()).toBe("2 tools");
    expect(row(w, "Wiki").find(".summary").text()).toBe("Not connected");
  });

  it("shows Added for what the account has and Add for the rest", async () => {
    const { w } = await show();

    expect(row(w, "PDF files").find(".added").exists()).toBe(true);
    expect(row(w, "Calculator").find("button.add").exists()).toBe(true);
  });

  it("adds a capability for the account", async () => {
    const { w } = await show();

    await row(w, "Calculator").get("button.add").trigger("click");
    await flushPromises();

    expect(mocks.accountSet).toHaveBeenCalledWith("capability", "calc", true);
    expect(row(w, "Calculator").find(".added").exists()).toBe(true);
  });

  it("disables an added extension for the account", async () => {
    const { w } = await show({ added: { capabilities: [], extensions: ["notes"] } });

    await row(w, "Notes").get("button.secondary").trigger("click");
    await flushPromises();

    expect(mocks.accountSet).toHaveBeenCalledWith("extension", "notes", false);
  });

  it("marks a capability that is off for everyone and offers no Add", async () => {
    const { w } = await show();

    expect(row(w, "Legacy").find(".badge").text()).toBe("Off for everyone");
    expect(row(w, "Legacy").find("button.add").exists()).toBe(false);
    expect(row(w, "Legacy").find(".summary").text()).toBe("Off for everyone");
  });

  describe("the Enabled and Disabled chips", () => {
    it("start with neither chosen, showing everything", async () => {
      const { w } = await show();

      expect(chip(w, "Enabled").attributes("aria-pressed")).toBe("false");
      expect(chip(w, "Disabled").attributes("aria-pressed")).toBe("false");
      expect(rows(w)).toHaveLength(5);
    });

    it("Enabled shows only what is added", async () => {
      const { w, router } = await show();

      await chip(w, "Enabled").trigger("click");
      await flushPromises();

      expect(names(w)).toEqual(["PDF files"]);
      expect(router.currentRoute.value.query.state).toBe("enabled");
      expect(chip(w, "Enabled").attributes("aria-pressed")).toBe("true");
    });

    it("Disabled shows only what is not added", async () => {
      const { w } = await show();

      await chip(w, "Disabled").trigger("click");
      await flushPromises();

      expect(names(w)).toEqual(["Calculator", "Legacy", "Notes", "Wiki"]);
    });

    it("choosing the other chip switches, and clicking the active chip clears it", async () => {
      const { w, router } = await show();

      await chip(w, "Enabled").trigger("click");
      await flushPromises();
      await chip(w, "Disabled").trigger("click");
      await flushPromises();
      expect(router.currentRoute.value.query.state).toBe("disabled");

      await chip(w, "Disabled").trigger("click");
      await flushPromises();
      expect(router.currentRoute.value.query.state).toBeUndefined();
      expect(rows(w)).toHaveLength(5);
    });

    it("is read from the address", async () => {
      const { w } = await show({ query: "state=enabled" });

      expect(names(w)).toEqual(["PDF files"]);
    });

    it("says so when a section has nothing in this filter", async () => {
      const { w } = await show({ query: "state=enabled" });

      expect(w.text()).toContain("No extensions match this filter.");
    });
  });

  it("lists only the extensions to an account without tools.use", async () => {
    const { w } = await show({ permissions: ["chat.use"] });

    expect(mocks.capabilities).not.toHaveBeenCalled();
    expect(w.findAll("h4.group-title").map((h) => h.text())).toEqual(["Extensions"]);
    expect(names(w)).toEqual(["Notes", "Wiki"]);
  });

  describe("administrators", () => {
    const ADMIN = ["tools.use", "chat.use", "admin.manage"];

    it("add and remove extensions; others see neither", async () => {
      const user = await show();
      expect(user.w.text()).not.toContain("Add extension");
      expect(user.w.find("button.remove").exists()).toBe(false);

      const admin = await show({ permissions: ADMIN });
      expect(admin.w.text()).toContain("Add extension");
      await row(admin.w, "Notes").get("button.remove").trigger("click");
      expect(admin.w.getComponent(ConfirmModal).props("message")).toContain('Remove "Notes"');
    });

    it("removing an extension asks the server and reloads the account's choices", async () => {
      mocks.removeExtension.mockResolvedValue(undefined);
      const { w } = await show({ permissions: ADMIN, added: { extensions: ["notes"] } });
      await row(w, "Notes").get("button.remove").trigger("click");

      await w.getComponent(ConfirmModal).get(".confirm").trigger("click");
      await flushPromises();

      expect(mocks.removeExtension).toHaveBeenCalledWith("notes");
      expect(names(w)).not.toContain("Notes");
      expect(mocks.accountGet).toHaveBeenCalledTimes(2);
    });

    it("can turn a capability that is off for everyone back on, asking first", async () => {
      mocks.setCapability.mockResolvedValue({ ...CAPS[2]!, enabled: true });
      const { w } = await show({ permissions: ADMIN });

      await row(w, "Legacy").get("button.everyone").trigger("click");
      expect(w.getComponent(ConfirmModal).props("message")).toContain('Turn on "Legacy"');
      await w.getComponent(ConfirmModal).get(".confirm").trigger("click");
      await flushPromises();

      expect(mocks.setCapability).toHaveBeenCalledWith("legacy", true);
      expect(row(w, "Legacy").find(".badge").exists()).toBe(false);
    });

    it("shows no everyone button on a capability that is on for everyone", async () => {
      const { w } = await show({ permissions: ADMIN });

      expect(row(w, "PDF files").find("button.everyone").exists()).toBe(false);
    });
  });

  it("shows why a change failed", async () => {
    mocks.accountSet.mockRejectedValue(new Error("Too many items added to this account"));
    const { w } = await show();

    await row(w, "Calculator").get("button.add").trigger("click");
    await flushPromises();

    expect(w.get("[role=alert]").text()).toContain("Too many items added to this account");
  });

  it("reports a load failure", async () => {
    mocks.capabilities.mockRejectedValue(new Error("mcp_server is down"));
    const { w } = await show();

    expect(w.text()).toContain("mcp_server is down");
  });
});
```

- [ ] **Step 4: Run to verify failure, then write the page**

Run: `npx vitest run src/views/SupermarketView.test.ts` — Expected: FAIL (view missing).

Create `apps/ember_web/src/views/SupermarketView.vue`:

```vue
<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { RouterLink, useRoute, useRouter } from "vue-router";
import { commandsClient, type CapabilityInfo } from "../api/CommandsClient";
import { extensionsClient, type ExtensionInfo } from "../api/ExtensionsClient";
import ConfirmModal from "../components/admin/ConfirmModal.vue";
import AddExtensionModal from "../components/AddExtensionModal.vue";
import SupermarketItem from "../components/SupermarketItem.vue";
import { useEveryoneSwitch } from "../composables/useEveryoneSwitch";
import { useAccountCapabilitiesStore } from "../stores/accountCapabilities";
import { useAuthStore } from "../stores/auth";
import { useChatStore } from "../stores/chat";
import { errorMessage } from "../utils/errors";

/** Everything the account can add: mcp_server's built-in capabilities and its
 * extensions, in two sections, with Add and Disable per row. A user can only
 * add or disable; administrators also add and remove extensions on the server
 * and can turn a built-in capability back on for everyone. Two exclusive filter
 * chips (Enabled, Disabled) narrow both lists; the choice lives in the address
 * (?state=enabled|disabled). */

const auth = useAuthStore();
const account = useAccountCapabilitiesStore();
const chat = useChatStore();
const route = useRoute();
const router = useRouter();

const capabilities = ref<CapabilityInfo[]>([]);
const extensions = ref<ExtensionInfo[]>([]);
const loading = ref(true);
const loadError = ref("");
const actionError = ref("");
const addOpen = ref(false);
const pendingRemove = ref<ExtensionInfo | null>(null);
const removing = ref(false);

const isAdmin = computed(() => auth.hasPermission("admin.manage"));
// Capabilities need tools.use; the extension list needs chat.use or tools.use.
const canTools = computed(() => auth.hasPermission("tools.use"));
const accountLoading = computed(() => !account.ready && account.error === "");

type StateFilter = "enabled" | "disabled" | null;
const stateFilter = computed<StateFilter>(() =>
  route.query.state === "enabled" ? "enabled" : route.query.state === "disabled" ? "disabled" : null,
);

function chooseFilter(next: "enabled" | "disabled"): void {
  const query = { ...route.query };
  if (stateFilter.value === next) delete query.state;
  else query.state = next;
  void router.replace({ query });
}

const shown = (added: boolean): boolean => stateFilter.value === null || (stateFilter.value === "enabled") === added;
const byLabel = <T extends { label?: string | null; name?: string; id?: string }>(a: T, b: T): number =>
  (a.label ?? a.name ?? a.id ?? "").localeCompare(b.label ?? b.name ?? b.id ?? "");

const addedCapabilities = computed(() => new Set(account.capabilities));
const addedExtensions = computed(() => new Set(account.extensions));
const builtIn = computed(() =>
  [...capabilities.value].sort(byLabel).filter((c) => shown(addedCapabilities.value.has(c.name))),
);
const extensionRows = computed(() =>
  [...extensions.value].sort(byLabel).filter((e) => shown(addedExtensions.value.has(e.id))),
);

const toolsText = (n: number): string => `${n} tool${n === 1 ? "" : "s"}`;
const capabilitySummary = (c: CapabilityInfo): string => (c.enabled ? toolsText(c.tools.length) : "Off for everyone");
const extensionSummary = (e: ExtensionInfo): string => (e.status === "connected" ? toolsText(e.tools.length) : "Not connected");

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    const [caps, exts] = await Promise.all([
      canTools.value ? commandsClient.capabilities() : [],
      extensionsClient.list(),
    ]);
    capabilities.value = caps;
    extensions.value = exts;
  } catch (err) {
    loadError.value = errorMessage(err);
  } finally {
    loading.value = false;
  }
}

const {
  pending: pendingSwitch,
  error: switchError,
  copy: switchCopy,
  ask: askSwitch,
  cancel: cancelSwitch,
  confirm: confirmSwitch,
} = useEveryoneSwitch((updated) => {
  capabilities.value = capabilities.value.map((c) => (c.name === updated.name ? updated : c));
});

function onAdded(created: ExtensionInfo): void {
  extensions.value = [...extensions.value.filter((e) => e.id !== created.id), created];
  addOpen.value = false;
  chat.refreshCommands();
}

const removeMessage = computed(() =>
  pendingRemove.value
    ? `Remove "${pendingRemove.value.label}"? Its tools stop being offered to every mcp_server client.`
    : "",
);

async function confirmRemove(): Promise<void> {
  const extension = pendingRemove.value;
  if (!extension) return;
  actionError.value = "";
  removing.value = true;
  try {
    await extensionsClient.remove(extension.id);
    extensions.value = extensions.value.filter((e) => e.id !== extension.id);
    // ember_api cleared the extension from every account; read our copy again.
    await account.refresh();
    chat.refreshCommands();
  } catch (err) {
    actionError.value = errorMessage(err);
  } finally {
    removing.value = false;
    pendingRemove.value = null;
  }
}

onMounted(load);
</script>

<template>
  <section class="shop-view">
    <div class="column">
      <RouterLink to="/capabilities" class="back">&larr; Back to capabilities</RouterLink>
      <div class="head">
        <h2>Supermarket</h2>
        <div class="chips" role="group" aria-label="Filter by state">
          <button
            type="button"
            :class="['chip', { on: stateFilter === 'enabled' }]"
            :aria-pressed="stateFilter === 'enabled'"
            @click="chooseFilter('enabled')"
          >
            Enabled
          </button>
          <button
            type="button"
            :class="['chip', { on: stateFilter === 'disabled' }]"
            :aria-pressed="stateFilter === 'disabled'"
            @click="chooseFilter('disabled')"
          >
            Disabled
          </button>
        </div>
      </div>
      <p class="muted intro">Add the capabilities and extensions you want. They appear on your Capabilities page and become available to the agent in your chats.</p>

      <p v-if="loading || accountLoading" class="muted">loading ...</p>
      <p v-else-if="loadError" class="error">error: {{ loadError }}</p>
      <p v-else-if="!account.ready" class="error">error: {{ account.error }}</p>
      <p v-if="actionError || switchError || (account.ready && account.error)" class="error" role="alert">
        {{ actionError || switchError || account.error }}
      </p>

      <template v-if="!loading && !loadError && account.ready">
        <template v-if="canTools">
          <h4 class="group-title">Built-in</h4>
          <SupermarketItem
            v-for="c in builtIn"
            :key="c.name"
            :label="c.label ?? c.name"
            :name="c.name"
            icon="builtin"
            :summary="capabilitySummary(c)"
            :added="addedCapabilities.has(c.name)"
            :locked="!c.enabled"
            @add="account.setCapability(c.name, true)"
            @disable="account.setCapability(c.name, false)"
          >
            <template v-if="isAdmin && !c.enabled" #actions>
              <button type="button" class="everyone" @click="askSwitch(c)">Turn on for everyone</button>
            </template>
          </SupermarketItem>
          <p v-if="builtIn.length === 0" class="muted">No built-in capabilities match this filter.</p>
        </template>

        <div class="section-head">
          <h4 class="group-title">Extensions</h4>
          <button v-if="isAdmin" type="button" class="primary" @click="addOpen = true">Add extension</button>
        </div>
        <SupermarketItem
          v-for="e in extensionRows"
          :key="e.id"
          :label="e.label"
          :name="e.id"
          icon="extension"
          :summary="extensionSummary(e)"
          :failed="e.status !== 'connected'"
          :added="addedExtensions.has(e.id)"
          @add="account.setExtension(e.id, true)"
          @disable="account.setExtension(e.id, false)"
        >
          <template v-if="isAdmin" #actions>
            <button type="button" class="remove" :aria-label="`Remove ${e.label}`" @click="pendingRemove = e">Remove</button>
          </template>
        </SupermarketItem>
        <p v-if="extensionRows.length === 0" class="muted">No extensions match this filter.</p>
      </template>
    </div>

    <ConfirmModal
      v-if="pendingSwitch"
      open
      :title="switchCopy.title"
      :message="switchCopy.message"
      :confirm-label="switchCopy.label"
      :danger="pendingSwitch.enabled"
      @confirm="confirmSwitch"
      @close="cancelSwitch"
    />

    <ConfirmModal
      v-if="pendingRemove"
      open
      title="Remove extension"
      :message="removeMessage"
      confirm-label="Remove"
      danger
      :busy="removing"
      @confirm="confirmRemove"
      @close="pendingRemove = null"
    />

    <AddExtensionModal v-if="isAdmin" :open="addOpen" @close="addOpen = false" @added="onAdded" />
  </section>
</template>

<style scoped>
.shop-view {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.column {
  max-width: 820px;
  margin: 0 auto;
  padding: 24px 16px;
}
.back {
  display: inline-block;
  margin-bottom: 8px;
  font-size: 0.85em;
  color: var(--accent);
  text-decoration: none;
}
.back:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 6px;
}
h2 {
  margin: 0;
  font-size: 1.2em;
}
.chips {
  display: flex;
  gap: 8px;
}
.chip {
  padding: 4px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  cursor: pointer;
  font-size: 0.85em;
  color: var(--text);
  background: transparent;
}
.chip:hover {
  border-color: var(--accent);
}
.chip.on {
  border-color: var(--accent);
  font-weight: 600;
  color: var(--accent-contrast);
  background: var(--accent);
}
.chip:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.intro {
  margin: 0 0 12px;
  font-size: 0.9em;
}
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.group-title {
  margin: 16px 2px 8px;
  font-size: 0.8em;
  font-weight: 500;
}
.primary {
  padding: 6px 16px;
  border: none;
  border-radius: var(--radius-full);
  cursor: pointer;
  font-weight: 600;
  color: var(--accent-contrast);
  background: var(--accent);
}
.everyone,
.remove {
  padding: 4px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  cursor: pointer;
  font-size: 0.85em;
  color: var(--muted);
  background: transparent;
}
.everyone:hover {
  color: var(--text);
  border-color: var(--accent);
}
.remove {
  border-color: var(--danger);
  color: var(--danger);
}
.everyone:focus-visible,
.remove:focus-visible,
.primary:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.muted {
  color: var(--muted);
}
.error {
  color: var(--danger);
}
</style>
```

- [ ] **Step 5: Add the route and its tests**

In `apps/ember_web/src/router/index.ts`, directly before the `/capabilities/:name` route object, add:

```ts
    // Declared before /capabilities/:name so a capability named "supermarket" can never shadow it.
    {
      path: "/capabilities/supermarket",
      name: "supermarket",
      component: () => import("../views/SupermarketView.vue"),
      // tools.use for the built-in capabilities, chat.use for the extensions.
      meta: { permission: ["tools.use", "chat.use"] },
    },
```

In `apps/ember_web/src/router/index.test.ts`, directly after the test `"opens for chat.use alone, to switch extensions"`, add:

```ts
  it("opens the Supermarket for chat.use alone", async () => {
    me.mockResolvedValue({ ...ACCOUNT, permissions: ["chat.use"] });

    await router.push("/capabilities/supermarket");

    expect(router.currentRoute.value.name).toBe("supermarket");
  });

  it("keeps the Supermarket from being taken for a capability page", () => {
    expect(router.resolve("/capabilities/supermarket").name).toBe("supermarket");
    expect(router.resolve("/capabilities/pdf").name).toBe("capability-page");
  });
```

- [ ] **Step 6: Run the tests and the build**

Run: `npx vitest run src/views/SupermarketView.test.ts src/components/SupermarketItem.test.ts src/router` then `npm run build`.
Expected: PASS and a clean build. If a view test fails on the `.group-title` or `.confirm` selector, read the failure and compare with `ConfirmModal.vue`/the matching Capabilities test, and fix the selector or the markup, not the intent.

- [ ] **Step 7: Commit**

```bash
git add apps/ember_web/src
git commit -m "feat(ember_web): Supermarket page for adding capabilities and extensions" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Fake API, e2e, docs, full check

**Checkpoint:** before editing, tell the user in two sentences that this task only touches the e2e fake API, the e2e spec and the READMEs, and wait for a yes.

**Files:**
- Modify: `apps/ember_web/e2e/fakeApi.ts`
- Modify (rewrite): `apps/ember_web/e2e/capabilities.spec.ts`
- Modify: `apps/ember_web/README.md` (bullets near lines 128 and 167)

**Interfaces:**
- Consumes: the real routes' shape from Task 2.

- [ ] **Step 1: Teach the fake API the new routes**

In `apps/ember_web/e2e/fakeApi.ts`:

a) In `interface FakeApi` add:

```ts
  /** What the account has added (GET and PUT /api/account-capabilities). */
  accountCapabilities: { capabilities: Set<string>; extensions: Set<string> };
```

b) In the `const api: FakeApi = {` literal add `accountCapabilities: { capabilities: new Set(), extensions: new Set() },`. Directly after the line `for (const c of ADMIN_CAPABILITIES) api.capabilities.set(c.name, { ...c });` add `for (const c of ADMIN_CAPABILITIES) api.accountCapabilities.capabilities.add(c.name);` (an administrator login starts with everything added, so the existing Capabilities tests still find their cards).

c) In the route handler, directly before the line `if (method === "GET" && path === "/api/extensions") return json(route, []);` add:

```ts
    // What the account has added, and the tools of the capabilities it has not.
    const accountView = () => ({
      capabilities: [...api.accountCapabilities.capabilities].sort(),
      extensions: [...api.accountCapabilities.extensions].sort(),
      disabled_tools: [...api.capabilities.values()]
        .filter((c) => !api.accountCapabilities.capabilities.has(c.name))
        .flatMap((c) => c.tools)
        .sort(),
    });
    if (method === "GET" && path === "/api/account-capabilities") return json(route, accountView());
    const accountItem = /^\/api\/account-capabilities\/(capability|extension)\/([A-Za-z0-9_.-]+)$/.exec(path);
    if (method === "PUT" && accountItem) {
      const set = accountItem[1] === "capability" ? api.accountCapabilities.capabilities : api.accountCapabilities.extensions;
      if ((request.postDataJSON() as { enabled: boolean }).enabled) set.add(accountItem[2]!);
      else set.delete(accountItem[2]!);
      return json(route, accountView());
    }
```

- [ ] **Step 2: Rewrite the e2e spec**

Replace `apps/ember_web/e2e/capabilities.spec.ts` with:

```ts
import { expect, test } from "@playwright/test";
import { installFakeApi } from "./fakeApi.ts";
import { logIn } from "./helpers.ts";

const card = (page: import("@playwright/test").Page, name: string) =>
  page.locator("article.card").filter({ has: page.getByRole("heading", { name, exact: true }) });
const item = (page: import("@playwright/test").Page, name: string) =>
  page.locator("article.item").filter({ has: page.getByRole("heading", { name, exact: true }) });

test("a built-in capability turned off moves to the Supermarket and can be added back", async ({ page }) => {
  const api = await installFakeApi(page, { admin: true });
  await logIn(page);
  await page.getByRole("link", { name: "Capabilities", exact: true }).click();

  const pdf = card(page, "PDF files");
  await expect(pdf.getByRole("switch")).toBeChecked();
  await pdf.locator("label.toggle").click();
  await expect(pdf).toHaveCount(0);

  await page.getByRole("link", { name: "Supermarket" }).click();
  await expect(page).toHaveURL(/\/capabilities\/supermarket$/);
  await expect(item(page, "PDF files").getByRole("button", { name: "Add PDF files" })).toBeVisible();

  await item(page, "PDF files").getByRole("button", { name: "Add PDF files" }).click();
  await expect(item(page, "PDF files").getByText("Added")).toBeVisible();

  await page.reload();
  await expect(item(page, "PDF files").getByText("Added")).toBeVisible();
  await page.getByRole("link", { name: "Back to capabilities" }).click();
  await expect(card(page, "PDF files")).toBeVisible();
  expect(api.unexpected).toEqual([]);
});

test("an extension is added from the Supermarket and then listed on Capabilities", async ({ page }) => {
  const api = await installFakeApi(page, { admin: true });
  await page.route("**/api/extensions", (route) =>
    route.fulfill({
      json: [{ id: "echo", label: "Echo server", description: "", status: "connected", error: null, tools: [] }],
    }),
  );
  await logIn(page);
  await page.goto("/capabilities/supermarket");

  await expect(item(page, "Echo server").getByText("Added")).toHaveCount(0);
  await item(page, "Echo server").getByRole("button", { name: "Add Echo server" }).click();
  await expect(item(page, "Echo server").getByText("Added")).toBeVisible();

  await page.getByRole("button", { name: "Enabled" }).click();
  await expect(page).toHaveURL(/state=enabled/);
  await expect(item(page, "Echo server")).toBeVisible();

  await page.getByRole("link", { name: "Back to capabilities" }).click();
  await expect(card(page, "Echo server")).toBeVisible();
  await expect(card(page, "Echo server").getByRole("switch")).toBeChecked();
  expect(api.unexpected).toEqual([]);
});
```

- [ ] **Step 3: Update the ember_web README**

In `apps/ember_web/README.md` find the two bullets that start with `- Capabilities page` (near lines 128 and 167; `grep -n "Capabilities page" README.md`). Keep their existing wording about the tool list, the tool run modal, resources, Open buttons and admin everyone switch, and make these changes: say the page lists only what the account has added; the card switch turns the item off for the account (the card leaves the page); an account that has added nothing sees "Nothing added yet" with a link; add a new bullet directly after them:

```markdown
- Supermarket (`/capabilities/supermarket`, `tools.use` or `chat.use`; opened from a button on the Capabilities page): every built-in
  capability and extension in two sections, with Add and Disable per row. What an account has added is kept in ember_api
  (`/api/account-capabilities`), so it follows the account across devices; a new account starts with nothing added. Two exclusive
  filter chips, Enabled and Disabled, narrow the lists (clicking the active chip clears it; the choice is in the address as
  `?state=`). A capability an administrator turned off for everyone shows "Off for everyone" and cannot be added; administrators
  see "Turn on for everyone" there. Administrators also add and remove extensions in the Extensions section (`admin.manage`).
```

Also, in the `stores/` line (near line 374) add `accountCapabilities` to the list of Pinia stores.

- [ ] **Step 4: Run everything**

Run from `apps/ember_web`: `npx vitest run` then `npm run build` then `npx playwright test e2e/capabilities.spec.ts`.
Expected: all PASS. If Playwright cannot run in this environment (browsers not installed), say so in the report; do not claim the e2e passed.
Run from `apps/ember_api`: `python -m pytest -q`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/ember_web/e2e apps/ember_web/README.md
git commit -m "test(ember_web): e2e for the Supermarket; document it" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

## Self-review (done while writing)

- **Spec coverage:** model and migration (Task 1); service, routes, key and row limits, no-op repeat, logging (Task 2); extension removal cleanup and API docs (Task 3); store with optimistic update, rollback, reset on account change (Task 4); chat store reads the account store, blocks sending until loaded, never "everything on" (Task 5); Capabilities page: only added items, always-operable switch, Supermarket button, no Add/Remove, empty state, rewritten "How switches work", admin everyone button kept (Task 6); Supermarket route before `:name`, sections, chips with URL query, Add/Disable, off-for-everyone row and admin turn-on, admin Add/Remove extension (Task 7); e2e and READMEs (Task 8). The status dot is untouched (its `status` prop on `CapabilitySection` is unchanged). The deleted-account cascade is covered by the model's `ON DELETE CASCADE` and `test_migrations` model parity, not by its own test, as for `nav_preferences`.
- **Placeholder scan:** no TBD or "similar to". The README text in Task 8 step 3 edits existing bullets by instruction because those bullets' current wording was not reproduced here; the executor must read them first.
- **Type consistency:** `setCapability`/`setExtension`/`refresh`/`settled`/`disabledTools`/`ready`/`error` (Task 4) match their uses in Tasks 5-7; `enabledCapabilities`/`enabledExtensions` (Task 5) match the chat tests; `addedOnly` (Task 6) is used only by `CapabilitiesView`; `useEveryoneSwitch` returns `pending/switching/error/copy/ask/cancel/confirm` as destructured in both views; the API shape `{capabilities, extensions, disabled_tools}` is identical in ember_api (Task 2), the client (Task 4) and the fake API (Task 8).
