# Merged Network-Gate / Login Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge `chat_app`'s network-level Basic Auth gate with per-user login so a real account's own credentials satisfy both in one prompt, and add temporary "gate codes" as a no-account way through the gate.

**Architecture:** `security.check_auth()` currently treats "is the gate on" and "does this pass it" as one question (`CHAT_AUTH_USER`/`PASSWORD` configured or not). This plan splits that into a new `auth.service.network_gate_enabled()` (three-way OR: shared pair configured, a live gate code exists, or `CHAT_NETWORK_ACCESS_ENABLED` is set) and a rewritten `check_auth()` that, once the gate is on, checks Basic Auth against three paths in order: the shared pair (unchanged), a real account's credentials (which also calls `service.login()` immediately - the "one prompt" merge), or a gate code (password field only, no session). Gate codes get their own `gate_codes` SQLite table in `auth/store.py`, mirroring `invite_codes`' HMAC-hash approach, plus admin (Account manager tab) and self-service (sidebar quick-action) minting UI.

**Tech Stack:** Flask, sqlite3 (stdlib, no ORM), Jinja2 templates, vanilla JS - all matching the existing `chat_app` stack, no new dependencies.

**Spec:** [docs/superpowers/specs/2026-08-17-merged-network-login-design.md](../specs/2026-08-17-merged-network-login-design.md)

## Global Constraints

- Scope is `chat_app` only. `mcp_server` is not touched.
- `gate_codes.expires_at` is `NOT NULL` - unlike `invite_codes.expires_at`, a gate code always has an expiry.
- Gate code TTL choices in every UI dropdown: 1 hour / 24 hours / 7 days. No "never expires" option.
- No new permission scope. Admin-facing gate-code endpoints (`account.create_gate_code_api`, `account.delete_gate_code_api`) join the existing `"accounts"` scope, exactly like `account.create_invite_api`/`account.delete_invite_api` do today. The self-service endpoint (`auth.create_gate_code`) joins the existing `"invites"` scope, exactly like `auth.create_invite` does today.
- A gate code is multi-use for its whole window (no claim/consume-on-first-use logic) and not tied to any username - Basic Auth's password field is checked, the username field is ignored.
- Once `network_gate_enabled()` is true, Basic Auth is required on **every** request, including from loopback and including one that already carries a valid session cookie - unchanged from today's existing behavior when `CHAT_AUTH_USER`/`PASSWORD` is configured (`check_auth` runs before `check_login` on every request, unconditionally). Minting a gate code therefore switches this on immediately for everyone, including the admin who minted it - the spec calls this out explicitly as an accepted "deliberate act," same reasoning as configuring `CHAT_AUTH_USER`/`PASSWORD` today.
- `mcp_server` has no login concept and `auth/permissions.py`'s `SCOPES`/`ROLE_RANK`/executive tier are untouched.

---

### Task 1: `auth/store.py` - the `gate_codes` table and its CRUD

**Files:**
- Modify: `chat_app/src/chat_app/auth/store.py`
- Test: `chat_app/tests/test_auth_store.py`

**Interfaces:**
- Produces: `store.UnknownGateCode` (exception), `store.IssuedGateCode` (frozen dataclass: `code_id: str`, `code: str`, `created_by: str`, `created_at: str`, `expires_at: str`), `store.create_gate_code(db_path: Path, created_by: str, ttl_hours: float) -> IssuedGateCode`, `store.list_gate_codes(db_path: Path) -> list[dict]` (each dict: `code_id`, `created_by`, `created_at`, `expires_at`), `store.gate_code_is_valid(db_path: Path, code: str) -> bool`, `store.delete_gate_code(db_path: Path, code_id: str) -> None`, `store.any_gate_code_valid(db_path: Path) -> bool`. Task 2 (`auth/service.py`) consumes `any_gate_code_valid` and `gate_code_is_valid`; Task 4/5 (route handlers) consume the rest.

- [ ] **Step 1: Write the failing tests**

Append to `chat_app/tests/test_auth_store.py` (after the existing `# --- invite listing ---` section, at the end of the file):

```python
# --- gate codes --------------------------------------------------------


def _gate_code(db_path, created_by="admin", ttl_hours=1):
    return store.create_gate_code(db_path, created_by=created_by, ttl_hours=ttl_hours)


def test_create_gate_code_is_valid_immediately(db_path):
    issued = _gate_code(db_path)

    assert store.gate_code_is_valid(db_path, issued.code) is True


def test_wrong_gate_code_is_not_valid(db_path):
    _gate_code(db_path)

    assert store.gate_code_is_valid(db_path, "not-the-code") is False


def test_gate_code_is_multi_use(db_path):
    """Unlike an invite code, a gate code stays valid across many uses for
    its whole window - there's no claim/race logic, since it isn't tied to
    any one account."""
    issued = _gate_code(db_path)

    assert store.gate_code_is_valid(db_path, issued.code) is True
    assert store.gate_code_is_valid(db_path, issued.code) is True


def test_expired_gate_code_is_not_valid(db_path):
    issued = _gate_code(db_path, ttl_hours=1)
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    conn.execute("UPDATE gate_codes SET expires_at = ? WHERE code_id = ?", (past, issued.code_id))
    conn.commit()
    conn.close()

    assert store.gate_code_is_valid(db_path, issued.code) is False


def test_list_gate_codes_excludes_and_purges_expired_rows(db_path):
    issued = _gate_code(db_path, ttl_hours=1)
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    conn.execute("UPDATE gate_codes SET expires_at = ? WHERE code_id = ?", (past, issued.code_id))
    conn.commit()
    conn.close()

    assert store.list_gate_codes(db_path) == []

    # Purged outright, not just filtered - a direct query confirms the
    # row itself is gone, mirroring how invite_codes has no lazy-GC
    # precedent to compare against but delete_role's expired-invite path
    # already relies on the same "expired rows don't linger forever" idea.
    conn = sqlite3.connect(str(db_path))
    remaining = conn.execute("SELECT 1 FROM gate_codes").fetchone()
    conn.close()
    assert remaining is None


def test_list_gate_codes_includes_active_rows(db_path):
    issued = _gate_code(db_path, created_by="root-admin")

    [row] = store.list_gate_codes(db_path)

    assert row["code_id"] == issued.code_id
    assert row["created_by"] == "root-admin"
    assert row["expires_at"] == issued.expires_at


def test_delete_gate_code_revokes_it_immediately(db_path):
    issued = _gate_code(db_path)

    store.delete_gate_code(db_path, issued.code_id)

    assert store.gate_code_is_valid(db_path, issued.code) is False
    assert store.list_gate_codes(db_path) == []


def test_delete_gate_code_with_unknown_id_raises(db_path):
    with pytest.raises(store.UnknownGateCode):
        store.delete_gate_code(db_path, "not-a-real-code-id")


def test_any_gate_code_valid_reports_true_only_while_unexpired(db_path):
    assert store.any_gate_code_valid(db_path) is False

    issued = _gate_code(db_path, ttl_hours=1)
    assert store.any_gate_code_valid(db_path) is True

    import sqlite3

    conn = sqlite3.connect(str(db_path))
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    conn.execute("UPDATE gate_codes SET expires_at = ? WHERE code_id = ?", (past, issued.code_id))
    conn.commit()
    conn.close()
    assert store.any_gate_code_valid(db_path) is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `chat_app/`): `pytest tests/test_auth_store.py -v -k gate_code`
Expected: FAIL - `AttributeError: module 'chat_app.auth.store' has no attribute 'create_gate_code'` (and similarly for the other new names).

- [ ] **Step 3: Implement the `gate_codes` table and its CRUD**

In `chat_app/src/chat_app/auth/store.py`, add a new exception near the existing ones (after `class UnknownInvite(Exception):`):

```python
class UnknownGateCode(Exception):
    """Raised by delete_gate_code() when the code_id doesn't exist."""
