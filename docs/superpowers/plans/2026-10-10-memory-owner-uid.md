# Memory Owner UID Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Key memory notes on a new immutable per-account `uid` instead of the username, carry it from `ember_api` through `ai_agent` to `mcp_server`, and delete an account's notes when the account is deleted.

**Architecture:** `ember_api` gets `Account.uid` (random UUID hex, unique, never changes) and sends it as `X-Requester-Uid`. `ai_agent` carries it in its `Requester` and in `_meta.requester`. `mcp_server` reads it with `identity_context.current_uid()`; the memory capability uses it as the owner. A token-protected HTTP route on `mcp_server` (`DELETE /memory/owners/{uid}`) removes a user's notes, and `ember_api` calls it after deleting an account.

**Tech Stack:** Python 3.11+, FastAPI/SQLAlchemy/Alembic (`ember_api`), FastMCP and Starlette (`mcp_server`), httpx, pytest.

**Spec:** `docs/superpowers/specs/2026-10-10-memory-owner-uid-design.md` (amends `docs/superpowers/specs/2026-10-10-persistent-memory-design.md`)

## Global Constraints

- Work spans `apps/mcp_server`, `apps/ai_agent`, `apps/Ember/ember_api` and the `_TODO.md` / memory docs. Do not touch `apps/Ember/ember_web`, `apps/chat_cli`, or any `.env*` / `secrets/` file.
- The uid is `uuid.uuid4().hex` (32 lowercase hex characters), created with the account, unique, never reassigned, never returned by any `ember_api` response, never logged, never forwarded to third-party extensions (`mcp_server/src/services/extensions.py::_requester_meta` keeps sending only username and email).
- Header name `X-Requester-Uid` (lowercase `x-requester-uid` on the `mcp_server` side). `_meta.requester` key `uid`.
- A sender with an empty uid sends no header and no `uid` key, so old callers and existing tests keep their shape.
- Memory refuses (clear message, nothing touched) when `identity_context.current_uid()` is empty. The refusal text is exactly: `No account identity is known for this request, so memory is unavailable.`
- The purge route is an HTTP route, not a tool; it checks `X-Internal-Token` like `src/upload_routes.py::_token_valid` (an unset token never validates); it only accepts a uid matching `^[0-9a-f]{32}$`; it returns 404 and does nothing when the `memory` capability is offline.
- The purge call from `ember_api` is best effort: it never raises, never blocks or undoes the deletion, and a failure is written to the log with `logs.error`.
- Follow the repo conventions already used by the surrounding code. Edit skills only under `.agents/skills/` if any is touched (none should be).
- Work on a git branch or worktree, never on `main`. Conventional commit messages. One commit per task.
- Run each project's tests with its own venv from its own folder. In a git worktree the venvs live in the main checkout: use `D:/User/Documents/Programming/Python/MCPServer/apps/<project path>/<venv>/Scripts/python -m pytest ...` with the worktree folder as the working directory (`src` then resolves to the worktree). Venv folders: `apps/mcp_server/.venv_mcp`, `apps/ai_agent/.venv_ai_agent`, `apps/Ember/ember_api/.venv_ember_api`.
- Take a baseline pass count for each project's whole suite before the first change (as of 2026-10-10: `mcp_server` 746 passed, `ember_api` 1074 passed; take `ai_agent`'s yourself). The `ember_api` suite takes about 8 minutes; run it in the background.

## File Structure

- `apps/mcp_server/src/services/identity_context.py` (modify): `current_uid()`, header, middleware.
- `apps/mcp_server/src/services/memory_store.py` (modify): `purge_owner`, refusal text.
- `apps/mcp_server/src/capabilities/memory/domain.py` (modify): owner is the uid.
- `apps/mcp_server/src/memory_routes.py` (create): the purge route. `apps/mcp_server/src/run.py` (modify): install it.
- `apps/ai_agent/src/core/internal_auth.py` (modify): `Requester.uid`, header, meta.
- `apps/Ember/ember_api/src/models/account.py`, `migrations/versions/0011_account_uid.py` (create), `tests/test_migrations.py` (modify): the uid column.
- `apps/Ember/ember_api/src/services/agent_gateway.py`, `mcp_session.py`, `mcp_proxy.py`, `agent_admin.py`, `mcp_server_info.py`, `server_tools.py`, and the three `Caller(...)` sites in `routes/chats.py`, `routes/server_info.py`, `routes/user_extensions.py` (modify): send the uid.
- `apps/Ember/ember_api/src/services/memory_purger.py` (create), `src/deps.py`, `src/app.py`, `src/routes/admin.py` (modify): the purge call.
- Tests: new `mcp_server/tests/test_identity_uid.py`, `test_memory_routes.py`; changed `test_memory_store.py`, `test_memory_capability.py`; changed `ai_agent/tests/test_internal_auth.py`; new `ember_api/tests/test_account_uid.py`, `test_memory_purge.py`; changed `test_mcp_proxy.py`, `test_agent_admin.py`, `test_agent_gateway.py`, `test_download.py`.
- Docs: `apps/mcp_server/src/capabilities/memory/README.md`, `STATIC-GUIDELINES.md`, `_TODO.md`.

---

### Task 1: mcp_server reads the uid, keys memory on it, and can purge an owner

**Files:**
- Modify: `apps/mcp_server/src/services/identity_context.py`, `apps/mcp_server/src/services/memory_store.py`, `apps/mcp_server/src/capabilities/memory/domain.py`, `apps/mcp_server/src/run.py`
- Create: `apps/mcp_server/src/memory_routes.py`
- Test: create `apps/mcp_server/tests/test_identity_uid.py`, `apps/mcp_server/tests/test_memory_routes.py`; modify `apps/mcp_server/tests/test_memory_store.py`, `apps/mcp_server/tests/test_memory_capability.py`

