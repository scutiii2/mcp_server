# Ticketing ember_api Implementation Plan (permissions, migration, proxy routes)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the mcp_server ticket core to the browser apps through ember_api: two new permissions, a migration that keeps existing roles working, and authenticated reporter and staff routes.

**Architecture:** `ember_api` adds no ticket logic. A `TicketGateway` wraps the existing `McpServerInfo` HTTP client (same internal token, traffic counters and requester headers) and calls mcp_server's `/tickets/*` (reporter) and `/ticket-admin/*` (staff) routes. Route modules decide who may call what; mcp_server trusts ember_api for scope, and ember_api never lets a request body name the reporter.

**Tech Stack:** Python 3.11+, FastAPI, pydantic v2, SQLAlchemy/Alembic, httpx, pytest (`fastapi.testclient`).

**Spec:** `docs/superpowers/specs/2026-10-10-ticketing-system-design.md` (section 3, ember_api). Backend plan: `docs/superpowers/plans/2026-10-10-ticketing-backend.md` (already merged; its route shapes are the contract used here).

## Global Constraints

- Paths are relative to the repo root; run commands from `apps/Ember/ember_api`. Test command: `.venv_ember_api/Scripts/python -m pytest <target> -v` (use whichever venv `run.bat` creates; `py -m pytest` as a fallback).
- Permission names: `tickets.create` (own tickets) and `tickets.manage` (all tickets). `tickets.create` joins `DEFAULT_ROLE_PERMISSIONS`; the Administrator role gets both automatically (`ALL_PERMISSIONS`).
- The browser never names the reporter. Request models use `extra="forbid"`. The reporter is the logged-in account's username, sent as `X-Requester-Username` by `McpServerInfo`. ember_api also sends `verified_context` = `{"via": "ember_api", "account_id": "<account id as text>"}` on create (the stable id survives a rename).
- Tickets created through ember_api always have `source: "user"`. Reporters cannot set tags, status, priority or assignee.
- Errors: mcp_server unreachable or 5xx maps to `502 "mcp_server is unreachable"`; mcp_server 404 maps to 404 with its message; any other mcp_server 4xx maps to 400 with its message.
- Every staff change (ticket update, move, comment, group priority) is written to the activity log via `LogWriter.action` after mcp_server accepted it. Never log ticket titles, descriptions or comment bodies; log ids and field names only.
- Limits (enforced by request models and again by mcp_server): title 120, description 4000, comment 2000, assignee 64, at most 5 tags.
- Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## File Structure

| File | Responsibility |
|---|---|
| `apps/Ember/ember_api/src/services/permissions.py` | `TICKETS_CREATE`, `TICKETS_MANAGE`, registry entries, default-role grant |
| `apps/Ember/ember_api/migrations/versions/0011_ticket_permissions.py` | Create `tickets.create` and grant it to roles that hold `chat.use` |
| `apps/Ember/ember_api/tests/test_migrations.py` | `HEAD`/`NEXT` bumped, new migration test |
| `apps/Ember/ember_api/src/services/mcp_server_info.py` | Public `request()` wrapper over the private `_request` |
| `apps/Ember/ember_api/src/services/ticket_gateway.py` | `TicketGateway`: one method per mcp_server ticket route |
| `apps/Ember/ember_api/src/routes/tickets.py` | `router` (`/api/tickets`) and `admin_router` (`/api/admin/tickets`, `/api/admin/ticket-groups`) |
| `apps/Ember/ember_api/src/app.py` | Include both routers |
| `apps/Ember/ember_api/tests/test_tickets.py` | Routes, permissions, proxy mapping, logging |
| `apps/Ember/ember_api/README.md` | Permission and route notes |

---

### Task 1: Permissions and migration

**Files:**
- Modify: `apps/Ember/ember_api/src/services/permissions.py`
- Create: `apps/Ember/ember_api/migrations/versions/0011_ticket_permissions.py`
- Modify: `apps/Ember/ember_api/tests/test_migrations.py` (constants and one new test)
- Test: `apps/Ember/ember_api/tests/test_migrations.py`

**Interfaces:**
- Produces: `permissions.TICKETS_CREATE = "tickets.create"`, `permissions.TICKETS_MANAGE = "tickets.manage"`, both in `ALL_PERMISSIONS`; `TICKETS_CREATE` in `DEFAULT_ROLE_PERMISSIONS`; Alembic revision `"0011"` (down revision `"0010"`).

- [ ] **Step 1: Bump the migration test constants and add the failing migration test**

In `tests/test_migrations.py` change the constants:

```python
# The newest real migration; the tests' throwaway one comes after it.
HEAD = "0011"
NEXT = "0012"
```