```

In `_connect()`, add the table right after the `invite_codes` table creation block (after its closing `)` and before `now = datetime.now(timezone.utc).isoformat()`):

```python
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS gate_codes (
            code_id TEXT PRIMARY KEY,
            salt BLOB NOT NULL,
            code_hash BLOB NOT NULL,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )
        """
    )
```

Still in `_connect()`, register a second SQL function name for the same HMAC comparison, right after the existing `conn.create_function("invite_code_matches", ...)` line:

```python
    # Same HMAC-SHA256 comparison as invite codes (see _invite_code_matches)
    # registered under its own SQL name so gate_code_is_valid's query reads
    # naturally - a gate code isn't an invite, even though the hashing
    # approach is identical.
    conn.create_function("gate_code_matches", 3, _invite_code_matches, deterministic=True)
```

At the end of the file, add a new section after the `# --- invite codes ---` section's last function (`register_user`):

```python
# --- gate codes ----------------------------------------------------------


@dataclass(frozen=True)
class IssuedGateCode:
    """What create_gate_code() hands back. ``code`` exists here and
    nowhere else - only its salted HMAC is stored, same as IssuedInvite."""

    code_id: str
    code: str
    created_by: str
    created_at: str
    expires_at: str


def create_gate_code(db_path: Path, created_by: str, ttl_hours: float) -> IssuedGateCode:
    conn = _connect(db_path)
    try:
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        expires_at = (now + timedelta(hours=ttl_hours)).isoformat()
        code = secrets.token_urlsafe(9)
        code_id = secrets.token_urlsafe(12)
        salt = secrets.token_bytes(16)
        conn.execute(
            "INSERT INTO gate_codes (code_id, salt, code_hash, created_by, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (code_id, salt, _hash_invite_code(salt, code), created_by, now_iso, expires_at),
        )
        conn.commit()
    finally:
        conn.close()
    return IssuedGateCode(code_id=code_id, code=code, created_by=created_by, created_at=now_iso, expires_at=expires_at)


def list_gate_codes(db_path: Path) -> list[dict]:
    """Still-valid gate codes, never the plaintext. Opportunistically
    deletes expired rows first - lazy GC, no cron needed, so the table
    doesn't grow unbounded from codes nobody ever revoked."""
    conn = _connect(db_path)
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("DELETE FROM gate_codes WHERE expires_at <= ?", (now,))
        conn.commit()
        rows = conn.execute(
            "SELECT code_id, created_by, created_at, expires_at FROM gate_codes ORDER BY created_at DESC"
        ).fetchall()
    finally:
        conn.close()
    return [
        {"code_id": code_id, "created_by": created_by, "created_at": created_at, "expires_at": expires_at}
        for code_id, created_by, created_at, expires_at in rows
    ]