**Interfaces:**
- Produces (used by other tasks): `identity_context.current_uid() -> str`; `memory_store.purge_owner(path: Path, owner: str) -> int`; route `DELETE /memory/owners/{uid}` returning `{"purged": <int>}` (200), 401 bad token, 400 bad uid, 404 capability offline; the memory refusal text in Global Constraints.

- [ ] **Step 1: Write the failing tests**

Create `apps/mcp_server/tests/test_identity_uid.py`:

```python
"""current_uid(): read from the header or _meta.requester, like the username."""

from __future__ import annotations

import pytest
from mcp.server.lowlevel.server import request_ctx
from mcp.shared.context import RequestContext
from mcp.types import RequestParams
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from src.services import extensions, identity_context
from src.services.identity_context import IdentityContextMiddleware


@pytest.fixture
def mcp_request_meta():
    tokens = []

    def bind(meta: dict | None) -> None:
        context = RequestContext(
            request_id=1,
            meta=RequestParams.Meta(**meta) if meta is not None else None,
            session=None,
            lifespan_context=None,
        )
        tokens.append(request_ctx.set(context))

    yield bind
    for token in reversed(tokens):
        request_ctx.reset(token)


def test_the_uid_falls_back_to_request_meta(mcp_request_meta):
    mcp_request_meta({"requester": {"username": "alice", "uid": "u-1"}})
    assert identity_context.current_uid() == "u-1"


def test_the_uid_is_empty_without_meta_or_with_odd_meta(mcp_request_meta):
    assert identity_context.current_uid() == ""
    mcp_request_meta(None)
    assert identity_context.current_uid() == ""
    mcp_request_meta({"requester": {"uid": 7}})
    assert identity_context.current_uid() == ""


def test_the_header_wins_over_meta_and_is_scoped_to_one_request(mcp_request_meta):
    async def whoami(request):
        return JSONResponse({"uid": identity_context.current_uid(), "username": identity_context.current_username()})

    app = Starlette(routes=[Route("/who", whoami)])
    app.add_middleware(IdentityContextMiddleware)
    client = TestClient(app)
    mcp_request_meta({"requester": {"uid": "from-meta"}})

    sent = client.get("/who", headers={"X-Requester-Uid": "abc123", "X-Requester-Username": "alice"})
    assert sent.json() == {"uid": "abc123", "username": "alice"}
    # No header: the middleware sets nothing, so the meta fallback applies again.
    assert client.get("/who").json()["uid"] == "from-meta"


def test_the_uid_is_never_forwarded_to_extensions(monkeypatch):
    monkeypatch.setattr(extensions, "current_username", lambda: "alice")
    monkeypatch.setattr(extensions, "current_email", lambda: "alice@example.com")
    token = identity_context._uid.set("secret-uid")
    try:
        meta = extensions._requester_meta()
    finally:
        identity_context._uid.reset(token)
    assert meta == {"requester": {"username": "alice", "email": "alice@example.com"}}
```

In `apps/mcp_server/tests/test_memory_store.py`:
- change the three `match="signed-in user"` to `match="account identity"` (in `test_every_operation_refuses_without_an_owner`);
- add this test after `test_note_ids_are_not_reused_after_a_delete` (or at the end of the file if that name differs):

```python
def test_purge_owner_removes_only_that_owners_notes_from_both_tables(db):
    store.save(db, "uid-a", "alpha one")
    store.save(db, "uid-a", "alpha two")
    keep = store.save(db, "uid-b", "beta keeps this")

    assert store.purge_owner(db, "uid-a") == 2

    assert store.search(db, "uid-a") == []
    assert store.search(db, "uid-a", "alpha") == []
    assert [n.id for n in store.search(db, "uid-b", "beta")] == [keep.id]
    assert store.purge_owner(db, "uid-a") == 0


def test_purge_owner_creates_nothing_and_refuses_an_empty_owner(db):
    assert store.purge_owner(db, "uid-a") == 0
    assert not db.exists()
    with pytest.raises(store.MemoryStoreError, match="account identity"):
        store.purge_owner(db, "")
```

In `apps/mcp_server/tests/test_memory_capability.py`:
- in the `capability` fixture replace `monkeypatch.setattr(identity_context, "current_username", lambda: "alice")` with `monkeypatch.setattr(identity_context, "current_uid", lambda: "uid-alice")`;
- in `test_every_tool_refuses_without_an_identity` replace the `current_username` patch with `current_uid` returning `""` and change `match="signed-in user"` to `match="account identity"`; also set `current_username` to `"alice"` there so the test proves a username alone is not enough;
- in `test_notes_are_private_to_their_owner` replace the `current_username` patch (`"bob"`) with `current_uid` returning `"uid-bob"`.

Create `apps/mcp_server/tests/test_memory_routes.py`:

```python
"""DELETE /memory/owners/{uid}: the route ember_api calls when an account is deleted."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from src import memory_routes
from src.memory_routes import install_memory_routes
from src.services import memory_store

TOKEN = "shared-secret"
UID_A = "a" * 32
UID_B = "b" * 32


@pytest.fixture
def db(tmp_path):
    return tmp_path / "memory.db"


@pytest.fixture
def fake_settings(monkeypatch, db):
    fake = SimpleNamespace(internal_api_token=TOKEN, memory_db_path=db)
    monkeypatch.setattr(memory_routes, "settings", fake)
    return fake


@pytest.fixture
def online(monkeypatch):
    state = {"on": True}
    monkeypatch.setattr(memory_routes, "_memory_online", lambda: state["on"])
    return state


@pytest.fixture
def client(fake_settings, online):
    app = Starlette()
    install_memory_routes(app)
    with TestClient(app) as test_client:
        yield test_client


def purge(client, uid=UID_A, token=TOKEN):
    headers = {"X-Internal-Token": token} if token is not None else {}
    return client.delete(f"/memory/owners/{uid}", headers=headers)


def test_it_removes_only_that_owners_notes(client, db):
    memory_store.save(db, UID_A, "alpha")
    memory_store.save(db, UID_B, "beta")

    response = purge(client)

    assert response.status_code == 200 and response.json() == {"purged": 1}
    assert memory_store.search(db, UID_A) == []
    assert len(memory_store.search(db, UID_B)) == 1


def test_an_owner_with_no_notes_purges_zero(client):
    assert purge(client).json() == {"purged": 0}


@pytest.mark.parametrize("token", [None, "wrong"])
def test_a_missing_or_wrong_token_is_a_401_and_deletes_nothing(client, db, token):
    memory_store.save(db, UID_A, "alpha")
    assert purge(client, token=token).status_code == 401
    assert len(memory_store.search(db, UID_A)) == 1


def test_an_unset_token_never_validates(client, fake_settings, db):
    fake_settings.internal_api_token = ""
    memory_store.save(db, UID_A, "alpha")
    assert purge(client, token="").status_code == 401
    assert len(memory_store.search(db, UID_A)) == 1


@pytest.mark.parametrize("uid", ["alice", "A" * 32, "a" * 31, "a" * 33, "..%2F"])
def test_only_a_32_hex_uid_is_accepted(client, uid):
    assert purge(client, uid=uid).status_code in (400, 404)


def test_it_does_nothing_when_memory_is_offline(client, online, db):
    memory_store.save(db, UID_A, "alpha")
    online["on"] = False
    assert purge(client).status_code == 404
    assert len(memory_store.search(db, UID_A)) == 1


def test_only_delete_is_allowed(client):
    assert client.get(f"/memory/owners/{UID_A}", headers={"X-Internal-Token": TOKEN}).status_code == 405
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `apps/mcp_server`): `<venv>/python -m pytest tests/test_identity_uid.py tests/test_memory_store.py tests/test_memory_capability.py tests/test_memory_routes.py -q -p no:cacheprovider`
Expected: failures and import errors (`current_uid`, `purge_owner`, `memory_routes` do not exist; message text differs).

- [ ] **Step 3: Implement identity_context**

In `apps/mcp_server/src/services/identity_context.py`:
- next to the other header constants add `REQUESTER_UID_HEADER = "x-requester-uid"`;
- next to the other ContextVars add `_uid: ContextVar[str] = ContextVar("requester_uid", default="")`;
- after `current_email()` add:

```python
def current_uid() -> str:
    """The account's stable id (never changes, never reused), unlike the username."""
    return _uid.get() or _from_request_meta("uid")
```

- in `IdentityContextMiddleware.__call__`, read it with the other two (`uid = raw_headers.get(REQUESTER_UID_HEADER.encode("latin-1"), b"").decode("utf-8")`), set it (`uid_token = _uid.set(uid)`) and reset it (`_uid.reset(uid_token)`) in the same `try/finally` as the other two.
- Update the module docstring's mention of the getters to include the uid.

- [ ] **Step 4: Implement the store and domain changes**

In `apps/mcp_server/src/services/memory_store.py`:
- change `_NO_OWNER` to `"No account identity is known for this request, so memory is unavailable."`;
- append:

```python
@catalog
def purge_owner(path: Path, owner: str) -> int:
    """Delete every note of `owner` (their account was deleted); returns how many."""
    owner = _owner(owner)
    if not path.exists():
        return 0
    with closing(_connect(path)) as db, db:
        ids = [row["id"] for row in db.execute("SELECT id FROM notes WHERE owner = ?", (owner,))]
        db.executemany("DELETE FROM notes_fts WHERE rowid = ?", [(note_id,) for note_id in ids])
        db.execute("DELETE FROM notes WHERE owner = ?", (owner,))
    return len(ids)
```

In `apps/mcp_server/src/capabilities/memory/domain.py` change `_owner()` to `return identity_context.current_uid()`.

- [ ] **Step 5: Implement the route**

Create `apps/mcp_server/src/memory_routes.py`:

```python
"""DELETE /memory/owners/{uid}: removes one account's memory notes.

A plain HTTP route and not a tool, so no model can name a user: only
ember_api calls it, after it deletes an account. Checked against the
internal token like /upload (an unset token never validates).
"""

from __future__ import annotations

import asyncio
import hmac
import re

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.config import settings
from src.services import capability_registry, memory_store

_UID = re.compile(r"[0-9a-f]{32}")


def _token_valid(request: Request) -> bool:
    expected = settings.internal_api_token
    provided = request.headers.get("X-Internal-Token", "")
    if not expected:
        return False
    return hmac.compare_digest(expected, provided)


def _memory_online() -> bool:
    return "memory" in capability_registry.names() and capability_registry.is_enabled("memory")


async def purge_memory_owner(request: Request) -> JSONResponse:
    if not _token_valid(request):
        return JSONResponse({"error": "Invalid or missing internal API token"}, status_code=401)
    if not _memory_online():
        return JSONResponse({"error": "Memory is not enabled"}, status_code=404)
    uid = request.path_params["uid"]
    if not _UID.fullmatch(uid):
        return JSONResponse({"error": "Not a valid account uid"}, status_code=400)
    purged = await asyncio.to_thread(memory_store.purge_owner, settings.memory_db_path, uid)
    return JSONResponse({"purged": purged})


def install_memory_routes(app: Starlette) -> None:
    app.add_route("/memory/owners/{uid}", purge_memory_owner, methods=["DELETE"])
```

In `apps/mcp_server/src/run.py`: add `from src.memory_routes import install_memory_routes` next to the other `install_*_routes` imports inside the same function, and call `install_memory_routes(app)` right after `install_download_routes(app)` with the comment `# Deletes an account's memory notes when ember_api deletes the account. See memory_routes.py.`

- [ ] **Step 6: Run the tests to verify they pass**

Run: `<venv>/python -m pytest tests/test_identity_uid.py tests/test_memory_store.py tests/test_memory_capability.py tests/test_memory_routes.py -q -p no:cacheprovider`
Expected: all PASS. If a parametrized uid case in `test_only_a_32_hex_uid_is_accepted` returns 405 or another code, print the response and decide: only 400 or 404 are acceptable; fix the route, not the test. Then run the whole `mcp_server` suite (about 30 s): no failures.