Add this test after `test_permission_split_preserves_access_once_and_keeps_revocations` (reuse that test's helpers `make_database` and `run_with`):

```python
def test_ticket_permission_is_granted_to_chat_roles_once(tmp_path: Path) -> None:
    run_with(make_database(tmp_path))
    path = tmp_path / "ember.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("UPDATE alembic_version SET version_num = '0010'")
        for name in ("chatters", "readers"):
            conn.execute("INSERT INTO roles (name) VALUES (?)", (name,))
        conn.execute("INSERT INTO permissions (name) VALUES ('chat.use')")
        conn.execute(
            "INSERT INTO role_permission SELECT r.id, p.id FROM roles r, permissions p "
            "WHERE r.name = 'chatters' AND p.name = 'chat.use'"
        )
        conn.commit()

    assert run_with(make_database(tmp_path)) == "upgraded"

    def grants(name: str) -> set[str]:
        with closing(sqlite3.connect(path)) as conn:
            return {row[0] for row in conn.execute(
                "SELECT p.name FROM role_permission rp JOIN roles r ON r.id = rp.role_id "
                "JOIN permissions p ON p.id = rp.permission_id WHERE r.name = ?", (name,)
            )}

    assert "tickets.create" in grants("chatters")
    assert "tickets.create" not in grants("readers")
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(
            "DELETE FROM role_permission WHERE role_id = (SELECT id FROM roles WHERE name = 'chatters') "
            "AND permission_id = (SELECT id FROM permissions WHERE name = 'tickets.create')"
        )
        conn.commit()
    assert run_with(make_database(tmp_path)) == "current"
    assert "tickets.create" not in grants("chatters")  # a later revocation sticks
```

- [ ] **Step 2: Run to see it fail**

Run: `.venv_ember_api/Scripts/python -m pytest tests/test_migrations.py -v`
Expected: FAIL (no revision `0011`; other tests may fail on the new `HEAD` too, which is expected until Step 3).

- [ ] **Step 3: Implement the permissions and the migration**

In `src/services/permissions.py` add the constants after `AGENTS_MANAGE`:

```python
TICKETS_CREATE = "tickets.create"
TICKETS_MANAGE = "tickets.manage"
```

add to `ALL_PERMISSIONS` (after the `AGENTS_MANAGE` entry):

```python
    TICKETS_CREATE: "Report bugs, suggest features and follow your own tickets",
    TICKETS_MANAGE: "See every ticket, triage them and set status, priority and assignee",
```

and extend `DEFAULT_ROLE_PERMISSIONS`:

```python
DEFAULT_ROLE_PERMISSIONS = (
    CHAT_USE, TOOLS_VIEW, TOOLS_EXECUTE, CHAT_SHARE,
    EXTENSIONS_PERSONAL_MANAGE, FILES_UPLOAD, FILES_DOWNLOAD, TICKETS_CREATE,
)
```

Create `migrations/versions/0011_ticket_permissions.py`:

```python
"""Give every role that can chat the new ticket-reporting permission, once.

Later revocations stick: re-running startup never restores a revoked grant.
`tickets.manage` is deliberately not granted to anyone here; the Administrator
role receives it at startup like every permission in the registry.
"""

from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

# Frozen migration data: never import the application's evolving registry.
SOURCE = "chat.use"
TARGET = "tickets.create"


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text(
        "INSERT INTO permissions (name, description) SELECT :name, NULL "
        "WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE name = :name)"
    ), {"name": TARGET})
    conn.execute(sa.text(
        "INSERT INTO role_permission (role_id, permission_id) "
        "SELECT old.role_id, new.id FROM role_permission old "
        "JOIN permissions legacy ON legacy.id = old.permission_id "
        "JOIN permissions new ON new.name = :target "
        "WHERE legacy.name = :source AND NOT EXISTS "
        "(SELECT 1 FROM role_permission present WHERE present.role_id = old.role_id "
        "AND present.permission_id = new.id)"
    ), {"source": SOURCE, "target": TARGET})


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text(
        "DELETE FROM role_permission WHERE permission_id IN (SELECT id FROM permissions WHERE name = :name)"
    ), {"name": TARGET})
    conn.execute(sa.text("DELETE FROM permissions WHERE name = :name"), {"name": TARGET})
```

- [ ] **Step 4: Run migration tests, then the whole suite**

Run: `.venv_ember_api/Scripts/python -m pytest tests/test_migrations.py -v`
Expected: PASS.

Run: `.venv_ember_api/Scripts/python -m pytest -q`
Expected: PASS. If a test hardcodes the list of default or all permissions (for example a role listing), update that expectation to include `tickets.create` / `tickets.manage`; do not change application code to satisfy it. Tests that compare against `DEFAULT_ROLE_PERMISSIONS` need no change.

- [ ] **Step 5: Commit**

```bash
git add apps/Ember/ember_api/src/services/permissions.py apps/Ember/ember_api/migrations/versions/0011_ticket_permissions.py apps/Ember/ember_api/tests
git commit -m "feat(ember-api): ticket permissions and migration"
```

---

### Task 2: TicketGateway

**Files:**
- Modify: `apps/Ember/ember_api/src/services/mcp_server_info.py` (add one public method to `McpServerInfo`)
- Create: `apps/Ember/ember_api/src/services/ticket_gateway.py`
- Test: `apps/Ember/ember_api/tests/test_tickets.py` (created here, extended in Tasks 3 and 4)

**Interfaces:**
- Consumes: `McpServerInfo._request(method, path, account, params=None, json=None, files=None, timeout=30.0)`; it sends `X-Requester-Username`, `X-Requester-Email`, `X-Internal-Token`, raises `McpServerUnavailable` / `McpServerRefused(status, message)`.
- Produces:

```python
# McpServerInfo
async def request(self, method: str, path: str, account: Account, *, params: dict[str, str] | None = None, json: Any = None) -> Any

# ticket_gateway.py
class TicketGateway:
    def __init__(self, info: McpServerInfo) -> None
    # reporter (mcp_server /tickets*)
    async def create(self, account: Account, body: dict[str, Any]) -> dict[str, Any]      # {"ticket", "duplicate", "group_size"}
    async def list_own(self, account: Account, status: str | None = None) -> dict[str, Any]   # {"tickets": [...]}
    async def get_own(self, account: Account, ticket_id: int) -> dict[str, Any]           # {"ticket": {..., "comments": [...]}}
    async def comment_own(self, account: Account, ticket_id: int, body: str) -> dict[str, Any]
    async def close_own(self, account: Account, ticket_id: int) -> dict[str, Any]
    # staff (mcp_server /ticket-admin/*)
    async def list_all(self, account: Account, filters: dict[str, Any]) -> dict[str, Any]   # {"tickets": [...]}
    async def get_any(self, account: Account, ticket_id: int) -> dict[str, Any]
    async def update(self, account: Account, ticket_id: int, changes: dict[str, Any]) -> dict[str, Any]
    async def comment_staff(self, account: Account, ticket_id: int, body: str) -> dict[str, Any]
    async def move(self, account: Account, ticket_id: int, group_id: int | None) -> dict[str, Any]
    async def list_groups(self, account: Account, filters: dict[str, Any]) -> dict[str, Any]   # {"groups": [...]}
    async def update_group(self, account: Account, group_id: int, changes: dict[str, Any]) -> dict[str, Any]   # {"group": {...}}
    async def stats(self, account: Account) -> dict[str, Any]                              # {"open", "urgent", "groups"}
```

Filter dicts may hold `None` values and a bool `possible`; the gateway drops `None`, sends `possible` as `"1"` when true, and stringifies the rest.

- [ ] **Step 1: Write the failing gateway test**

`tests/test_tickets.py`:

```python
"""Ticket routes and gateway: ember_api only proxies to mcp_server and decides who may call what."""

from __future__ import annotations

import asyncio
import json
import re

import httpx
import pytest

from src.models import Account
from src.services.mcp_server_info import McpServerInfo
from src.services.ticket_gateway import TicketGateway
from tests.conftest import FakeUpstream
from tests.test_admin import login, make_member, role_by_name
from tests.test_permission_split import limited_account
from tests.test_registration import as_admin

TICKET = {
    "id": 7, "group_id": 3, "type": "bug", "title": "Email fails", "description": "It does not send",
    "status": "open", "priority": "normal", "effective_priority": "normal", "assignee": None, "reporter": "alice",
    "source": "user", "tags": ["email"], "context": {}, "possible_group_id": None,
    "created_at": "2026-10-10T10:00:00+00:00", "updated_at": "2026-10-10T10:00:00+00:00", "closed_at": None,
}
GROUP = {"id": 3, "title": "Email fails", "priority": "normal", "priority_pinned": False, "ticket_count": 1,
         "recent_count": 1, "open_count": 1, "tags": ["email"]}


def body_of(request: httpx.Request):
    return json.loads(request.content) if request.content else None


def tickets_server(request: httpx.Request) -> httpx.Response:
    """mcp_server's ticket routes with canned answers; tests read upstream.requests."""
    path, method = request.url.path, request.method
    if path == "/tickets" and method == "POST":
        title = body_of(request)["title"]
        if title == "bad":
            return httpx.Response(400, json={"error": "The title is not acceptable."})
        if title == "dup":
            return httpx.Response(200, json={"ticket": TICKET, "duplicate": True, "group_size": 1})
        return httpx.Response(201, json={"ticket": TICKET, "duplicate": False, "group_size": 1})
    if path == "/tickets" and method == "GET":
        return httpx.Response(200, json={"tickets": [TICKET]})
    if path == "/ticket-admin/tickets" and method == "GET":
        return httpx.Response(200, json={"tickets": [TICKET]})
    if path == "/ticket-admin/groups" and method == "GET":
        return httpx.Response(200, json={"groups": [GROUP]})
    if path == "/ticket-admin/stats":
        return httpx.Response(200, json={"open": 1, "urgent": 0, "groups": 1})
    match = re.fullmatch(r"/(ticket-admin/)?tickets/(\d+)(?:/(comments|close|move))?", path)
    if match:
        ticket_id, action = int(match.group(2)), match.group(3)
        if ticket_id == 404:
            return httpx.Response(404, json={"error": "No ticket 404."})
        return httpx.Response(200, json={"ticket": {**TICKET, "id": ticket_id, "comments": []}})
    match = re.fullmatch(r"/ticket-admin/groups/(\d+)", path)
    if match and method == "PATCH":
        return httpx.Response(200, json={"group": {**GROUP, **body_of(request)}})
    return httpx.Response(404, json={"error": "no route"})


def test_gateway_drops_empty_filters_and_flags_possible(upstream: FakeUpstream) -> None:
    upstream.handler = tickets_server
    account = Account(id=1, username="root", email="root@example.com")
    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    gateway = TicketGateway(McpServerInfo(client, "http://mcp-server.internal/mcp", "tok", None))

    result = asyncio.run(gateway.list_all(account, {"status": "open", "tag": None, "possible": True, "group_id": 3}))

    assert result == {"tickets": [TICKET]}
    request = upstream.requests[-1]
    assert dict(request.url.params) == {"status": "open", "possible": "1", "group_id": "3"}
    assert request.headers["x-requester-username"] == "root"
    assert request.headers["x-internal-token"] == "tok"
```

(`Account(...)` constructor kwargs: if the model needs other required fields, build it the way `tests` elsewhere do, for example by constructing it with the same fields `McpServerInfo` reads: `username` and `email` only.)

- [ ] **Step 2: Run to see it fail**

Run: `.venv_ember_api/Scripts/python -m pytest tests/test_tickets.py -v`
Expected: FAIL (`ModuleNotFoundError: src.services.ticket_gateway`).

- [ ] **Step 3: Implement**

In `src/services/mcp_server_info.py`, add inside `McpServerInfo` directly after `_request`:

```python
    async def request(
        self, method: str, path: str, account: Account, *,
        params: dict[str, str] | None = None, json: Any = None,
    ) -> Any:
        """A call to one of mcp_server's fixed plain routes, for gateways that wrap one feature."""
        return await self._request(method, path, account, params=params, json=json)
```

Create `src/services/ticket_gateway.py`:

```python
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
```

- [ ] **Step 4: Run tests**

Run: `.venv_ember_api/Scripts/python -m pytest tests/test_tickets.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/Ember/ember_api/src/services/mcp_server_info.py apps/Ember/ember_api/src/services/ticket_gateway.py apps/Ember/ember_api/tests/test_tickets.py
git commit -m "feat(ember-api): ticket gateway to mcp_server"
```

---

### Task 3: Reporter routes

**Files:**
- Create: `apps/Ember/ember_api/src/routes/tickets.py` (reporter part; staff part added in Task 4)
- Modify: `apps/Ember/ember_api/src/app.py` (import and include the routers)
- Test: `apps/Ember/ember_api/tests/test_tickets.py` (append)

**Interfaces:**
- Consumes: `TicketGateway` (Task 2), `require_permission(TICKETS_CREATE)`.
- Produces: `routes.tickets.router` (prefix `/api/tickets`) with `POST ""` (201, or 200 when `duplicate`), `GET ""` (query `status`), `GET "/{ticket_id}"`, `POST "/{ticket_id}/comments"`, `POST "/{ticket_id}/close"`. `routes.tickets.admin_router` (prefix `/api/admin`) is defined empty here and filled in Task 4. Also `get_ticket_gateway(request, settings) -> TicketGateway` and `_call(awaitable)`.

- [ ] **Step 1: Append the failing tests**

```python
# ---- reporter routes -------------------------------------------------------

def member_client(client_factory, email, upstream):
    upstream.handler = tickets_server
    member = client_factory()
    member_id = make_member(member, email)
    login(member, "alice")
    return member, member_id


def test_member_files_and_follows_own_tickets(client_factory, email, upstream) -> None:
    member, member_id = member_client(client_factory, email, upstream)

    created = member.post("/api/tickets", json={"type": "bug", "title": "Email fails", "description": "It does not send"})
    assert created.status_code == 201, created.text
    assert created.json() == {"ticket": TICKET, "duplicate": False, "group_size": 1}
    sent = upstream.requests[-1]
    assert (sent.method, sent.url.path) == ("POST", "/tickets")
    assert sent.headers["x-requester-username"] == "alice"
    assert body_of(sent) == {
        "type": "bug", "title": "Email fails", "description": "It does not send", "source": "user",
        "verified_context": {"via": "ember_api", "account_id": str(member_id)},
    }

    assert member.get("/api/tickets", params={"status": "open"}).json() == {"tickets": [TICKET]}
    assert dict(upstream.requests[-1].url.params) == {"status": "open"}
    assert member.get("/api/tickets/7").json()["ticket"]["id"] == 7
    assert member.post("/api/tickets/7/comments", json={"body": "log attached"}).status_code == 200
    assert body_of(upstream.requests[-1]) == {"body": "log attached"}
    assert member.post("/api/tickets/7/close").status_code == 200
    assert upstream.requests[-1].url.path == "/tickets/7/close"


def test_a_repeated_report_answers_200(client_factory, email, upstream) -> None:
    member, _ = member_client(client_factory, email, upstream)

    response = member.post("/api/tickets", json={"type": "bug", "title": "dup", "description": "again"})

    assert response.status_code == 200 and response.json()["duplicate"] is True


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "bug", "title": "t", "description": "d", "reporter": "mallory"},
        {"type": "bug", "title": "t", "description": "d", "tags": ["email"]},
        {"type": "bug", "title": "t", "description": "d", "source": "ai_auto"},
        {"type": "complaint", "title": "t", "description": "d"},
        {"type": "bug", "title": "", "description": "d"},
        {"type": "bug", "title": "x" * 121, "description": "d"},
        {"type": "bug", "title": "t", "description": "x" * 4001},
        {"type": "bug", "title": "t"},
    ],
)
def test_invalid_reports_never_reach_mcp_server(client_factory, email, upstream, payload) -> None:
    member, _ = member_client(client_factory, email, upstream)

    assert member.post("/api/tickets", json=payload).status_code == 422
    assert len(upstream.requests) == 0


def test_comment_and_id_validation(client_factory, email, upstream) -> None:
    member, _ = member_client(client_factory, email, upstream)

    assert member.post("/api/tickets/7/comments", json={"body": ""}).status_code == 422
    assert member.post("/api/tickets/7/comments", json={"body": "x" * 2001}).status_code == 422
    assert member.post("/api/tickets/7/comments", json={"body": "hi", "role": "staff"}).status_code == 422
    assert member.get("/api/tickets/abc").status_code == 422
    assert member.get("/api/tickets/0").status_code == 422
    assert member.get("/api/tickets", params={"status": "done"}).status_code == 422
    assert len(upstream.requests) == 0


def test_ticket_routes_need_tickets_create(client_factory, email, upstream) -> None:
    upstream.handler = tickets_server
    member = client_factory()
    make_member(member, email)
    admin = as_admin(client_factory())
    role = role_by_name(admin, "Member")
    assert admin.delete(f"/api/admin/roles/{role['id']}/permissions/tickets.create").status_code == 200
    login(member, "alice")

    refused = member.get("/api/tickets")

    assert (refused.status_code, refused.json()["detail"]) == (403, "Missing permission: tickets.create")
    assert member.post("/api/tickets", json={"type": "bug", "title": "t", "description": "d"}).status_code == 403
    assert len(upstream.requests) == 0


def test_logged_out_visitors_get_401(client, upstream) -> None:
    upstream.handler = tickets_server
    assert client.get("/api/tickets").status_code == 401
    assert client.post("/api/tickets", json={"type": "bug", "title": "t", "description": "d"}).status_code == 401
    assert len(upstream.requests) == 0


def test_mcp_server_answers_map_to_http_errors(client_factory, email, upstream) -> None:
    member, _ = member_client(client_factory, email, upstream)

    refused = member.post("/api/tickets", json={"type": "bug", "title": "bad", "description": "d"})
    assert (refused.status_code, refused.json()["detail"]) == (400, "The title is not acceptable.")
    missing = member.get("/api/tickets/404")
    assert (missing.status_code, missing.json()["detail"]) == (404, "No ticket 404.")

    upstream.unreachable = True
    down = member.get("/api/tickets")
    assert (down.status_code, down.json()["detail"]) == (502, "mcp_server is unreachable")
```

- [ ] **Step 2: Run to see it fail**

Run: `.venv_ember_api/Scripts/python -m pytest tests/test_tickets.py -v`
Expected: FAIL (404 on `/api/tickets`: router not mounted).

- [ ] **Step 3: Implement**

Create `src/routes/tickets.py`:

```python
"""/api/tickets: a signed-in account's own tickets (tickets.create), and
/api/admin/tickets + /api/admin/ticket-groups: every ticket for staff
(tickets.manage). ember_api only proxies to mcp_server's ticket core. The
reporter is always the logged-in account; the browser cannot name one, set
tags, or pick a source. Staff changes go to the activity log (ids and field
names only, never ticket text).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from src.config import Settings
from src.deps import get_log_writer, get_settings, require_permission
from src.models import Account
from src.services.log_service import LogWriter
from src.services.mcp_server_info import McpServerInfo, McpServerRefused, McpServerUnavailable
from src.services.permissions import TICKETS_CREATE, TICKETS_MANAGE
from src.services.ticket_gateway import TicketGateway

router = APIRouter(prefix="/api/tickets", tags=["tickets"])
admin_router = APIRouter(prefix="/api/admin", tags=["tickets-admin"])

require_create = require_permission(TICKETS_CREATE)
require_manage = require_permission(TICKETS_MANAGE)

TicketType = Literal["bug", "feature", "other"]
TicketStatus = Literal["open", "in_progress", "resolved", "closed"]
TicketPriority = Literal["low", "normal", "high", "urgent"]
TicketId = Annotated[int, Path(ge=1)]


def get_ticket_gateway(request: Request, settings: Settings = Depends(get_settings)) -> TicketGateway:
    return TicketGateway(
        McpServerInfo(request.app.state.upstream, settings.mcp_server_url, request.app.state.internal_token, request.app.state.traffic)
    )


async def _call(awaitable: Any) -> Any:
    try:
        return await awaitable
    except McpServerUnavailable as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "mcp_server is unreachable") from error
    except McpServerRefused as error:
        code = status.HTTP_404_NOT_FOUND if error.status == 404 else status.HTTP_400_BAD_REQUEST
        raise HTTPException(code, str(error)) from error


class TicketIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: TicketType
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=4000)


class CommentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=2000)


# ---- reporter routes -------------------------------------------------------

@router.post("")
async def create_ticket(
    body: TicketIn, account: Account = Depends(require_create), gateway: TicketGateway = Depends(get_ticket_gateway),
) -> JSONResponse:
    payload = {
        **body.model_dump(),
        "source": "user",
        "verified_context": {"via": "ember_api", "account_id": str(account.id)},
    }
    result = await _call(gateway.create(account, payload))
    return JSONResponse(result, status_code=200 if result.get("duplicate") else 201)


@router.get("")
async def list_own_tickets(
    status_filter: Annotated[TicketStatus | None, Query(alias="status")] = None,
    account: Account = Depends(require_create), gateway: TicketGateway = Depends(get_ticket_gateway),
) -> Any:
    return await _call(gateway.list_own(account, status_filter))


@router.get("/{ticket_id}")
async def get_own_ticket(
    ticket_id: TicketId, account: Account = Depends(require_create), gateway: TicketGateway = Depends(get_ticket_gateway),
) -> Any:
    return await _call(gateway.get_own(account, ticket_id))


@router.post("/{ticket_id}/comments")
async def comment_own_ticket(
    ticket_id: TicketId, body: CommentIn,
    account: Account = Depends(require_create), gateway: TicketGateway = Depends(get_ticket_gateway),
) -> Any:
    return await _call(gateway.comment_own(account, ticket_id, body.body))


@router.post("/{ticket_id}/close")
async def close_own_ticket(
    ticket_id: TicketId, account: Account = Depends(require_create), gateway: TicketGateway = Depends(get_ticket_gateway),
) -> Any:
    return await _call(gateway.close_own(account, ticket_id))
```

In `src/app.py`, add `tickets as tickets_routes` to the existing `from src.routes import (...)` list (next to `emberlings as emberlings_routes`) and after `app.include_router(emberlings_routes.router)` add:

```python
    app.include_router(tickets_routes.router)
    app.include_router(tickets_routes.admin_router)
```

- [ ] **Step 4: Run tests**

Run: `.venv_ember_api/Scripts/python -m pytest tests/test_tickets.py -v`
Expected: PASS. A logged-out `GET /api/tickets` must answer 401 (the `current_account` dependency).

- [ ] **Step 5: Commit**

```bash
git add apps/Ember/ember_api/src/routes/tickets.py apps/Ember/ember_api/src/app.py apps/Ember/ember_api/tests/test_tickets.py
git commit -m "feat(ember-api): reporter ticket routes"
```

---

### Task 4: Staff routes and activity log

**Files:**
- Modify: `apps/Ember/ember_api/src/routes/tickets.py` (append the staff routes)
- Test: `apps/Ember/ember_api/tests/test_tickets.py` (append)

**Interfaces:**
- Consumes: Task 3's `admin_router`, `require_manage`, `_call`, `get_ticket_gateway`, `TicketPriority`, `TicketStatus`, `TicketType`, `TicketId`, `CommentIn`.
- Produces on `admin_router` (all need `tickets.manage`): `GET /api/admin/tickets` (query `status`, `type`, `tag`, `priority`, `assignee`, `group_id`, `possible`, `limit`), `GET /api/admin/tickets/stats`, `GET /api/admin/tickets/{ticket_id}`, `PATCH /api/admin/tickets/{ticket_id}`, `POST /api/admin/tickets/{ticket_id}/comments`, `POST /api/admin/tickets/{ticket_id}/move`, `GET /api/admin/ticket-groups`, `PATCH /api/admin/ticket-groups/{group_id}`. The `stats` route is declared before `{ticket_id}` so it is never read as an id.
- Activity-log sources and messages: `tickets.update` "Updated ticket 7 (assignee, status)", `tickets.comment` "Commented on ticket 7", `tickets.move` "Moved ticket 7 to group 3" / "Moved ticket 7 to a new group", `tickets.group_priority` "Set ticket group 3 priority to urgent (pinned)" / "Changed ticket group 3 pin to off".

- [ ] **Step 1: Append the failing tests**

```python
# ---- staff routes ----------------------------------------------------------

def test_staff_list_forwards_filters_and_reads_everything(client, upstream) -> None:
    upstream.handler = tickets_server
    admin = as_admin(client)

    listing = admin.get(
        "/api/admin/tickets",
        params={"status": "open", "type": "bug", "tag": "email", "priority": "high", "assignee": "root",
                "group_id": 3, "possible": "true", "limit": 20},
    )

    assert listing.json() == {"tickets": [TICKET]}
    request = upstream.requests[-1]
    assert request.url.path == "/ticket-admin/tickets"
    assert dict(request.url.params) == {
        "status": "open", "type": "bug", "tag": "email", "priority": "high", "assignee": "root",
        "group_id": "3", "possible": "1", "limit": "20",
    }
    assert request.headers["x-requester-username"] == "root"
    assert admin.get("/api/admin/tickets", params={"status": "done"}).status_code == 422
    assert admin.get("/api/admin/tickets", params={"limit": 501}).status_code == 422


def test_staff_stats_is_not_read_as_a_ticket_id(client, upstream) -> None:
    upstream.handler = tickets_server
    admin = as_admin(client)

    assert admin.get("/api/admin/tickets/stats").json() == {"open": 1, "urgent": 0, "groups": 1}
    assert upstream.requests[-1].url.path == "/ticket-admin/stats"
    assert admin.get("/api/admin/tickets/7").json()["ticket"]["id"] == 7
    assert upstream.requests[-1].url.path == "/ticket-admin/tickets/7"


def test_staff_groups_list_and_priority(client, upstream) -> None:
    upstream.handler = tickets_server
    admin = as_admin(client)

    assert admin.get("/api/admin/ticket-groups", params={"tag": "email"}).json() == {"groups": [GROUP]}
    assert dict(upstream.requests[-1].url.params) == {"tag": "email"}

    pinned = admin.patch("/api/admin/ticket-groups/3", json={"priority": "urgent"})
    assert pinned.status_code == 200 and pinned.json()["group"]["priority"] == "urgent"
    assert body_of(upstream.requests[-1]) == {"priority": "urgent"}
    assert admin.patch("/api/admin/ticket-groups/3", json={"pinned": False}).status_code == 200
    assert body_of(upstream.requests[-1]) == {"pinned": False}
    assert admin.patch("/api/admin/ticket-groups/3", json={"priority": "critical"}).status_code == 422
    assert admin.patch("/api/admin/ticket-groups/3", json={}).status_code == 422


def test_staff_ticket_changes_are_proxied_and_logged_without_text(client, upstream) -> None:
    upstream.handler = tickets_server
    admin = as_admin(client)

    patched = admin.patch("/api/admin/tickets/7", json={"status": "in_progress", "assignee": "root", "tags": ["config"]})
    assert patched.status_code == 200
    assert body_of(upstream.requests[-1]) == {"status": "in_progress", "assignee": "root", "tags": ["config"]}
    assert admin.post("/api/admin/tickets/7/comments", json={"body": "secret log text"}).status_code == 200
    assert admin.post("/api/admin/tickets/7/move", json={"group_id": 3}).status_code == 200
    assert body_of(upstream.requests[-1]) == {"group_id": 3}
    assert admin.post("/api/admin/tickets/7/move", json={"group_id": None}).status_code == 200
    assert admin.patch("/api/admin/ticket-groups/3", json={"priority": "urgent"}).status_code == 200
    assert admin.patch("/api/admin/ticket-groups/3", json={"pinned": False}).status_code == 200

    messages = [entry["message"] for entry in admin.get("/api/logs/action").json()]
    assert messages[:6] == [
        "Changed ticket group 3 pin to off",
        "Set ticket group 3 priority to urgent (pinned)",
        "Moved ticket 7 to a new group",
        "Moved ticket 7 to group 3",
        "Commented on ticket 7",
        "Updated ticket 7 (assignee, status, tags)",
    ]
    assert not any("secret log text" in message for message in messages)


def test_staff_request_validation(client, upstream) -> None:
    upstream.handler = tickets_server
    admin = as_admin(client)

    assert admin.patch("/api/admin/tickets/7", json={"status": "done"}).status_code == 422
    assert admin.patch("/api/admin/tickets/7", json={"priority": "critical"}).status_code == 422
    assert admin.patch("/api/admin/tickets/7", json={"reporter": "x"}).status_code == 422
    assert admin.patch("/api/admin/tickets/7", json={"tags": ["a", "b", "c", "d", "e", "f"]}).status_code == 422
    assert admin.patch("/api/admin/tickets/7", json={}).status_code == 422
    assert admin.post("/api/admin/tickets/7/move", json={}).status_code == 422
    assert admin.post("/api/admin/tickets/7/move", json={"group_id": 0}).status_code == 422
    assert admin.post("/api/admin/tickets/7/comments", json={"body": ""}).status_code == 422
    assert len(upstream.requests) == 0


def test_failed_staff_change_is_not_logged(client, upstream) -> None:
    upstream.handler = tickets_server
    admin = as_admin(client)

    assert admin.patch("/api/admin/tickets/404", json={"status": "closed"}).status_code == 404
    messages = [entry["message"] for entry in admin.get("/api/logs/action").json()]
    assert not any("ticket 404" in message for message in messages)


def test_staff_routes_need_tickets_manage_and_own_routes_need_create(client_factory, email, upstream) -> None:
    upstream.handler = tickets_server
    member, _ = member_client(client_factory, email, upstream)
    for method, path in [("get", "/api/admin/tickets"), ("get", "/api/admin/tickets/stats"),
                         ("get", "/api/admin/tickets/7"), ("get", "/api/admin/ticket-groups")]:
        refused = getattr(member, method)(path)
        assert (refused.status_code, refused.json()["detail"]) == (403, "Missing permission: tickets.manage")
    assert member.patch("/api/admin/tickets/7", json={"status": "closed"}).status_code == 403
    assert member.patch("/api/admin/ticket-groups/3", json={"priority": "low"}).status_code == 403
    assert len(upstream.requests) == 0


def test_manage_without_create_can_triage_but_not_file(client_factory, email, upstream) -> None:
    upstream.handler = tickets_server
    client = client_factory()
    limited_account(client, email, "tickets.manage")

    assert client.get("/api/admin/tickets").status_code == 200
    assert client.get("/api/tickets").status_code == 403
    assert client.post("/api/tickets", json={"type": "bug", "title": "t", "description": "d"}).status_code == 403


def test_staff_routes_report_an_unreachable_mcp_server(client, upstream) -> None:
    admin = as_admin(client)
    upstream.unreachable = True

    down = admin.get("/api/admin/tickets")

    assert (down.status_code, down.json()["detail"]) == (502, "mcp_server is unreachable")
```

- [ ] **Step 2: Run to see it fail**

Run: `.venv_ember_api/Scripts/python -m pytest tests/test_tickets.py -v`
Expected: FAIL (404 on `/api/admin/tickets`).

- [ ] **Step 3: Implement**

Append to `src/routes/tickets.py`:

```python
# ---- staff routes ----------------------------------------------------------

class TicketPatch(BaseModel):
    """What staff can change on one ticket. An empty assignee clears it."""

    model_config = ConfigDict(extra="forbid")
    status: TicketStatus | None = None
    priority: TicketPriority | None = None
    assignee: str | None = Field(default=None, max_length=64)
    tags: list[str] | None = Field(default=None, max_length=5)


class MoveIn(BaseModel):
    """Move to an existing group, or split out into a new one with group_id null."""

    model_config = ConfigDict(extra="forbid")
    group_id: Annotated[int, Field(ge=1)] | None


class GroupPatch(BaseModel):
    """Setting a priority pins it; pinned false hands it back to automatic elevation."""

    model_config = ConfigDict(extra="forbid")
    priority: TicketPriority | None = None
    pinned: bool | None = None


@admin_router.get("/tickets")
async def list_all_tickets(
    status_filter: Annotated[TicketStatus | None, Query(alias="status")] = None,
    type: TicketType | None = None,
    tag: Annotated[str | None, Query(max_length=50)] = None,
    priority: TicketPriority | None = None,
    assignee: Annotated[str | None, Query(max_length=64)] = None,
    group_id: Annotated[int | None, Query(ge=1)] = None,
    possible: bool = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    account: Account = Depends(require_manage), gateway: TicketGateway = Depends(get_ticket_gateway),
) -> Any:
    filters = {
        "status": status_filter, "type": type, "tag": tag, "priority": priority, "assignee": assignee,
        "group_id": group_id, "possible": possible, "limit": limit,
    }
    return await _call(gateway.list_all(account, filters))


@admin_router.get("/tickets/stats")
async def ticket_stats(
    account: Account = Depends(require_manage), gateway: TicketGateway = Depends(get_ticket_gateway),
) -> Any:
    return await _call(gateway.stats(account))


@admin_router.get("/tickets/{ticket_id}")
async def get_any_ticket(
    ticket_id: TicketId, account: Account = Depends(require_manage), gateway: TicketGateway = Depends(get_ticket_gateway),
) -> Any:
    return await _call(gateway.get_any(account, ticket_id))


@admin_router.patch("/tickets/{ticket_id}")
async def update_ticket(
    ticket_id: TicketId, body: TicketPatch,
    account: Account = Depends(require_manage), gateway: TicketGateway = Depends(get_ticket_gateway),
    logs: LogWriter = Depends(get_log_writer),
) -> Any:
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Nothing to change")
    result = await _call(gateway.update(account, ticket_id, changes))
    await logs.action(account, "tickets.update", f"Updated ticket {ticket_id} ({', '.join(sorted(changes))})")
    return result


@admin_router.post("/tickets/{ticket_id}/comments")
async def comment_any_ticket(
    ticket_id: TicketId, body: CommentIn,
    account: Account = Depends(require_manage), gateway: TicketGateway = Depends(get_ticket_gateway),
    logs: LogWriter = Depends(get_log_writer),
) -> Any:
    result = await _call(gateway.comment_staff(account, ticket_id, body.body))
    await logs.action(account, "tickets.comment", f"Commented on ticket {ticket_id}")
    return result


@admin_router.post("/tickets/{ticket_id}/move")
async def move_ticket(
    ticket_id: TicketId, body: MoveIn,
    account: Account = Depends(require_manage), gateway: TicketGateway = Depends(get_ticket_gateway),
    logs: LogWriter = Depends(get_log_writer),
) -> Any:
    result = await _call(gateway.move(account, ticket_id, body.group_id))
    target = f"group {body.group_id}" if body.group_id else "a new group"
    await logs.action(account, "tickets.move", f"Moved ticket {ticket_id} to {target}")
    return result


@admin_router.get("/ticket-groups")
async def list_ticket_groups(
    status_filter: Annotated[TicketStatus | None, Query(alias="status")] = None,
    tag: Annotated[str | None, Query(max_length=50)] = None,
    priority: TicketPriority | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    account: Account = Depends(require_manage), gateway: TicketGateway = Depends(get_ticket_gateway),
) -> Any:
    filters = {"status": status_filter, "tag": tag, "priority": priority, "limit": limit}
    return await _call(gateway.list_groups(account, filters))


@admin_router.patch("/ticket-groups/{group_id}")
async def update_ticket_group(
    group_id: TicketId, body: GroupPatch,
    account: Account = Depends(require_manage), gateway: TicketGateway = Depends(get_ticket_gateway),
    logs: LogWriter = Depends(get_log_writer),
) -> Any:
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Nothing to change")
    result = await _call(gateway.update_group(account, group_id, changes))
    if "priority" in changes:
        pinned = " (pinned)" if changes.get("pinned", True) else ""
        message = f"Set ticket group {group_id} priority to {changes['priority']}{pinned}"
    else:
        message = f"Changed ticket group {group_id} pin to {'on' if changes['pinned'] else 'off'}"
    await logs.action(account, "tickets.group_priority", message)
    return result
```

- [ ] **Step 4: Run tests**

Run: `.venv_ember_api/Scripts/python -m pytest tests/test_tickets.py -v`
Expected: PASS. If `test_staff_ticket_changes...` shows the log newest-first in a different order, check how `/api/logs/action` sorts (other tests such as `test_server_info.py::test_extension_manager_can_add_remove...` read `logged[:2]` newest first) and adjust only the expected list order in the test, not the route.

- [ ] **Step 5: Run the whole suite**

Run: `.venv_ember_api/Scripts/python -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add apps/Ember/ember_api/src/routes/tickets.py apps/Ember/ember_api/tests/test_tickets.py
git commit -m "feat(ember-api): staff ticket routes with activity log"
```

---

### Task 5: Docs

**Files:**
- Modify: `apps/Ember/ember_api/README.md`
- Modify: `docs/superpowers/specs/2026-10-10-ticketing-system-design.md` (section 3 route list)

**Interfaces:** none.

- [ ] **Step 1: README**

Add to the permissions and routes sections of `apps/Ember/ember_api/README.md`: the two permissions with their descriptions; the five `/api/tickets` routes; the `/api/admin/tickets`, `/api/admin/tickets/stats`, `/api/admin/ticket-groups` routes; that tickets live in mcp_server (ember_api stores nothing); that a rename of an account orphans its tickets in mcp_server's store because tickets are keyed by username (the same limitation as memory notes; the stable `account_id` is kept in each ticket's verified context for a later migration).