def gate_code_is_valid(db_path: Path, code: str) -> bool:
    conn = _connect(db_path)
    try:
        now = datetime.now(timezone.utc).isoformat()
        row = conn.execute(
            "SELECT 1 FROM gate_codes WHERE expires_at > ? AND gate_code_matches(salt, code_hash, ?) LIMIT 1",
            (now, code),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def any_gate_code_valid(db_path: Path) -> bool:
    """Whether at least one gate code is currently valid - used by
    auth.service.network_gate_enabled() as one of the three activation
    signals ("an admin minting one is itself a deliberate act")."""
    conn = _connect(db_path)
    try:
        now = datetime.now(timezone.utc).isoformat()
        return conn.execute("SELECT 1 FROM gate_codes WHERE expires_at > ? LIMIT 1", (now,)).fetchone() is not None
    finally:
        conn.close()


def delete_gate_code(db_path: Path, code_id: str) -> None:
    """Manual revocation - rejected immediately after this, since
    gate_code_is_valid checks the live table on every call."""
    conn = _connect(db_path)
    try:
        deleted = conn.execute("DELETE FROM gate_codes WHERE code_id = ?", (code_id,)).rowcount
        conn.commit()
        if deleted == 0:
            raise UnknownGateCode(code_id)
    finally:
        conn.close()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_auth_store.py -v`
Expected: PASS, all tests including the pre-existing invite/role/user ones (regression check).

- [ ] **Step 5: Commit**

```bash
git add chat_app/src/chat_app/auth/store.py chat_app/tests/test_auth_store.py
git commit -m "feat: add gate_codes table and CRUD to auth/store.py"
```

---

### Task 2: `auth/service.py` - `network_gate_enabled()` and `gate_code_grants_access()`

**Files:**
- Modify: `chat_app/src/chat_app/auth/service.py`
- Test: `chat_app/tests/test_auth_service.py` (new file)

**Interfaces:**
- Consumes: `store.any_gate_code_valid(db_path) -> bool`, `store.gate_code_is_valid(db_path, code) -> bool` (Task 1).
- Produces: `service.network_gate_enabled() -> bool`, `service.gate_code_grants_access(code: str) -> bool`. Task 3 (`security.py`) consumes both.

- [ ] **Step 1: Write the failing tests**

Create `chat_app/tests/test_auth_service.py`:

```python
"""Unit tests for auth/service.py's network-gate helpers - see security.py's
check_auth for how these feed into the merged credential paths."""

from __future__ import annotations

import dataclasses
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from chat_app.auth import service, store
from chat_app.config import settings as base_settings


@pytest.fixture(autouse=True)
def no_signals(monkeypatch):
    """Default state: every activation signal off."""
    monkeypatch.delenv("CHAT_AUTH_USER", raising=False)
    monkeypatch.delenv("CHAT_AUTH_PASSWORD", raising=False)
    monkeypatch.delenv("CHAT_NETWORK_ACCESS_ENABLED", raising=False)


@pytest.fixture
def users_db(tmp_path, monkeypatch):
    """Same isolation approach as conftest.py's users_db fixture - points
    the module's own (frozen, import-time) settings reference at a fresh
    per-test SQLite file."""
    test_settings = dataclasses.replace(base_settings, users_db_path=tmp_path / "users.db")
    monkeypatch.setattr(service, "settings", test_settings)
    return test_settings.users_db_path


def test_gate_is_off_with_no_signal(users_db):
    assert service.network_gate_enabled() is False


def test_shared_pair_turns_the_gate_on(users_db, monkeypatch):
    monkeypatch.setenv("CHAT_AUTH_USER", "me")
    monkeypatch.setenv("CHAT_AUTH_PASSWORD", "s3cret")

    assert service.network_gate_enabled() is True


def test_half_configured_shared_pair_does_not_turn_the_gate_on(users_db, monkeypatch):
    monkeypatch.setenv("CHAT_AUTH_USER", "me")

    assert service.network_gate_enabled() is False


def test_network_access_enabled_env_var_turns_the_gate_on(users_db, monkeypatch):
    monkeypatch.setenv("CHAT_NETWORK_ACCESS_ENABLED", "1")

    assert service.network_gate_enabled() is True


def test_a_valid_gate_code_turns_the_gate_on(users_db):
    store.create_gate_code(users_db, created_by="admin", ttl_hours=1)

    assert service.network_gate_enabled() is True


def test_an_expired_gate_code_does_not_turn_the_gate_on(users_db):
    issued = store.create_gate_code(users_db, created_by="admin", ttl_hours=1)
    conn = sqlite3.connect(str(users_db))
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    conn.execute("UPDATE gate_codes SET expires_at = ? WHERE code_id = ?", (past, issued.code_id))
    conn.commit()
    conn.close()

    assert service.network_gate_enabled() is False


def test_gate_code_grants_access_checks_the_password_only(users_db):
    issued = store.create_gate_code(users_db, created_by="admin", ttl_hours=1)

    assert service.gate_code_grants_access(issued.code) is True
    assert service.gate_code_grants_access("wrong-code") is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_auth_service.py -v`
Expected: FAIL - `AttributeError: module 'chat_app.auth.service' has no attribute 'network_gate_enabled'`.

- [ ] **Step 3: Implement `network_gate_enabled()` and `gate_code_grants_access()`**

In `chat_app/src/chat_app/auth/service.py`, add these two functions after `can_anyone_log_in()`:

```python
def network_gate_enabled() -> bool:
    """Whether the network gate (security.check_auth) is switched on at
    all - kept separate from what satisfies it once active, because
    ADMIN_USERNAME/PASSWORD is mandatory in every deployment: if "an admin
    account exists" alone were enough, every deployment would become
    reachable off-loopback automatically. Three independent signals, any
    one of which switches it on:

    1. The shared CHAT_AUTH_USER/PASSWORD pair - read directly here
       (rather than importing security.configured_credentials, which
       would be a circular import: security already imports from this
       module) with the same both-or-neither treatment.
    2. At least one currently-valid gate code - an admin minting one is
       itself a deliberate act, same reasoning as configuring the pair.
    3. CHAT_NETWORK_ACCESS_ENABLED (any non-empty value) - the explicit
       "real accounts alone, no shared secret" opt-in.
    """
    if os.getenv("CHAT_AUTH_USER") and os.getenv("CHAT_AUTH_PASSWORD"):
        return True
    if store.any_gate_code_valid(settings.users_db_path):
        return True
    return bool(os.getenv("CHAT_NETWORK_ACCESS_ENABLED"))


def gate_code_grants_access(code: str) -> bool:
    return store.gate_code_is_valid(settings.users_db_path, code)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_auth_service.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add chat_app/src/chat_app/auth/service.py chat_app/tests/test_auth_service.py
git commit -m "feat: add network_gate_enabled and gate_code_grants_access to auth/service.py"
```

---

### Task 3: `security.py` - merge `check_auth` into three credential paths

**Files:**
- Modify: `chat_app/src/chat_app/security.py`
- Modify: `chat_app/tests/test_security.py`
- Modify: `chat_app/.env.example`
- Modify: `chat_app/zima_host.yaml`

**Interfaces:**
- Consumes: `service.network_gate_enabled()`, `service.gate_code_grants_access(code)` (Task 2), `service.check_credentials(username, password)` and `service.login(username)` (existing, from `auth/service.py`).
- Produces: rewritten `check_auth()` behavior that Task 4/5's manual/browser testing (not automated) will exercise end-to-end.

- [ ] **Step 1: Write the failing tests**

In `chat_app/tests/test_security.py`, first give the file's `client` fixture DB isolation (it doesn't have any today - see the fixture's own docstring, which only isolates login/admin env vars, not `settings.users_db_path`). Change:

```python
@pytest.fixture
def client(client, monkeypatch):
```

to:

```python
@pytest.fixture
def client(client, monkeypatch, users_db):
```

(`users_db` is the existing fixture from `conftest.py`; without it, the new real-account/gate-code credential paths added below would read/write the real, CWD-relative `data/users.db` as a side effect of running this test file.)

Then append a new section at the end of the file:

```python
# --- merged login (real accounts, gate codes) ---------------------------
#
# Unlike the sections above, these tests mostly use a FRESH, sessionless
# client (client.application.test_client()) rather than the file's shared
# `client` fixture - that fixture is already logged in via a session
# cookie, and once any of these tests switches the gate on, every
# subsequent request needs its own valid Basic Auth regardless of that
# cookie (check_auth runs before check_login, unconditionally - see
# check_auth's own docstring). A fresh client sidesteps having to reason
# about that ordering for each assertion.


def test_gate_stays_off_with_no_activation_signal(client):
    """Regression check for the byte-for-byte-unchanged-when-off
    guarantee - the two tests in the loopback-fallback section above
    already cover this implicitly, this one names it explicitly."""
    assert client.get("/api/providers", environ_base=REMOTE).status_code == 403


def test_network_access_enabled_env_var_switches_the_gate_on(client, monkeypatch):
    monkeypatch.setenv("CHAT_NETWORK_ACCESS_ENABLED", "1")

    response = client.get("/api/providers", environ_base=REMOTE)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith("Basic ")


def test_a_live_gate_code_switches_the_gate_on(client, users_db):
    from chat_app.auth import store

    store.create_gate_code(users_db, created_by="test-admin", ttl_hours=1)

    response = client.get("/api/providers", environ_base=REMOTE)

    assert response.status_code == 401


def test_real_account_credentials_pass_the_gate_and_auto_login(client, monkeypatch):
    """The 'one prompt, not two' merge: Basic Auth with a real account's
    own credentials both satisfies check_auth AND establishes a session,
    so check_login (which runs right after in the same request) doesn't
    also redirect to /login."""
    monkeypatch.setenv("CHAT_NETWORK_ACCESS_ENABLED", "1")
    fresh = client.application.test_client()

    response = fresh.get(
        "/api/providers", headers=_basic("test-admin", "test-admin-pw-1"), environ_base=REMOTE
    )

    assert response.status_code == 200


def test_wrong_real_account_password_falls_through_to_401(client, monkeypatch):
    monkeypatch.setenv("CHAT_NETWORK_ACCESS_ENABLED", "1")
    fresh = client.application.test_client()

    response = fresh.get("/api/providers", headers=_basic("test-admin", "wrong-pw"), environ_base=REMOTE)

    assert response.status_code == 401


def test_a_gate_code_passes_the_gate_but_does_not_establish_a_session(client, users_db):
    from chat_app.auth import store

    issued = store.create_gate_code(users_db, created_by="test-admin", ttl_hours=1)
    fresh = client.application.test_client()

    response = fresh.get("/", headers=_basic("whoever", issued.code), environ_base=REMOTE, follow_redirects=False)

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_gate_code_username_field_is_ignored(client, users_db):
    from chat_app.auth import store

    issued = store.create_gate_code(users_db, created_by="test-admin", ttl_hours=1)
    fresh = client.application.test_client()

    response = fresh.get("/api/providers", headers=_basic("literally-anything", issued.code), environ_base=REMOTE)

    assert response.status_code == 401  # gate passed (not 403); 401 is check_login's JSON-API rejection


def test_expired_gate_code_is_rejected(client, users_db):
    from chat_app.auth import store
    import sqlite3
    from datetime import datetime, timedelta, timezone

    issued = store.create_gate_code(users_db, created_by="test-admin", ttl_hours=1)
    conn = sqlite3.connect(str(users_db))
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    conn.execute("UPDATE gate_codes SET expires_at = ? WHERE code_id = ?", (past, issued.code_id))
    conn.commit()
    conn.close()
    fresh = client.application.test_client()

    response = fresh.get("/api/providers", headers=_basic("whoever", issued.code), environ_base=REMOTE)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith("Basic ")


def test_revoked_gate_code_is_rejected_immediately(client, users_db):
    from chat_app.auth import store

    issued = store.create_gate_code(users_db, created_by="test-admin", ttl_hours=1)
    store.delete_gate_code(users_db, issued.code_id)
    fresh = client.application.test_client()

    response = fresh.get("/api/providers", headers=_basic("whoever", issued.code), environ_base=REMOTE)

    assert response.status_code == 401


def test_shared_pair_still_takes_priority_when_configured(client, monkeypatch):
    """All three signals can be true at once - the shared pair (checked
    first) still works exactly as before."""
    monkeypatch.setenv("CHAT_AUTH_USER", "me")
    monkeypatch.setenv("CHAT_AUTH_PASSWORD", "s3cret")
    fresh = client.application.test_client()

    response = fresh.get("/api/providers", headers=_basic("me", "s3cret"), environ_base=REMOTE)

    assert response.status_code == 200
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_security.py -v -k "gate_ or real_account or shared_pair_still or gate_code"`
Expected: FAIL - most either error on `AttributeError` (no, those live in service/store which already exist from Tasks 1-2) or on wrong status codes, since `check_auth` hasn't been rewritten yet (e.g. `test_network_access_enabled_env_var_switches_the_gate_on` gets 403 instead of 401, because today's `check_auth` never calls `network_gate_enabled()`).

- [ ] **Step 3: Rewrite `check_auth()`**

In `chat_app/src/chat_app/security.py`, change the import line:

```python
from chat_app.auth import permissions
from chat_app.auth.service import current_scopes, is_authenticated, is_executive, logout
```

to:

```python
from chat_app.auth import permissions
from chat_app.auth.service import (
    check_credentials,
    current_scopes,
    gate_code_grants_access,
    is_authenticated,
    is_executive,
    login,
    logout,
    network_gate_enabled,
)
```

Replace the `check_auth()` function body:

```python
def check_auth() -> Response | None:
    credentials = configured_credentials()

    if credentials is None:
        if _is_loopback_address(request.remote_addr):
            return None
        return _error(
            "This app is not configured for network access. Set CHAT_AUTH_USER "
            "and CHAT_AUTH_PASSWORD to enable authenticated remote access.",
            403,
        )

    user, password = credentials
    supplied = request.authorization
    if supplied is None or supplied.type != "basic":
        return _error("Authentication required.", 401, {"WWW-Authenticate": f'Basic realm="{AUTH_REALM}"'})

    # compare_digest on both halves, and never short-circuit between them:
    # a plain == leaks how much of the credential was right via timing.
    user_ok = secrets.compare_digest((supplied.username or ""), user)
    password_ok = secrets.compare_digest((supplied.password or ""), password)
    if not (user_ok and password_ok):
        return _error("Invalid credentials.", 401, {"WWW-Authenticate": f'Basic realm="{AUTH_REALM}"'})
    return None
```

with:

```python
def check_auth() -> Response | None:
    """Whether this request satisfies the network gate.

    ``auth.service.network_gate_enabled()`` decides whether the gate is
    switched on AT ALL - kept as a separate question from what satisfies
    it once active, since ADMIN_USERNAME/PASSWORD is mandatory in every
    deployment (see that function's docstring for why "an admin account
    exists" can never be the activation signal by itself).

    Once the gate is on, EVERY request needs valid Basic Auth - including
    a loopback one, and including one that already carries a valid
    session cookie (check_login, which reads that cookie, doesn't run
    until after this check) - unchanged from today's behavior when
    CHAT_AUTH_USER/PASSWORD was the only way to switch it on. There are
    now three ways to satisfy it, checked in order:

    1. The configured shared pair, exactly as before.
    2. A real account's own credentials (service.check_credentials - the
       same check the login form itself uses), which - unlike the shared
       pair - also establishes a session immediately (service.login()),
       so check_login sees it right after in the same request. This is
       the "one prompt, not two" merge: a browser that's cached this
       Basic Auth challenge resends it on every subsequent request
       automatically, so a person only ever has to type it once.
    3. A currently-valid gate code, checked against the password field
       only - the username is meaningless for a credential that isn't
       tied to any identity. Passes the gate but does NOT log anyone in;
       check_login still sends them to /login right after, same as an
       unauthenticated request today.
    """
    if not network_gate_enabled():
        if _is_loopback_address(request.remote_addr):
            return None
        return _error(
            "This app is not configured for network access. Set CHAT_AUTH_USER/"
            "CHAT_AUTH_PASSWORD or CHAT_NETWORK_ACCESS_ENABLED, or mint a gate "
            "code from the Account manager, to enable authenticated remote access.",
            403,
        )

    supplied = request.authorization
    if supplied is None or supplied.type != "basic":
        return _error("Authentication required.", 401, {"WWW-Authenticate": f'Basic realm="{AUTH_REALM}"'})
    username = supplied.username or ""
    password = supplied.password or ""

    credentials = configured_credentials()
    if credentials is not None:
        user, expected_password = credentials
        # compare_digest on both halves, and never short-circuit between
        # them: a plain == leaks how much of the credential was right via
        # timing.
        user_ok = secrets.compare_digest(username, user)
        password_ok = secrets.compare_digest(password, expected_password)
        if user_ok and password_ok:
            return None

    if check_credentials(username, password):
        login(username)
        return None

    if gate_code_grants_access(password):
        return None

    return _error("Invalid credentials.", 401, {"WWW-Authenticate": f'Basic realm="{AUTH_REALM}"'})
```

Also update the module docstring's check-2 paragraph (starting `**2. The caller is authenticated.**`) to:

```
**2. The caller is authenticated.** HTTP Basic Auth, checked once the
network gate is switched on (``auth.service.network_gate_enabled()``) -
against a shared credential from the environment, a real account's own
credentials (which also logs that account in immediately - see
``check_auth``'s docstring for why), or a temporary gate code. If the
gate isn't switched on at all, the app still runs but serves loopback
requests only - local development stays frictionless, while exposing it
to a network requires deliberately switching the gate on. Note the
fallback trusts ``remote_addr``: behind a reverse proxy every request
appears to come from the proxy, i.e. from loopback, so **you must switch
the gate on before putting this behind a proxy**. ``X-Forwarded-For`` is
deliberately not consulted - it's caller-supplied and trivially forged
unless a proxy you control overwrites it.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_security.py tests/test_auth_routes.py tests/test_account_routes.py -v`
Expected: PASS - the new tests plus every pre-existing test in these three files (regression check for the byte-for-byte-unchanged-when-off guarantee and the shared-pair path).

- [ ] **Step 5: Document `CHAT_NETWORK_ACCESS_ENABLED`**

In `chat_app/.env.example`, add this block right after the existing `CHAT_ALLOWED_HOSTS=` line and its blank line (before the `# Per-user chat history.` comment):

```
# Explicit "reachable via real accounts alone" switch. Set this (any
# non-empty value) to require Basic Auth for every request (see
# CHAT_AUTH_USER/CHAT_AUTH_PASSWORD above) WITHOUT configuring a shared
# CHAT_AUTH_USER/PASSWORD pair at all - useful if you never want a shared
# secret, only real per-person accounts. Leave unset if you're already
# using CHAT_AUTH_USER/PASSWORD, or if this app should stay loopback-only.
# A currently-valid gate code (minted from the Account manager's Network
# access tab, or the sidebar's "+ Gate code" button) switches this gate
# on by itself too, the same as this var does - see security.check_auth.
CHAT_NETWORK_ACCESS_ENABLED=
```

In `chat_app/zima_host.yaml`, add a comment (not an active env line, since this deployment already sets `CHAT_AUTH_USER`/`CHAT_AUTH_PASSWORD`) right after the `CHAT_ALLOWED_HOSTS` line:

```
      # Alternative to CHAT_AUTH_USER/PASSWORD above, not needed alongside
      # them: set CHAT_NETWORK_ACCESS_ENABLED=1 instead if you'd rather
      # require real per-person account logins for every request than a
      # shared pair. See .env.example for the full explanation.
```

- [ ] **Step 6: Commit**

```bash
git add chat_app/src/chat_app/security.py chat_app/tests/test_security.py chat_app/.env.example chat_app/zima_host.yaml
git commit -m "feat: merge network-gate Basic Auth with real-account login and gate codes"
```

---

### Task 4: Account manager - "Network access" tab (admin UI + admin API)

**Files:**
- Modify: `chat_app/src/chat_app/pages/account/routes.py`
- Modify: `chat_app/src/chat_app/auth/permissions.py`
- Modify: `chat_app/src/chat_app/pages/account/template/index.html`
- Modify: `chat_app/src/chat_app/pages/account/template/script.js`
- Modify: `chat_app/src/chat_app/pages/account/template/styles.css`
- Test: `chat_app/tests/test_account_routes.py`

**Interfaces:**
- Consumes: `store.create_gate_code`, `store.list_gate_codes`, `store.delete_gate_code`, `store.UnknownGateCode` (Task 1).
- Produces: `POST /accounts/api/gate-codes` (body `{ttl_hours}`, required positive number; 201 with `{code_id, code, created_by, created_at, expires_at}`), `DELETE /accounts/api/gate-codes/<code_id>` (200, or 404 for an unknown id). Both gated by the `"accounts"` scope, same as the existing invite-code admin endpoints.

- [ ] **Step 1: Write the failing tests**

Add near the top of `chat_app/tests/test_account_routes.py`, after the existing `ADMIN_PASSWORD = "s3cret-pw"` line:

```python
def _basic(user, password):
    from base64 import b64encode

    token = b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}
```

Then append a new section at the end of the file:

```python
# --- gate codes (Network access tab) --------------------------------------
#
# Minting a gate code switches the network gate on for the whole app (see
# security.check_auth / auth.service.network_gate_enabled) - so any
# follow-up HTTP call in these tests, after a code already exists, needs
# its own Basic Auth header even though admin_client already carries a
# session cookie. Using the env admin's own credentials for that (which
# also satisfies the gate via the real-account path) is simplest.


def test_admin_can_generate_a_gate_code(admin_client, users_db):
    response = admin_client.post("/accounts/api/gate-codes", json={"ttl_hours": 24})

    assert response.status_code == 201
    data = response.get_json()
    assert data["code"]
    assert data["expires_at"] is not None


def test_generating_a_gate_code_without_a_ttl_fails(admin_client, users_db):
    response = admin_client.post("/accounts/api/gate-codes", json={})

    assert response.status_code == 400


def test_member_cannot_generate_a_gate_code_via_the_admin_endpoint(admin_client, users_db):
    member = _member_client(admin_client)

    response = member.post("/accounts/api/gate-codes", json={"ttl_hours": 24})

    assert response.status_code == 403


def test_admin_can_delete_an_outstanding_gate_code(admin_client, users_db):
    admin_client.post("/accounts/api/gate-codes", json={"ttl_hours": 24})
    [gate_code] = store.list_gate_codes(users_db)

    response = admin_client.delete(
        f"/accounts/api/gate-codes/{gate_code['code_id']}", headers=_basic(ADMIN_USER, ADMIN_PASSWORD)
    )

    assert response.status_code == 200
    assert store.list_gate_codes(users_db) == []


def test_deleting_an_unknown_gate_code_returns_404(admin_client, users_db):
    response = admin_client.delete(
        "/accounts/api/gate-codes/not-a-real-code-id", headers=_basic(ADMIN_USER, ADMIN_PASSWORD)
    )

    assert response.status_code == 404


def test_member_cannot_delete_a_gate_code(admin_client, users_db):
    admin_client.post("/accounts/api/gate-codes", json={"ttl_hours": 24})
    [gate_code] = store.list_gate_codes(users_db)
    member = _member_client(admin_client)

    response = member.delete(
        f"/accounts/api/gate-codes/{gate_code['code_id']}", headers=_basic(ADMIN_USER, ADMIN_PASSWORD)
    )

    assert response.status_code == 403


def test_network_access_tab_lists_active_gate_codes(admin_client, users_db):
    store.create_gate_code(users_db, created_by="admin", ttl_hours=1)

    page = admin_client.get("/accounts/", headers=_basic(ADMIN_USER, ADMIN_PASSWORD)).get_data(as_text=True)

    assert "Network access" in page
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_account_routes.py -v -k gate_code`
Expected: FAIL - 404s on `/accounts/api/gate-codes` (route doesn't exist yet).

- [ ] **Step 3: Add the admin API endpoints**

In `chat_app/src/chat_app/pages/account/routes.py`, add these two routes after `delete_invite_api`:

```python
@account_bp.post("/api/gate-codes")
def create_gate_code_api():
    """Mint a temporary Basic Auth password that satisfies the network
    gate without tying to any identity - see security.check_auth's third
    credential path. Admin-facing: TTL is a required choice (the account
    manager's own form offers 1/24/168 hours), unlike the invite form's
    optional "never expires" - a gate code with no expiry would
    contradict "temporary" by definition (see auth/store.py's schema).
    """
    data = json_body()
    try:
        ttl_hours = float(data.get("ttl_hours"))
    except (TypeError, ValueError):
        return _api_error("ttl_hours is required and must be a number.")
    if ttl_hours <= 0:
        return _api_error("ttl_hours must be positive.")

    issued = store.create_gate_code(settings.users_db_path, created_by=service.current_username(), ttl_hours=ttl_hours)
    return (
        jsonify(
            {
                "code_id": issued.code_id,
                "code": issued.code,
                "created_by": issued.created_by,
                "created_at": issued.created_at,
                "expires_at": issued.expires_at,
            }
        ),
        201,
    )


@account_bp.delete("/api/gate-codes/<code_id>")
def delete_gate_code_api(code_id: str):
    try:
        store.delete_gate_code(settings.users_db_path, code_id)
    except store.UnknownGateCode:
        return _api_error(f"No such gate code {code_id!r}.", 404)
    return jsonify({"status": "ok"})
```

In the same file, `manage_page()` needs to pass the active gate codes to the template. Add this line inside the `render_template(...)` call, right after `invites=store.list_invite_codes(settings.users_db_path),`:

```python
        gate_codes=store.list_gate_codes(settings.users_db_path),
```

In `chat_app/src/chat_app/auth/permissions.py`, add the two new endpoint names to the existing `"accounts"` scope entry:

```python
    "accounts": {
        "label": "Account manager (create/remove users, manage roles)",
        "endpoints": {
            "account.static",
            "account.manage_page",
            "account.create_user_api",
            "account.delete_user_api",
            "account.set_role_api",
            "account.create_role_api",
            "account.delete_role_api",
            "account.create_invite_api",
            "account.delete_invite_api",
            "account.create_gate_code_api",
            "account.delete_gate_code_api",
        },
    },
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_account_routes.py -v`
Expected: PASS, including all pre-existing tests in the file (regression check).

- [ ] **Step 5: Add the "Network access" tab UI**

In `chat_app/src/chat_app/pages/account/template/index.html`, add a fourth tab button after the "Invitations" button:

```html
    <button class="tab-btn" type="button" data-tab="gate-codes" role="tab" aria-selected="false">Network access</button>
```

Add a new `<section>` after the closing `</section>` of `id="tab-invites"` (before the final `</div>` that closes `.page-content`):

```html
  <section class="tab-panel" id="tab-gate-codes" role="tabpanel">
    <div class="panel-block">
      <h2>Generate a gate code</h2>
      <p class="section-hint">
        A temporary password that lets someone through the network gate without a shared secret or an
        account of their own - they'll still need to register (or log in) once they're through. Once a
        real account's own credentials can also satisfy this gate, logging out is best-effort: browsers
        cache Basic Auth and can silently resend it, so a full sign-out may also need closing the browser
        or clearing its saved site credentials.
      </p>
      <form id="create-gate-code-form" class="inline-form">
        <select name="ttl_hours" required>
          <option value="1">1 hour</option>
          <option value="24" selected>24 hours</option>
          <option value="168">7 days</option>
        </select>
        <button type="submit">Generate code</button>
      </form>
      <p id="gate-code-result"></p>
    </div>

    <div class="panel-block">
      <h2>Active gate codes</h2>
      <p class="section-hint">Every code below is still valid - it disappears from this list automatically once it expires.</p>
      <table>
        <thead><tr><th>Code</th><th>Created by</th><th>Created</th><th>Expires</th><th></th></tr></thead>
        <tbody id="gate-codes-body">
          {% for gate_code in gate_codes %}
          <tr data-code-id="{{ gate_code.code_id }}">
            <td><span class="invite-code-unavailable" title="Only shown once, right after it's generated">—</span></td>
            <td>{{ gate_code.created_by }}</td>
            <td>{{ gate_code.created_at }}</td>
            <td>{{ gate_code.expires_at }}</td>
            <td><button class="delete-gate-code danger" type="button">Delete</button></td>
          </tr>
          {% endfor %}
          {% if not gate_codes %}
          <tr><td colspan="5" class="empty-row">No active gate codes.</td></tr>
          {% endif %}
        </tbody>
      </table>
    </div>
  </section>
```

In `chat_app/src/chat_app/pages/account/template/script.js`, add after the existing `invites-body` click handler at the end of the file:

```javascript
function prependGateCodeRow(gateCode) {
  const body = document.getElementById('gate-codes-body');
  body.querySelector('.empty-row')?.closest('tr')?.remove();

  const row = document.createElement('tr');
  row.dataset.codeId = gateCode.code_id;
  addCell(row, buildCopyButton(gateCode.code));
  addCell(row, gateCode.created_by);
  addCell(row, gateCode.created_at);
  addCell(row, gateCode.expires_at);
  const deleteBtn = document.createElement('button');
  deleteBtn.type = 'button';
  deleteBtn.className = 'delete-gate-code danger';
  deleteBtn.textContent = 'Delete';
  addCell(row, deleteBtn);

  body.insertBefore(row, body.firstChild);
}

document.getElementById('create-gate-code-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.target;
  const result = document.getElementById('gate-code-result');
  result.textContent = 'Generating…';
  try {
    const data = await callApi('/accounts/api/gate-codes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ttl_hours: form.ttl_hours.value }),
    });
    result.textContent = '';
    result.append(`Gate code (expires: ${data.expires_at}): `, buildCopyChip(data.code));
    prependGateCodeRow(data);
  } catch (err) {
    result.textContent = `Failed to generate a code: ${err.message}`;
  }
});

document.getElementById('gate-codes-body').addEventListener('click', async (event) => {
  if (!event.target.classList.contains('delete-gate-code')) return;
  const row = event.target.closest('tr');
  const codeId = row.dataset.codeId;
  const confirmed = await confirmModal({
    title: 'Delete gate code?',
    message: 'Anyone still holding it will no longer be able to use it to get through the network gate.',
    confirmLabel: 'Delete',
    danger: true,
  });
  if (!confirmed) return;
  try {
    await callApi(`/accounts/api/gate-codes/${encodeURIComponent(codeId)}`, { method: 'DELETE' });
    location.reload();
  } catch (err) {
    showStatus(`Failed to delete gate code: ${err.message}`, true);
  }
});
```

In `chat_app/src/chat_app/pages/account/template/styles.css`, change the `#invite-result` rule to cover both:

```css
#invite-result, #gate-code-result { font-size: 13px; margin-top: 8px; color: #333; display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
```

- [ ] **Step 6: Commit**

```bash
git add chat_app/src/chat_app/pages/account/routes.py chat_app/src/chat_app/auth/permissions.py chat_app/src/chat_app/pages/account/template/index.html chat_app/src/chat_app/pages/account/template/script.js chat_app/src/chat_app/pages/account/template/styles.css chat_app/tests/test_account_routes.py
git commit -m "feat: add Network access tab to the Account manager"
```

---

### Task 5: Self-service gate-code quick action (sidebar)

**Files:**
- Modify: `chat_app/src/chat_app/pages/auth/routes.py`
- Modify: `chat_app/src/chat_app/auth/permissions.py`
- Modify: `chat_app/src/chat_app/pages/_shared/template/sidebar.html`
- Modify: `chat_app/src/chat_app/pages/_shared/template/sidebar.js`
- Test: `chat_app/tests/test_auth_routes.py`

**Interfaces:**
- Consumes: `store.create_gate_code` (Task 1); `prependGateCodeRow` (Task 4, optional - only present when the current page is the Account manager).
- Produces: `POST /api/gate-codes` (no body; 200 with `{code_id, code, created_by, created_at, expires_at}`), gated by the `"invites"` scope, mirroring `auth.create_invite`.

- [ ] **Step 1: Write the failing tests**

Append to `chat_app/tests/test_auth_routes.py`, after the existing `test_generating_an_invite_requires_login` test:

```python
# --- self-service gate codes (sidebar quick-action) ------------------------


def test_generating_a_gate_code_requires_login(client, users_db, monkeypatch):
    _set_admin(monkeypatch)

    assert client.post("/api/gate-codes").status_code == 401


def test_logged_in_user_can_generate_a_gate_code(client, users_db, monkeypatch):
    user, password = _set_admin(monkeypatch)
    client.post("/login", data={"username": user, "password": password})

    response = client.post("/api/gate-codes")

    assert response.status_code == 200
    data = response.get_json()
    assert data["code"]
    assert data["expires_at"] is not None


def test_generated_gate_code_carries_a_twenty_four_hour_ttl(client, users_db, monkeypatch):
    user, password = _set_admin(monkeypatch)
    client.post("/login", data={"username": user, "password": password})

    from datetime import datetime

    data = client.post("/api/gate-codes").get_json()
    created = datetime.fromisoformat(data["created_at"])
    expires = datetime.fromisoformat(data["expires_at"])

    assert (expires - created).total_seconds() == pytest.approx(24 * 3600, abs=2)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_auth_routes.py -v -k gate_code`
Expected: FAIL - 404 on `POST /api/gate-codes` (route doesn't exist yet).

- [ ] **Step 3: Add the self-service endpoint**

In `chat_app/src/chat_app/pages/auth/routes.py`, add this route after `create_invite`:

```python
@auth_bp.post("/api/gate-codes")
def create_gate_code():
    """Mint a 24-hour gate code as the logged-in user - the sidebar's
    self-service quick action, mirroring create_invite immediately above.
    Fixed TTL, no options: an admin who wants to choose the expiry uses
    the account manager's own gate-code form instead - see
    pages/account/routes.py.
    """
    issued = store.create_gate_code(settings.users_db_path, created_by=service.current_username(), ttl_hours=24)
    return jsonify(
        {
            "code_id": issued.code_id,
            "code": issued.code,
            "created_by": issued.created_by,
            "created_at": issued.created_at,
            "expires_at": issued.expires_at,
        }
    )
```

In `chat_app/src/chat_app/auth/permissions.py`, add the new endpoint to the existing `"invites"` scope entry:

```python
    "invites": {
        "label": "Generate invite codes",
        "endpoints": {"auth.create_invite", "auth.create_gate_code"},
    },
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_auth_routes.py -v`
Expected: PASS, including all pre-existing tests in the file (regression check).

- [ ] **Step 5: Add the sidebar quick-action UI**

In `chat_app/src/chat_app/pages/_shared/template/sidebar.html`, change the `invites`-scoped block:

```html
  {% if 'invites' in scopes %}
  <div class="sidebar-invite">
    <button id="sidebar-generate-invite" type="button" class="sidebar-invite-btn">+ Invite code</button>
    <p id="sidebar-invite-result" class="sidebar-invite-result"></p>
  </div>
  {% endif %}
```

to:

```html
  {% if 'invites' in scopes %}
  <div class="sidebar-invite">
    <button id="sidebar-generate-invite" type="button" class="sidebar-invite-btn">+ Invite code</button>
    <p id="sidebar-invite-result" class="sidebar-invite-result"></p>
    <button id="sidebar-generate-gate-code" type="button" class="sidebar-invite-btn">+ Gate code</button>
    <p id="sidebar-gate-code-result" class="sidebar-invite-result"></p>
  </div>
  {% endif %}
```

In `chat_app/src/chat_app/pages/_shared/template/sidebar.js`, add a new IIFE after the existing `sidebar-generate-invite` one:

```javascript
(function () {
  const btn = document.getElementById('sidebar-generate-gate-code');
  if (!btn) return;
  btn.addEventListener('click', async () => {
    const result = document.getElementById('sidebar-gate-code-result');
    result.textContent = 'Generating…';
    try {
      const response = await fetch('/api/gate-codes', { method: 'POST' });
      if (!response.ok) throw new Error(`Server returned ${response.status}`);
      const data = await response.json();
      result.textContent = '';
      result.append('Code: ', buildCopyChip(data.code));
      // Only defined on the account manager page (account/script.js,
      // loaded before this file - see that page's index.html). Generating
      // a code from the sidebar while the Network access tab is open
      // should update its list the same as generating one from the tab's
      // own form does, not leave it looking stale until a reload.
      if (typeof prependGateCodeRow === 'function') prependGateCodeRow(data);
    } catch (err) {
      result.textContent = `Failed: ${err.message}`;
    }
  });
})();
```

- [ ] **Step 6: Commit**

```bash
git add chat_app/src/chat_app/pages/auth/routes.py chat_app/src/chat_app/auth/permissions.py chat_app/src/chat_app/pages/_shared/template/sidebar.html chat_app/src/chat_app/pages/_shared/template/sidebar.js chat_app/tests/test_auth_routes.py
git commit -m "feat: add self-service gate-code quick action to the sidebar"
```

---

## Manual verification (after all tasks)

Automated tests cover every behavior above, but the merged Basic Auth flow and the two UI surfaces are worth a manual pass in a real browser (per this project's own testing preferences, run the app yourself rather than delegating to a browser-automation agent):

1. Start the app with `CHAT_NETWORK_ACCESS_ENABLED=1` and an `ADMIN_USERNAME`/`ADMIN_PASSWORD` set, hit it from a non-loopback address (or just confirm the Basic Auth prompt appears), and log in with the admin's real credentials at that prompt - confirm you land straight on the app with no second `/login` form.
2. From the Account manager's new "Network access" tab, generate a gate code and confirm the copy chip/table behave like the Invitations tab.
3. In a private/incognito window (no cached Basic Auth), hit the app with the gate code as the Basic Auth password (any username) - confirm you're bounced to `/register` or `/login` rather than straight in.
4. Revoke the gate code and confirm the same private window's next request is rejected.
5. Note the expected rough edge from this plan's Global Constraints: once a gate code exists (or `CHAT_NETWORK_ACCESS_ENABLED` is set), *every* request needs Basic Auth, including your own already-logged-in browser tab if it never got challenged for one - reloading that tab should prompt you for Basic Auth at that point. Confirm this matches what you see, since it's an accepted consequence of the design rather than a bug.

## Self-review notes

- **Spec coverage:** §1 (activation + 3 credential paths) → Task 3. §2 (`gate_codes` table + store functions + service functions) → Tasks 1-2. §3 admin UI → Task 4. §3 self-service quick action → Task 5. "Known limitation" UI note → Task 4's tab copy. `.env.example`/`zima_host.yaml` open item → Task 3 Step 5. Testing section's three categories (security integration, store unit, account-route) → Tasks 3, 1, 4/5 respectively.
- **Placeholder scan:** no TBD/TODO markers; every step has literal code or literal shell commands.
- **Type consistency:** `IssuedGateCode` fields (`code_id`, `code`, `created_by`, `created_at`, `expires_at`) match the dict shape `list_gate_codes` and the two route handlers return, and match what `script.js`'s `prependGateCodeRow`/`sidebar.js` read off the JSON response (`data.code_id`, `data.code`, `data.created_by`, `data.created_at`, `data.expires_at`) throughout Tasks 1, 4, and 5.