- [ ] **Step 7: Commit**

```bash
git add apps/mcp_server/src apps/mcp_server/tests
git commit -m "feat(mcp-server): key memory on the account uid and add a purge route"
```

---

### Task 2: ai_agent carries the uid

**Files:**
- Modify: `apps/ai_agent/src/core/internal_auth.py`
- Test: `apps/ai_agent/tests/test_internal_auth.py`

**Interfaces:**
- Produces: `Requester(username, email, uid="")`; `Requester.from_headers` reads `X-Requester-Uid`; `requester_meta()` adds `"uid"` only when non-empty; `outbound_headers()` adds `X-Requester-Uid` when non-empty; constant `REQUESTER_UID_HEADER = "X-Requester-Uid"`.

- [ ] **Step 1: Write the failing tests**

Read `apps/ai_agent/tests/test_internal_auth.py` first (the existing tests at lines ~47-70 show the style). Append:

```python
def test_the_uid_is_read_from_headers_and_carried_in_meta_and_outbound_headers(monkeypatch):
    monkeypatch.setattr(internal_auth, "TOKEN", "")
    requester = Requester.from_headers(
        {"X-Requester-Username": "alice", "X-Requester-Email": "a@x.com", "X-Requester-Uid": "u-1"}
    )
    assert requester == Requester("alice", "a@x.com", "u-1")

    token = internal_auth.bind_requester(requester)
    try:
        assert internal_auth.requester_meta() == {
            "requester": {"username": "alice", "email": "a@x.com", "uid": "u-1"}
        }
        assert internal_auth.outbound_headers()["X-Requester-Uid"] == "u-1"
    finally:
        internal_auth.reset_requester(token)


def test_without_a_uid_the_old_shapes_are_unchanged(monkeypatch):
    monkeypatch.setattr(internal_auth, "TOKEN", "")
    token = internal_auth.bind_requester(Requester("alice", "a@x.com"))
    try:
        assert internal_auth.requester_meta() == {"requester": {"username": "alice", "email": "a@x.com"}}
        assert "X-Requester-Uid" not in internal_auth.outbound_headers()
    finally:
        internal_auth.reset_requester(token)


def test_a_uid_alone_makes_the_requester_truthy():
    assert Requester(uid="u-1")
    assert not Requester()
    assert Requester.from_headers({"X-Requester-Uid": 5}) == Requester()  # non-strings are ignored
```

(Use the file's existing imports for `internal_auth` and `Requester`; add them if missing.)

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `apps/ai_agent`): `<venv>/python -m pytest tests/test_internal_auth.py -q -p no:cacheprovider`
Expected: FAIL (`Requester` takes no `uid`).

- [ ] **Step 3: Implement**

In `apps/ai_agent/src/core/internal_auth.py`:
- add `REQUESTER_UID_HEADER = "X-Requester-Uid"` after `REQUESTER_EMAIL_HEADER`;
- `Requester` gets a third field `uid: str = ""`;
- `from_headers`: read `uid = headers.get(REQUESTER_UID_HEADER, "")` and return `cls(username if ..., email if ..., uid if isinstance(uid, str) else "")` (keep the existing string checks for the first two);
- `__bool__` returns `bool(self.username or self.email or self.uid)`;
- `requester_meta()`: build `{"username": requester.username, "email": requester.email}`; if `requester.uid` add `["uid"] = requester.uid`; return `{REQUESTER_META_KEY: that}`;
- `outbound_headers()`: after the email line add `if requester.uid: headers[REQUESTER_UID_HEADER] = requester.uid`.
- Update the module docstring sentence about identity to mention the uid.

- [ ] **Step 4: Run the tests**

Run: `<venv>/python -m pytest tests/test_internal_auth.py -q -p no:cacheprovider`, then the whole `ai_agent` suite. Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/ai_agent/src/core/internal_auth.py apps/ai_agent/tests/test_internal_auth.py
git commit -m "feat(ai-agent): carry the requester uid in headers and _meta"
```

---

### Task 3: ember_api account `uid` column and migration

**Files:**
- Modify: `apps/Ember/ember_api/src/models/account.py`, `apps/Ember/ember_api/tests/test_migrations.py`
- Create: `apps/Ember/ember_api/migrations/versions/0011_account_uid.py`, `apps/Ember/ember_api/tests/test_account_uid.py`

**Interfaces:**
- Produces: `Account.uid: str` (32 hex characters, set by default on creation); migration `0011` (down revision `0010`); the named unique index `ix_accounts_uid`.

Note: the code in this task was prototyped and its migration tests were run in a scratch copy before this plan was written (19 migration tests passed). It uses a **named unique index**, not a column `unique=True`, because SQLite cannot drop a UNIQUE column and the migration tests rebuild older schemas by dropping later columns. This differs from the spec's "unique column" wording on purpose.

- [ ] **Step 1: Write the failing tests**

Create `apps/Ember/ember_api/tests/test_account_uid.py`:

```python
"""Account.uid: created with the account, never changes, never leaves the server."""

from __future__ import annotations

import re
import sqlite3
from contextlib import closing

from fastapi.testclient import TestClient

from tests.conftest import FakeEmailSender
from tests.test_admin import make_member
from tests.test_registration import as_admin


def uids(client: TestClient) -> dict[str, str]:
    path = client.app.state.settings.database_path
    with closing(sqlite3.connect(path)) as conn:
        return dict(conn.execute("SELECT username, uid FROM accounts"))


def test_every_account_gets_its_own_32_hex_uid(client: TestClient, email: FakeEmailSender) -> None:
    make_member(client, email, "alice")
    make_member(client, email, "bob")

    found = uids(client)

    assert set(found) == {"root", "alice", "bob"}
    assert all(re.fullmatch(r"[0-9a-f]{32}", uid) for uid in found.values())
    assert len(set(found.values())) == 3