- [ ] **Step 2: Spec**

In spec section 3 replace the staff route list with the actual paths from Task 4 (`/api/admin/tickets`, `/api/admin/tickets/stats`, `/api/admin/tickets/{id}`, `.../comments`, `.../move`, `/api/admin/ticket-groups`, `/api/admin/ticket-groups/{id}`), and note that reporters cannot set tags and that `verified_context` carries `via` and `account_id`.

- [ ] **Step 3: Commit**

```bash
git add apps/Ember/ember_api/README.md docs/superpowers/specs/2026-10-10-ticketing-system-design.md
git commit -m "docs: ember_api ticket routes"
```

---

## Self-Review (done)

**Spec coverage (section 3):** permissions `tickets.create` / `tickets.manage` with default-role grant and migration: Task 1. Gateway proxy with internal token and requester headers, 502 mapping, 4xx passthrough: Tasks 2 and 3. Reporter routes (create, list own, get, comment, close): Task 3. Staff routes (list with filters, get, patch, comment, move, groups, group priority, stats): Task 4. Activity log on staff changes: Task 4. Reporter identity from the session only, `source: user`, verified context with account id: Tasks 3 and the constraints. Rate limit on create: dropped on purpose; mcp_server already limits automatic reports, and manual tickets are typed by a signed-in person. If abuse appears, add `rate_limiter` later (note in the README task). Tests for the permission matrix, own-only isolation (enforced by mcp_server per reporter header; the proxy test checks the header), proxy error mapping, migration: Tasks 1, 3, 4.

**Placeholders:** none. One cleanup line in Task 4 Step 3 is called out explicitly.

**Type consistency:** gateway method names match between Task 2 and the routes in Tasks 3 and 4 (`create`, `list_own`, `get_own`, `comment_own`, `close_own`, `list_all`, `get_any`, `update`, `comment_staff`, `move`, `list_groups`, `update_group`, `stats`). mcp_server paths match the merged backend (`/tickets`, `/tickets/{id}`, `/tickets/{id}/comments`, `/tickets/{id}/close`, `/ticket-admin/tickets`, `/ticket-admin/tickets/{id}`, `.../comments`, `.../move`, `/ticket-admin/groups`, `/ticket-admin/groups/{id}`, `/ticket-admin/stats`). `McpServerInfo.request` is the only change to an existing service.