def test_the_uid_survives_a_rename_and_a_role_change(client: TestClient, email: FakeEmailSender) -> None:
    alice = make_member(client, email, "alice")
    as_admin(client)
    before = uids(client)["alice"]

    assert client.patch(f"/api/admin/accounts/{alice}", json={"username": "alicia"}).status_code == 200
    viewer = client.post("/api/admin/roles", json={"name": "Viewer"}).json()
    assert client.put(f"/api/admin/accounts/{alice}/roles/{viewer['id']}").status_code == 200

    assert uids(client)["alicia"] == before


def test_the_uid_is_never_returned_by_the_api(client: TestClient, email: FakeEmailSender) -> None:
    make_member(client, email, "alice")
    as_admin(client)
    secret = uids(client)["alice"]

    for path in ("/api/admin/accounts", "/api/auth/me"):
        body = client.get(path).text
        assert secret not in body
        assert '"uid"' not in body
```

In `apps/Ember/ember_api/tests/test_migrations.py` make exactly these changes (all verified in the prototype):
1. `HEAD = "0010"` becomes `HEAD = "0011"`, and `NEXT = "0011"` becomes `NEXT = "0012"`.
2. After those constants add:

```python
def drop_account_uid(conn: sqlite3.Connection) -> None:
    """Undo migration 0011 on a database built from the current models."""
    conn.execute("DROP INDEX ix_accounts_uid")
    conn.execute("ALTER TABLE accounts DROP COLUMN uid")
```

3. In `test_permission_split_preserves_access_once_and_keeps_revocations`, right after the line `conn.execute("UPDATE alembic_version SET version_num = '0009'")` add `drop_account_uid(conn)`.
4. In `TestDatabaseFromBeforeMigrations.build_legacy`, after the `ALTER TABLE accounts DROP COLUMN prompt_suggestions` line add `drop_account_uid(conn)  # likewise`.
5. In `test_it_is_only_stamped_when_the_baseline_is_the_newest_revision`, add `"0011*"` to the `ignore_patterns(...)` list after `"0010*"`.
6. In the `scripts_with_a_new_migration` fixture rename the throwaway file to `0012_add_nickname.py` and change its text to `revision = "0012"` and `down_revision = "0011"`.
7. In `TestLaterMigration.build_at_baseline`, the raw INSERT must include a uid: change it to
   `"INSERT INTO accounts (uid, username, email, password_hash, is_protected, is_active, email_verified, created_at)"` / `" VALUES ('0123456789abcdef0123456789abcdef', 'lex', 'lex@example.com', 'x', 0, 1, 1, '2026-01-01 00:00:00')"`.
8. In `test_a_legacy_database_is_stamped_then_upgraded_after_a_backup` (the second legacy builder), after the `ALTER TABLE accounts DROP COLUMN prompt_suggestions` line add `drop_account_uid(conn)  # likewise`.
9. Add this test before `class TestFreshDatabase:`:

```python
def test_account_uid_is_backfilled_unique_and_removed_by_the_downgrade(tmp_path: Path) -> None:
    run_with(make_database(tmp_path))
    path = tmp_path / "ember.db"
    with closing(sqlite3.connect(path)) as conn:
        drop_account_uid(conn)
        conn.execute("UPDATE alembic_version SET version_num = '0010'")
        for name in ("lex", "sam"):
            conn.execute(
                "INSERT INTO accounts (username, email, password_hash, is_protected, is_active, email_verified, created_at)"
                f" VALUES ('{name}', '{name}@example.com', 'x', 0, 1, 1, '2026-01-01 00:00:00')"
            )
        conn.commit()

    assert run_with(make_database(tmp_path)) == "upgraded"

    with closing(sqlite3.connect(path)) as conn:
        uids = [row[0] for row in conn.execute("SELECT uid FROM accounts ORDER BY id")]
        assert len(uids) == 2 and len(set(uids)) == 2
        assert all(len(uid) == 32 and int(uid, 16) >= 0 for uid in uids)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO accounts (uid, username, email, password_hash, is_protected, is_active, email_verified, created_at)"
                f" VALUES ('{uids[0]}', 'dup', 'dup@example.com', 'x', 0, 1, 1, '2026-01-01 00:00:00')"
            )

    from alembic import command

    async def downgrade() -> None:
        database = make_database(tmp_path)
        runner = MigrationRunner(database.engine)
        try:
            async with database.engine.begin() as conn:
                await conn.run_sync(lambda sync: command.downgrade(runner._config(sync), "0010"))
        finally:
            await database.dispose()

    asyncio.run(downgrade())

    assert revision_of(path) == "0010"
    with closing(sqlite3.connect(path)) as conn:
        assert "uid" not in {row[1] for row in conn.execute("PRAGMA table_info(accounts)")}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `apps/Ember/ember_api`): `<venv>/python -m pytest tests/test_migrations.py tests/test_account_uid.py -q -p no:cacheprovider`
Expected: FAIL (no `uid` column, `ix_accounts_uid` missing).

- [ ] **Step 3: Implement the model and migration**

`apps/Ember/ember_api/src/models/account.py`: add `import uuid` above `from datetime import datetime`; change the sqlalchemy import to `from sqlalchemy import Index, String, true`; in `class Account` right after `__tablename__ = "accounts"` add

```python
    # A named unique index (not a column constraint) so a test can rebuild an older schema: SQLite cannot drop a UNIQUE column.
    __table_args__ = (Index("ix_accounts_uid", "uid", unique=True),)
```

and right after the `id` column add

```python
    # A stable id that never changes or repeats (unlike the username); internal only.
    uid: Mapped[str] = mapped_column(String(32), default=lambda: uuid.uuid4().hex)
```

Create `apps/Ember/ember_api/migrations/versions/0011_account_uid.py`:

```python
"""accounts.uid: a stable id that never changes or repeats.

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("accounts") as batch:
        batch.add_column(sa.Column("uid", sa.String(32), nullable=True))
    conn = op.get_bind()
    for (account_id,) in conn.execute(sa.text("SELECT id FROM accounts")).fetchall():
        conn.execute(sa.text("UPDATE accounts SET uid = :uid WHERE id = :id"), {"uid": uuid.uuid4().hex, "id": account_id})
    with op.batch_alter_table("accounts") as batch:
        batch.alter_column("uid", existing_type=sa.String(32), nullable=False)
        batch.create_index("ix_accounts_uid", ["uid"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("accounts") as batch:
        batch.drop_index("ix_accounts_uid")
        batch.drop_column("uid")
```

- [ ] **Step 4: Run the tests**

Run: `<venv>/python -m pytest tests/test_migrations.py tests/test_account_uid.py -q -p no:cacheprovider`
Expected: all PASS (19 migration tests plus the 3 new ones). Then run `tests/test_registration.py tests/test_admin.py tests/test_import_chat_app.py` (about 70 s): no failures. If `test_the_migrations_match_the_models_exactly` fails, print its differences and fix the model or migration (not the test).

- [ ] **Step 5: Commit**

```bash
git add apps/Ember/ember_api/src/models/account.py apps/Ember/ember_api/migrations/versions/0011_account_uid.py apps/Ember/ember_api/tests/test_migrations.py apps/Ember/ember_api/tests/test_account_uid.py
git commit -m "feat(ember-api): immutable account uid with migration 0011"
```

---

### Task 4: ember_api sends the uid to ai_agent and mcp_server

**Files:**
- Modify: `apps/Ember/ember_api/src/services/agent_gateway.py`, `mcp_session.py`, `mcp_proxy.py`, `agent_admin.py`, `mcp_server_info.py`, `server_tools.py`, `src/routes/chats.py`, `src/routes/server_info.py`, `src/routes/user_extensions.py`
- Test: `apps/Ember/ember_api/tests/test_mcp_proxy.py`, `test_agent_admin.py`, `test_agent_gateway.py`, `test_download.py`

**Interfaces:**
- Consumes (Task 3): `Account.uid`.
- Produces: `Caller(username, email, uid="")`; `identity_headers(username, email, internal_token, uid="")`; the header `X-Requester-Uid` on every proxied or gateway call made for an account.

- [ ] **Step 1: Write the failing tests**

- `tests/test_mcp_proxy.py::test_initialize_is_forwarded_with_identity_and_session_id`: add after the email assertion
  `assert re.fullmatch(r"[0-9a-f]{32}", sent.headers["x-requester-uid"])` (add `import re` if missing).
- `tests/test_mcp_proxy.py::test_browser_cannot_forge_identity_or_leak_its_cookie`: add `"X-Requester-Uid": "forged"` to the forged headers and assert `sent.headers["x-requester-uid"] != "forged"`.
- `tests/test_agent_admin.py::test_admin_lists_creates_updates_and_deletes`: after `assert sent.headers["x-requester-username"] == "root"` add `assert len(sent.headers["x-requester-uid"]) == 32`.
- `tests/test_download.py` near line 73 (after the `x-requester-username` assertion): add `assert len(sent.headers["x-requester-uid"]) == 32`.
- `tests/test_agent_gateway.py`: change `CALLER` to `Caller(username="alice", email="alice@example.com", uid="uid-alice")`; in `_build_agent` next to `seen["username"] = ...` add `seen["uid"] = headers.get("x-requester-uid")`; change the assertion at line ~154 to `assert result["seen"] == {"username": "alice", "uid": "uid-alice", "token": "s3cret"}`. Grep `result["seen"]` in the same file and update any other equality on that dict the same way.
- `tests/test_email_service.py` needs no change: the internal "ember" identity has no uid, so its header dict stays as asserted.

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `apps/Ember/ember_api`): `<venv>/python -m pytest tests/test_mcp_proxy.py tests/test_agent_admin.py tests/test_download.py tests/test_agent_gateway.py -q -p no:cacheprovider`
Expected: FAIL (`KeyError: 'x-requester-uid'`, `Caller` has no `uid`).

- [ ] **Step 3: Implement**

- `services/mcp_session.py`:

```python
def identity_headers(username: str, email: str, internal_token: str | None, uid: str = "") -> dict[str, str]:
    headers = {"X-Requester-Username": username, "X-Requester-Email": email}
    if uid:
        headers["X-Requester-Uid"] = uid
    if internal_token:
        headers["X-Internal-Token"] = internal_token
    return headers
```

- `services/agent_gateway.py`: `Caller` gets `uid: str = ""` after `email`; `McpAgentGateway._headers` returns `identity_headers(caller.username, caller.email, self._internal_token, caller.uid)`.
- `services/server_tools.py` (line ~40): `identity_headers(caller.username, caller.email, self._internal_token, caller.uid)`.
- `services/mcp_proxy.py::_upstream_headers`, `services/agent_admin.py::_headers`, `services/mcp_server_info.py::_headers`: add `headers["X-Requester-Uid"] = account.uid` right after the email header line.
- The three `Caller(...)` constructions pass the uid: `routes/chats.py::_caller` (`Caller(username=account.username, email=account.email, uid=account.uid)`), `routes/user_extensions.py::_caller` (same) and `routes/server_info.py` line ~195 (same).
- Do not change `services/email_service.py` or `services/emberlings_gateway.py`.

- [ ] **Step 4: Run the tests**

Run the four test files again: all PASS. Then run the whole `ember_api` suite in the background (about 8 minutes): no failures; compare the pass count with the Task 3 result plus none added here.

- [ ] **Step 5: Commit**

```bash
git add apps/Ember/ember_api/src apps/Ember/ember_api/tests
git commit -m "feat(ember-api): send the account uid to ai_agent and mcp_server"
```

---

### Task 5: ember_api purges memory when an account is deleted

**Files:**
- Create: `apps/Ember/ember_api/src/services/memory_purger.py`, `apps/Ember/ember_api/tests/test_memory_purge.py`
- Modify: `apps/Ember/ember_api/src/deps.py`, `apps/Ember/ember_api/src/app.py`, `apps/Ember/ember_api/src/routes/admin.py`

**Interfaces:**
- Consumes: `Account.uid` (Task 3); the `mcp_server` route (Task 1); `services.mcp_server_info.base_url`.
- Produces: `MemoryPurger(client, mcp_url, internal_token).purge(uid) -> bool` (never raises); `deps.get_memory_purger`; `app.state.memory_purger`.

- [ ] **Step 1: Write the failing tests**

Create `apps/Ember/ember_api/tests/test_memory_purge.py`:

```python
"""Deleting an account tells mcp_server to delete its memory notes (best effort)."""

from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from tests.conftest import ADMIN_USERNAME, FakeEmailSender, FakeUpstream
from tests.test_account_uid import uids
from tests.test_admin import make_member
from tests.test_registration import as_admin


def purges(upstream: FakeUpstream) -> list[httpx.Request]:
    return [r for r in upstream.requests if r.method == "DELETE" and r.url.path.startswith("/memory/owners/")]


def test_deleting_an_account_purges_its_notes_once(client: TestClient, email: FakeEmailSender, upstream: FakeUpstream) -> None:
    alice = make_member(client, email, "alice")
    as_admin(client)
    uid = uids(client)["alice"]
    upstream.requests.clear()

    assert client.delete(f"/api/admin/accounts/{alice}").status_code == 204

    sent = purges(upstream)
    assert [r.url.path for r in sent] == [f"/memory/owners/{uid}"]
    assert "x-internal-token" not in sent[0].headers  # none configured in this test


def test_the_internal_token_is_sent_when_configured(client_factory, email: FakeEmailSender, upstream: FakeUpstream) -> None:
    client = client_factory(internal_token="secret-token")
    alice = make_member(client, email, "alice")
    as_admin(client)
    upstream.requests.clear()

    assert client.delete(f"/api/admin/accounts/{alice}").status_code == 204

    assert purges(upstream)[0].headers["x-internal-token"] == "secret-token"


def test_a_failing_purge_never_blocks_the_deletion(client: TestClient, email: FakeEmailSender, upstream: FakeUpstream) -> None:
    alice = make_member(client, email, "alice")
    as_admin(client)
    upstream.handler = lambda request: httpx.Response(500, json={"error": "boom"})

    assert client.delete(f"/api/admin/accounts/{alice}").status_code == 204
    assert "alice" not in uids(client)


def test_an_unreachable_mcp_server_never_blocks_the_deletion(client: TestClient, email: FakeEmailSender, upstream: FakeUpstream) -> None:
    alice = make_member(client, email, "alice")
    as_admin(client)
    upstream.unreachable = True

    assert client.delete(f"/api/admin/accounts/{alice}").status_code == 204
    assert "alice" not in uids(client)


def test_a_refused_deletion_does_not_purge(client: TestClient, upstream: FakeUpstream) -> None:
    as_admin(client)
    root_id = next(a["id"] for a in client.get("/api/admin/accounts").json() if a["username"] == ADMIN_USERNAME)
    upstream.requests.clear()

    assert client.delete(f"/api/admin/accounts/{root_id}").status_code == 409  # protected and your own account
    assert purges(upstream) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `apps/Ember/ember_api`): `<venv>/python -m pytest tests/test_memory_purge.py -q -p no:cacheprovider`
Expected: FAIL (`purges(upstream)` is empty: nothing is called yet).

- [ ] **Step 3: Implement**

Create `apps/Ember/ember_api/src/services/memory_purger.py`:

```python
"""Tells mcp_server to delete a deleted account's memory notes.

Best effort: a failed purge must never block or undo the account deletion.
Leftover notes are harmless to other users (a uid is never reused), but
they linger, so the caller logs a failure.
"""

from __future__ import annotations

import logging
from urllib.parse import quote

import httpx

from src.services.mcp_server_info import base_url

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(5.0)


class MemoryPurger:
    def __init__(self, client: httpx.AsyncClient, mcp_url: str, internal_token: str | None) -> None:
        self._client = client
        self._base = base_url(mcp_url)
        self._internal_token = internal_token

    async def purge(self, uid: str) -> bool:
        """DELETE /memory/owners/<uid> on mcp_server. True only when it confirmed; never raises."""
        if not uid:
            return False
        headers = {"X-Internal-Token": self._internal_token} if self._internal_token else {}
        try:
            response = await self._client.delete(
                f"{self._base}/memory/owners/{quote(uid, safe='')}", headers=headers, timeout=_TIMEOUT
            )
        except httpx.HTTPError as error:
            logger.warning("memory purge request failed: %s", error)
            return False
        if response.status_code >= 400:
            logger.warning("memory purge was refused with status %s", response.status_code)
            return False
        return True
```

`src/app.py`: import `from src.services.memory_purger import MemoryPurger` with the other service imports and, after the `app.state.mcp_proxy = ...` line, add
`app.state.memory_purger = MemoryPurger(upstream, settings.mcp_server_url, internal_token or None)`.

`src/deps.py`: add (next to `get_emberlings`, with the matching import):

```python
def get_memory_purger(request: Request) -> MemoryPurger:
    return request.app.state.memory_purger
```

`src/routes/admin.py`: import `get_memory_purger` (in the existing `from src.deps import (...)` list) and `from src.services.memory_purger import MemoryPurger`; change `delete_account` to

```python
async def delete_account(
    account_id: int,
    admin: Account = Depends(require_accounts_delete),
    admin_service: AdminService = Depends(get_admin_service),
    logs: LogWriter = Depends(get_log_writer),
    purger: MemoryPurger = Depends(get_memory_purger),
) -> Response:
    try:
        target = await admin_service.account(account_id)
        username = target.username
        uid = target.uid
        await admin_service.delete_account(admin, target)
    except AdminError as error:
        raise _http_error(error) from error
    if not await purger.purge(uid):
        await logs.error(
            admin.id, "admin.memory_purge", f"Memory notes of deleted account '{username}' were not purged (mcp_server did not confirm)"
        )
    await logs.action(admin, "admin.delete_account", f"Deleted account '{username}'")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 4: Run the tests**

Run `tests/test_memory_purge.py tests/test_admin.py -q -p no:cacheprovider`: all PASS. Then the whole `ember_api` suite in the background: no failures.

- [ ] **Step 5: Commit**

```bash
git add apps/Ember/ember_api/src apps/Ember/ember_api/tests/test_memory_purge.py
git commit -m "feat(ember-api): purge an account's memory notes when it is deleted"
```

---

### Task 6: Docs and TODO

**Files:**
- Modify: `apps/mcp_server/src/capabilities/memory/README.md`, `apps/mcp_server/src/capabilities/memory/STATIC-GUIDELINES.md`, `_TODO.md`

**Interfaces:** none.

- [ ] **Step 1: Update the README**

In `README.md`:
- Intro (line 3): replace "Notes belong to the user named in the request's identity (never a tool parameter; see Rules for how far that can be trusted)" with "Notes belong to the account whose stable uid is in the request's identity (never a tool parameter; see Rules for how far that can be trusted)".
- In `## Rules` replace the bullet starting "Ownership is keyed on the username only." with:
  "- Notes are keyed on the account's stable `uid` (a random id ember_api creates with the account; it never changes and is never reused), so renaming an account keeps its notes. When ember_api deletes an account it asks this server to delete that account's notes (`DELETE /memory/owners/{uid}`, internal token required). The purge is best effort: if `mcp_server` is down, no `INTERNAL_API_TOKEN` is set, or memory is offline, the notes stay behind. That is harmless for other users (a uid is never reused) but the data lingers."
- Replace the bullet starting "Privacy is only as strong as the caller is trusted." with:
  "- Privacy is only as strong as the caller is trusted. The uid, like the username before it, is whatever the caller asserts (the `X-Requester-Uid` header or `_meta.requester.uid`), so notes are private only as far as the caller is trusted. Set `INTERNAL_API_TOKEN` whenever the server listens on a non-loopback address (`zima_host.yaml` binds 0.0.0.0). A caller that sends no uid (a direct MCP client) is refused."
- Replace the bullet "The number of distinct usernames is not capped; only 200 notes x 500 characters per username." with "The number of distinct uids is not capped; only 200 notes x 500 characters per uid."

- [ ] **Step 2: Update STATIC-GUIDELINES.md**

Replace its last bullet (the one starting "Notes are keyed on the username only") with:
"- Notes are keyed on the account uid, not the username, so a rename keeps them and a reused username inherits nothing. Deleting an account triggers a best-effort purge through `DELETE /memory/owners/{uid}` (needs the internal token); a failed purge leaves orphaned notes that nothing reads. The uid is whatever the caller asserts: set `INTERNAL_API_TOKEN` whenever the server listens on a non-loopback address. Distinct uids are not capped (only 200 notes x 500 characters each)."
Also change `notes` table description wording from "owner" to "owner (the account uid)" where the table columns are listed.

- [ ] **Step 3: Update the TODO**

In `_TODO.md`, item 6's "Follow-ups" list:
- Mark follow-up 1 as done: `1. **Done** (<hashes from git log>): notes are keyed on a stable account uid and purged when an account is deleted (spec docs/superpowers/specs/2026-10-10-memory-owner-uid-design.md).`
- Keep follow-ups 2, 3 and 4 unchanged.
- Add `5. Retry or periodically sweep failed memory purges (a purge is best effort today: orphaned notes stay when mcp_server was unreachable or had no token).`

- [ ] **Step 4: Check and commit**

Re-read the README rules once against `tool.py` and `memory_routes.py` for accuracy (route path, 401/404 behaviour, token). Run the `mcp_server` suite once (about 30 s): no failures. Grep the memory folder, the docs you edited and `src/memory_routes.py` for the word `username` and confirm every remaining use is intentional.

```bash
git add apps/mcp_server/src/capabilities/memory/README.md apps/mcp_server/src/capabilities/memory/STATIC-GUIDELINES.md _TODO.md
git commit -m "docs: memory is keyed on the account uid; purge on delete"
```

---

## Self-Review (done while writing)

- **Spec coverage:** uid column and migration (Task 3); header and `_meta` carrying (Tasks 2 and 4, `ember_api`'s three `Caller` sites, proxy, admin and info clients); `current_uid()` and middleware (Task 1); memory keyed on uid and refusal text (Task 1); `purge_owner`, the route and `run.py` install (Task 1); the `ember_api` purger and delete hook, best effort with `logs.error` (Task 5); no forwarding to extensions pinned by a test (Task 1); docs and TODO (Task 6). Not built, as the spec says: ember_web or chat_cli changes, retry or sweep, Emberlings uid, refusing on empty token.
- **Differences from the spec, on purpose:** the uid uniqueness is a named unique index (`ix_accounts_uid`), not a column `unique=True` (the migration tests rebuild old schemas by dropping later columns and SQLite cannot drop a UNIQUE column; verified in a prototype). `requester_meta()` adds `uid` only when non-empty so existing callers and tests keep their shape.
- **Placeholders:** none. Commit hashes in Task 6 Step 3 come from `git log` at execution time.
- **Type consistency:** `current_uid`, `purge_owner`, `memory_routes.install_memory_routes`, `Requester.uid`, `REQUESTER_UID_HEADER`, `Caller.uid`, `identity_headers(..., uid)`, `MemoryPurger.purge`, `get_memory_purger`, `Account.uid` and the index name `ix_accounts_uid` are spelled identically in every task.
- **Risks to watch while executing:** the `ember_api` migration tests (Task 3) are the most fragile part; the prototype passed 19 tests, so a failure there means a typo in copying the edits, not a design problem. Task 5's last test depends on what `as_admin` returns and on the status code for deleting your own account; the task tells the implementer to read both and adjust the test, not the code.
