# AuthTemplate Auth Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the one merged login/registration/logout flow — OTP-gated registration, credential verification wired into Flask-Login sessions, device-fingerprint-triggered `SecurityEvent` logging, role/permission enforcement via a `@require_permission` decorator, a self-healing bootstrap admin, and the first real page (`pages/Auth/`) with styled login/register forms and 401/403/429 error pages. This is Phase 3 of a multi-phase build, depending on the models (Phase 1: [2026-08-21-authtemplate-foundation.md](2026-08-21-authtemplate-foundation.md)) and security pipeline (Phase 2: [2026-08-21-authtemplate-security-pipeline.md](2026-08-21-authtemplate-security-pipeline.md)).

**Architecture:** `tokens.py` (random codes + hashing) → `authz.py` (permission registry + `@require_permission`, also where `Account` gains `UserMixin` since this is the first code needing Flask-Login's `current_user`) → `otp_service.py` (OTP lifecycle) → `auth_service.py` (credential check, session issuance via a module-level `LoginManager` singleton mirroring the `db` singleton pattern, registration, and a self-healing bootstrap-admin routine) → `pages/__index__.py` (blueprint auto-discovery) + `pages/Auth/` (the actual login/register/logout routes and templates) → wired together in `create_app`. Business logic stays in services, tested without needing the pages layer; the pages layer is a thin adapter tested via Flask's test client.

**Tech Stack:** Flask-Login (`UserMixin`, `LoginManager`, `login_user`/`logout_user`/`current_user`), Werkzeug's `generate_password_hash`/`check_password_hash` (scrypt), Python's `secrets`/`hashlib`/`hmac` stdlib modules, Jinja2 templates, pytest with Flask's test client.

**Spec:** [docs/superpowers/specs/2026-08-21-authtemplate-design.md](../specs/2026-08-21-authtemplate-design.md)

## Global Constraints

- No login-time 2FA/OTP — OTP is a registration gate only (spec §1, §2).
- Registering with a valid OTP creates the `Account` with **no roles assigned by default** (spec §7, §18).
- Password hashing: Werkzeug's `generate_password_hash`/`check_password_hash` (scrypt) (spec §18).
- Permissions are namespaced strings (`"<page>.<action>"`), discovered as pages declare them via `@require_permission` — no schema migration needed to add one (spec §5, §10).
- Bootstrap admin: on first run (empty `accounts` table), auto-create one `is_protected` admin holding every known permission; credentials from `secret_bootstrap_admin.env` if present, else a random password generated and printed to the console once (spec §8).
- Error handling: 401 → redirect to `/auth/login`; 403 → permission-denied page; 429 → rate-limited page; consistent styled pages sharing the base layout (spec §15).
- `pages/__index__.py` auto-discovers each subfolder (excluding `__shared__`), expects a `blueprint` attribute, registers with a URL prefix from the lowercased folder name — `Overview` is the one exception, mapping to `/` (spec §11).
- Documentation is distributed per folder (spec §17) — `src/pages/README.md` (folder convention + page index) and `src/pages/Auth/README.md` (this page's routes/permissions) must exist.
- All stored timestamps are UTC; SQLite round-trips `db.DateTime` columns as naive datetimes (Phase 1/2 constraint — still applies to `InviteOTP.expires_at` comparisons here).
- `src/run.py`'s `create_app(config: dict | None = None) -> Flask` signature does not change.
- No placeholders, no TODOs.

---

## File Structure

```
src/
  models/
    account.py                    # MODIFIED: adds UserMixin
  utils/
    tokens.py                     # generate_otp_code, hash_token, verify_token
  services/
    authz.py                       # registered_permissions, account_permissions, has_permission, require_permission
    otp_service.py                 # create_invite, find_valid_invite, consume_invite
    auth_service.py                 # login_manager, init_login_manager, verify_credentials, record_login_attempt, register_account, ensure_bootstrap_admin
  pages/
    __init__.py                     # empty, package marker
    __index__.py                     # discover_page_modules, register_pages
    README.md
    __shared__/
      base.html
      error_403.html
      error_429.html
    Auth/
      __init__.py                   # empty, package marker
      __index__.py                   # blueprint: /login /register /logout
      login.html
      register.html
      style.css
      script.js
      README.md
  run.py                             # MODIFIED: wires login manager, pages, bootstrap admin, error handlers
tests/
  test_tokens.py
  test_authz.py
  test_otp_service.py
  test_auth_service.py
  test_bootstrap_admin.py
  test_pages_index.py
  test_auth_page.py
```

---

### Task 1: Token generation + hashing utility

**Files:**
- Create: `src/utils/tokens.py`
- Test: `tests/test_tokens.py`

**Interfaces:**
- Produces: `generate_otp_code(length: int = 10) -> str`, `hash_token(token: str) -> str`, `verify_token(token: str, token_hash: str) -> bool` in `src/utils/tokens.py`.
- Later tasks: Task 3 (`otp_service.py`) imports all three.

- [ ] **Step 1: Write the failing test**

`tests/test_tokens.py`:
```python
from src.utils.tokens import generate_otp_code, hash_token, verify_token


def test_generate_otp_code_returns_string_of_requested_length():
    code = generate_otp_code(length=12)

    assert len(code) == 12
    assert code.isascii()


def test_generate_otp_code_is_random():
    first = generate_otp_code()
    second = generate_otp_code()

    assert first != second


def test_hash_token_is_deterministic_and_not_reversible():
    token = "my-secret-code"

    first = hash_token(token)
    second = hash_token(token)

    assert first == second
    assert first != token
    assert len(first) == 64


def test_verify_token_true_for_matching_token():
    token = "my-secret-code"
    token_hash = hash_token(token)

    assert verify_token(token, token_hash) is True


def test_verify_token_false_for_wrong_token():
    token_hash = hash_token("my-secret-code")

    assert verify_token("wrong-code", token_hash) is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_tokens.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.utils.tokens'`

- [ ] **Step 3: Implement `tokens.py`**

`src/utils/tokens.py`:
```python
import hashlib
import hmac
import secrets


def generate_otp_code(length: int = 10) -> str:
    return secrets.token_urlsafe(length)[:length]


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_token(token: str, token_hash: str) -> bool:
    return hmac.compare_digest(hash_token(token), token_hash)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_tokens.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/utils/tokens.py tests/test_tokens.py
git commit -m "feat: add OTP token generation/hashing utility"
```

---

### Task 2: Permission enforcement (`authz.py`) + Account gains `UserMixin`

**Files:**
- Create: `src/services/authz.py`
- Modify: `src/models/account.py`
- Test: `tests/test_authz.py`

**Interfaces:**
- Consumes: `Account`, `Role`, `Permission`, `db` from `src.models` (Phase 1).
- Produces: `registered_permissions() -> set[str]`, `account_permissions(account) -> set[str]`, `has_permission(account, permission_name: str) -> bool`, `require_permission(permission_name: str)` (decorator factory) in `src/services/authz.py`. `Account` now implements Flask-Login's `UserMixin` (adds `is_authenticated`, `is_anonymous`, `get_id()`; its own mapped `is_active` column shadows `UserMixin.is_active` correctly).
- Later tasks: Task 4 (`auth_service.py`) uses Flask-Login's `login_user`/`current_user` against `Account`; Task 5 (bootstrap admin) imports `registered_permissions`; Task 6 (`pages/Admin` in a later phase, and any protected route) uses `require_permission`.

- [ ] **Step 1: Modify `Account` to add `UserMixin`**

`src/models/account.py` (full replacement):
```python
from datetime import datetime, timezone

from flask_login import UserMixin

from src.models.associations import account_role
from src.models.base import db


class Account(UserMixin, db.Model):
    __tablename__ = "accounts"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_protected = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    roles = db.relationship("Role", secondary=account_role, back_populates="accounts")
```

- [ ] **Step 2: Run the existing model tests to verify nothing broke**

Run: `pytest tests/test_models.py -v`
Expected: PASS (7 tests, unchanged — `UserMixin` only adds attributes, doesn't remove any)

- [ ] **Step 3: Write the failing test**

`tests/test_authz.py`:
```python
from flask_login import LoginManager, login_user

from src.models import Account, Permission, Role, db
from src.services.authz import (
    account_permissions,
    has_permission,
    registered_permissions,
    require_permission,
)


def test_require_permission_registers_permission_name():
    @require_permission("test_module.some_action")
    def view():
        return "ok"

    assert "test_module.some_action" in registered_permissions()


def test_account_permissions_returns_union_across_roles(app):
    with app.app_context():
        account = Account(username="grace", email="grace@example.com", password_hash="hashed")
        role_a = Role(name="role_a")
        role_b = Role(name="role_b")
        perm_a = Permission(name="a.read")
        perm_b = Permission(name="b.write")
        role_a.permissions.append(perm_a)
        role_b.permissions.append(perm_b)
        account.roles.extend([role_a, role_b])
        db.session.add(account)
        db.session.commit()

        permissions = account_permissions(account)

    assert permissions == {"a.read", "b.write"}


def test_has_permission_true_when_granted(app):
    with app.app_context():
        account = Account(username="heidi", email="heidi@example.com", password_hash="hashed")
        role = Role(name="role_c")
        permission = Permission(name="c.manage")
        role.permissions.append(permission)
        account.roles.append(role)
        db.session.add(account)
        db.session.commit()

        assert has_permission(account, "c.manage") is True
        assert has_permission(account, "c.other") is False


def test_require_permission_blocks_unauthenticated_request(app):
    login_manager = LoginManager()
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(Account, int(user_id))

    @app.route("/protected")
    @require_permission("protected.view")
    def protected():
        return "secret"

    client = app.test_client()
    response = client.get("/protected")

    assert response.status_code == 401


def test_require_permission_blocks_authenticated_without_permission(app):
    login_manager = LoginManager()
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(Account, int(user_id))

    @app.route("/login-as/<int:account_id>")
    def login_as(account_id):
        account = db.session.get(Account, account_id)
        login_user(account)
        return "logged in"

    @app.route("/protected2")
    @require_permission("protected2.view")
    def protected2():
        return "secret"

    with app.app_context():
        account = Account(username="ivan2", email="ivan2@example.com", password_hash="hashed")
        db.session.add(account)
        db.session.commit()
        account_id = account.id

    client = app.test_client()
    client.get(f"/login-as/{account_id}")
    response = client.get("/protected2")

    assert response.status_code == 403


def test_require_permission_allows_authenticated_with_permission(app):
    login_manager = LoginManager()
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(Account, int(user_id))

    @app.route("/login-as2/<int:account_id>")
    def login_as2(account_id):
        account = db.session.get(Account, account_id)
        login_user(account)
        return "logged in"

    @app.route("/protected3")
    @require_permission("protected3.view")
    def protected3():
        return "secret"

    with app.app_context():
        account = Account(username="judy", email="judy@example.com", password_hash="hashed")
        role = Role(name="role_d")
        permission = Permission(name="protected3.view")
        role.permissions.append(permission)
        account.roles.append(role)
        db.session.add(account)
        db.session.commit()
        account_id = account.id

    client = app.test_client()
    client.get(f"/login-as2/{account_id}")
    response = client.get("/protected3")

    assert response.status_code == 200
    assert response.data == b"secret"
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `pytest tests/test_authz.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.services.authz'`

- [ ] **Step 5: Implement `authz.py`**

`src/services/authz.py`:
```python
from functools import wraps

from flask import abort
from flask_login import current_user

_REGISTERED_PERMISSIONS: set[str] = set()


def registered_permissions() -> set[str]:
    return set(_REGISTERED_PERMISSIONS)


def account_permissions(account) -> set[str]:
    permissions: set[str] = set()
    for role in account.roles:
        for permission in role.permissions:
            permissions.add(permission.name)
    return permissions


def has_permission(account, permission_name: str) -> bool:
    return permission_name in account_permissions(account)


def require_permission(permission_name: str):
    _REGISTERED_PERMISSIONS.add(permission_name)

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if not has_permission(current_user, permission_name):
                abort(403)
            return view_func(*args, **kwargs)

        return wrapped

    return decorator
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `pytest tests/test_authz.py -v`
Expected: PASS (6 tests)

- [ ] **Step 7: Commit**

```bash
git add src/models/account.py src/services/authz.py tests/test_authz.py
git commit -m "feat: add permission registry/enforcement and UserMixin on Account"
```

---

### Task 3: OTP lifecycle service

**Files:**
- Create: `src/services/otp_service.py`
- Test: `tests/test_otp_service.py`

**Interfaces:**
- Consumes: `InviteOTP` from `src.models` (Phase 1); `generate_otp_code`, `hash_token`, `verify_token` from `src.utils.tokens` (Task 1).
- Produces: `create_invite(db_session, created_by_account_id: int, invitee_email: str | None, delivery_method: str) -> tuple[InviteOTP, str]`, `find_valid_invite(db_session, code: str) -> InviteOTP | None`, `consume_invite(db_session, invite: InviteOTP) -> None` in `src/services/otp_service.py`.
- Later tasks: Task 4 (`auth_service.register_account`) calls `find_valid_invite` and `consume_invite`.

- [ ] **Step 1: Write the failing test**

`tests/test_otp_service.py`:
```python
from datetime import datetime, timedelta, timezone

from src.models import Account, InviteOTP, db
from src.services import otp_service


def test_create_invite_persists_hashed_code_and_returns_plaintext(app):
    with app.app_context():
        inviter = Account(username="admin", email="admin@example.com", password_hash="hashed")
        db.session.add(inviter)
        db.session.commit()

        invite, code = otp_service.create_invite(db.session, inviter.id, "new@example.com", "email")

        assert invite.id is not None
        assert invite.code_hash != code
        assert invite.used_at is None
        assert invite.delivery_method == "email"


def test_find_valid_invite_matches_correct_code(app):
    with app.app_context():
        inviter = Account(username="admin2", email="admin2@example.com", password_hash="hashed")
        db.session.add(inviter)
        db.session.commit()

        invite, code = otp_service.create_invite(db.session, inviter.id, None, "manual")

        found = otp_service.find_valid_invite(db.session, code)

    assert found is not None
    assert found.id == invite.id


def test_find_valid_invite_rejects_wrong_code(app):
    with app.app_context():
        inviter = Account(username="admin3", email="admin3@example.com", password_hash="hashed")
        db.session.add(inviter)
        db.session.commit()

        otp_service.create_invite(db.session, inviter.id, None, "manual")

        found = otp_service.find_valid_invite(db.session, "totally-wrong-code")

    assert found is None


def test_find_valid_invite_rejects_expired_code(app):
    with app.app_context():
        inviter = Account(username="admin4", email="admin4@example.com", password_hash="hashed")
        db.session.add(inviter)
        db.session.commit()

        invite, code = otp_service.create_invite(db.session, inviter.id, None, "manual")
        invite.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.session.commit()

        found = otp_service.find_valid_invite(db.session, code)

    assert found is None


def test_find_valid_invite_rejects_used_code(app):
    with app.app_context():
        inviter = Account(username="admin5", email="admin5@example.com", password_hash="hashed")
        db.session.add(inviter)
        db.session.commit()

        invite, code = otp_service.create_invite(db.session, inviter.id, None, "manual")
        otp_service.consume_invite(db.session, invite)

        found = otp_service.find_valid_invite(db.session, code)

    assert found is None


def test_consume_invite_sets_used_at(app):
    with app.app_context():
        inviter = Account(username="admin6", email="admin6@example.com", password_hash="hashed")
        db.session.add(inviter)
        db.session.commit()

        invite, _ = otp_service.create_invite(db.session, inviter.id, None, "manual")
        otp_service.consume_invite(db.session, invite)

        refreshed = db.session.get(InviteOTP, invite.id)

    assert refreshed.used_at is not None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_otp_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.services.otp_service'`

- [ ] **Step 3: Implement `otp_service.py`**

`src/services/otp_service.py`:
```python
from datetime import datetime, timedelta, timezone

from src.models import InviteOTP
from src.utils.tokens import generate_otp_code, hash_token, verify_token

OTP_EXPIRY_MINUTES = 15


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def create_invite(
    db_session, created_by_account_id: int, invitee_email: str | None, delivery_method: str
) -> tuple[InviteOTP, str]:
    code = generate_otp_code()
    invite = InviteOTP(
        code_hash=hash_token(code),
        created_by_account_id=created_by_account_id,
        invitee_email=invitee_email,
        delivery_method=delivery_method,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRY_MINUTES),
    )
    db_session.add(invite)
    db_session.commit()
    return invite, code


def find_valid_invite(db_session, code: str) -> InviteOTP | None:
    now = datetime.now(timezone.utc)
    candidates = db_session.query(InviteOTP).filter(InviteOTP.used_at.is_(None)).all()
    for candidate in candidates:
        if verify_token(code, candidate.code_hash) and _as_utc(candidate.expires_at) > now:
            return candidate
    return None


def consume_invite(db_session, invite: InviteOTP) -> None:
    invite.used_at = datetime.now(timezone.utc)
    db_session.commit()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_otp_service.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/services/otp_service.py tests/test_otp_service.py
git commit -m "feat: add OTP invite lifecycle service"
```

---

### Task 4: Credential verification, session issuance, registration

**Files:**
- Create: `src/services/auth_service.py`
- Test: `tests/test_auth_service.py`

**Interfaces:**
- Consumes: `Account`, `LoginAttempt`, `db` from `src.models`; `otp_service.find_valid_invite`/`consume_invite` (Task 3).
- Produces: `login_manager` (module-level `LoginManager` singleton), `init_login_manager(app: Flask) -> None`, `verify_credentials(db_session, username: str, password: str) -> Account | None`, `record_login_attempt(db_session, ip_address: str, account_id: int | None, success: bool) -> LoginAttempt`, `register_account(db_session, username: str, email: str, password: str, invite_code: str) -> Account | None` in `src/services/auth_service.py`.
- Later tasks: Task 5 appends `ensure_bootstrap_admin` to this same file. Task 6 (`pages/Auth`) imports `verify_credentials`, `record_login_attempt`, `register_account`. Task 7 (`run.py`) imports `init_login_manager`.

- [ ] **Step 1: Write the failing test**

`tests/test_auth_service.py`:
```python
from werkzeug.security import generate_password_hash

from src.models import Account, InviteOTP, db
from src.services import auth_service, otp_service


def test_verify_credentials_returns_account_for_correct_password(app):
    with app.app_context():
        account = Account(
            username="carol",
            email="carol@example.com",
            password_hash=generate_password_hash("correct-horse"),
        )
        db.session.add(account)
        db.session.commit()

        result = auth_service.verify_credentials(db.session, "carol", "correct-horse")

    assert result is not None
    assert result.username == "carol"


def test_verify_credentials_returns_none_for_wrong_password(app):
    with app.app_context():
        account = Account(
            username="dave",
            email="dave@example.com",
            password_hash=generate_password_hash("correct-horse"),
        )
        db.session.add(account)
        db.session.commit()

        result = auth_service.verify_credentials(db.session, "dave", "wrong-password")

    assert result is None


def test_verify_credentials_returns_none_for_unknown_username(app):
    with app.app_context():
        result = auth_service.verify_credentials(db.session, "ghost", "whatever")

    assert result is None


def test_verify_credentials_returns_none_for_inactive_account(app):
    with app.app_context():
        account = Account(
            username="erin",
            email="erin@example.com",
            password_hash=generate_password_hash("correct-horse"),
            is_active=False,
        )
        db.session.add(account)
        db.session.commit()

        result = auth_service.verify_credentials(db.session, "erin", "correct-horse")

    assert result is None


def test_record_login_attempt_persists_row(app):
    with app.app_context():
        attempt = auth_service.record_login_attempt(db.session, "203.0.113.4", None, False)

    assert attempt.id is not None
    assert attempt.success is False


def test_register_account_creates_account_and_consumes_invite(app):
    with app.app_context():
        inviter = Account(username="admin", email="admin@example.com", password_hash="hashed")
        db.session.add(inviter)
        db.session.commit()

        invite, code = otp_service.create_invite(db.session, inviter.id, "newbie@example.com", "manual")

        account = auth_service.register_account(db.session, "newbie", "newbie@example.com", "s3cret!", code)

        assert account is not None
        assert account.username == "newbie"
        assert account.roles == []

        refreshed_invite = db.session.get(InviteOTP, invite.id)
        assert refreshed_invite.used_at is not None


def test_register_account_rejects_invalid_invite_code(app):
    with app.app_context():
        account = auth_service.register_account(db.session, "nope", "nope@example.com", "pw", "bad-code")

    assert account is None


def test_register_account_rejects_reused_invite_code(app):
    with app.app_context():
        inviter = Account(username="admin2", email="admin2@example.com", password_hash="hashed")
        db.session.add(inviter)
        db.session.commit()

        invite, code = otp_service.create_invite(db.session, inviter.id, None, "manual")
        first = auth_service.register_account(db.session, "first", "first@example.com", "pw", code)
        second = auth_service.register_account(db.session, "second", "second@example.com", "pw", code)

    assert first is not None
    assert second is None


def test_init_login_manager_user_loader_returns_account(app):
    auth_service.init_login_manager(app)

    with app.app_context():
        account = Account(username="frank", email="frank@example.com", password_hash="hashed")
        db.session.add(account)
        db.session.commit()

        loaded = auth_service.login_manager._user_callback(str(account.id))

    assert loaded is not None
    assert loaded.username == "frank"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_auth_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.services.auth_service'`

- [ ] **Step 3: Implement `auth_service.py`**

`src/services/auth_service.py`:
```python
from flask import Flask
from flask_login import LoginManager
from werkzeug.security import check_password_hash, generate_password_hash

from src.models import Account, LoginAttempt, db
from src.services import otp_service

login_manager = LoginManager()
login_manager.login_view = "auth.login"


def init_login_manager(app: Flask) -> None:
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(Account, int(user_id))


def verify_credentials(db_session, username: str, password: str) -> Account | None:
    account = db_session.query(Account).filter_by(username=username).first()
    if account is None or not account.is_active:
        return None
    if not check_password_hash(account.password_hash, password):
        return None
    return account


def record_login_attempt(
    db_session, ip_address: str, account_id: int | None, success: bool
) -> LoginAttempt:
    attempt = LoginAttempt(ip_address=ip_address, account_id=account_id, success=success)
    db_session.add(attempt)
    db_session.commit()
    return attempt


def register_account(
    db_session, username: str, email: str, password: str, invite_code: str
) -> Account | None:
    invite = otp_service.find_valid_invite(db_session, invite_code)
    if invite is None:
        return None

    account = Account(
        username=username,
        email=email,
        password_hash=generate_password_hash(password),
    )
    db_session.add(account)
    otp_service.consume_invite(db_session, invite)
    db_session.commit()
    return account
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_auth_service.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add src/services/auth_service.py tests/test_auth_service.py
git commit -m "feat: add credential verification, session issuance, and registration"
```

---

### Task 5: Self-healing bootstrap admin

**Files:**
- Modify: `src/services/auth_service.py`
- Test: `tests/test_bootstrap_admin.py`

**Interfaces:**
- Consumes: `Permission`, `Role` from `src.models`; `registered_permissions` from `src.services.authz` (Task 2); `load_env_secrets` from `src.utils.config_loader` (Phase 1).
- Produces: `ensure_bootstrap_admin(db_session, secrets_dir) -> None`, appended to `src/services/auth_service.py`.
- Later tasks: Task 7 (`run.py`) calls this once per app boot, after pages are registered (so `registered_permissions()` reflects every page's declared permissions).

- [ ] **Step 1: Write the failing test**

`tests/test_bootstrap_admin.py`:
```python
from src.models import Account, Role, db
from src.services.auth_service import ensure_bootstrap_admin
from src.services.authz import require_permission


def test_ensure_bootstrap_admin_creates_protected_account_when_none_exist(app, tmp_path):
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()

    with app.app_context():
        ensure_bootstrap_admin(db.session, secrets_dir)

        admin = db.session.query(Account).filter_by(is_protected=True).one()

    assert admin.username == "admin"
    assert admin.email == "admin@example.com"


def test_ensure_bootstrap_admin_uses_configured_credentials(app, tmp_path):
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "secret_bootstrap_admin.env").write_text(
        "BOOTSTRAP_ADMIN_USERNAME=root\n"
        "BOOTSTRAP_ADMIN_EMAIL=root@example.com\n"
        "BOOTSTRAP_ADMIN_PASSWORD=super-secret\n"
    )

    with app.app_context():
        ensure_bootstrap_admin(db.session, secrets_dir)

        admin = db.session.query(Account).filter_by(is_protected=True).one()

    assert admin.username == "root"
    assert admin.email == "root@example.com"


def test_ensure_bootstrap_admin_skips_creation_when_accounts_exist(app, tmp_path):
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()

    with app.app_context():
        existing = Account(username="someone", email="someone@example.com", password_hash="hashed")
        db.session.add(existing)
        db.session.commit()

        ensure_bootstrap_admin(db.session, secrets_dir)

        count = db.session.query(Account).count()

    assert count == 1


def test_ensure_bootstrap_admin_syncs_registered_permissions_onto_role(app, tmp_path):
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()

    @require_permission("bootstrap_test.some_action")
    def _dummy_view():
        return "ok"

    with app.app_context():
        ensure_bootstrap_admin(db.session, secrets_dir)

        role = db.session.query(Role).filter_by(name="Administrator").one()
        permission_names = {p.name for p in role.permissions}

    assert "bootstrap_test.some_action" in permission_names


def test_ensure_bootstrap_admin_role_permissions_self_heal_on_repeat_call(app, tmp_path):
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()

    @require_permission("bootstrap_test.self_heal_action")
    def _dummy_view():
        return "ok"

    with app.app_context():
        ensure_bootstrap_admin(db.session, secrets_dir)

        role = db.session.query(Role).filter_by(name="Administrator").one()
        role.permissions.clear()
        db.session.commit()

        ensure_bootstrap_admin(db.session, secrets_dir)

        refreshed_role = db.session.query(Role).filter_by(name="Administrator").one()
        permission_names = {p.name for p in refreshed_role.permissions}

    assert "bootstrap_test.self_heal_action" in permission_names
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_bootstrap_admin.py -v`
Expected: FAIL with `ImportError: cannot import name 'ensure_bootstrap_admin' from 'src.services.auth_service'`

- [ ] **Step 3: Implement `ensure_bootstrap_admin` (full replacement of `auth_service.py`)**

`src/services/auth_service.py`:
```python
import secrets as secrets_module

from flask import Flask
from flask_login import LoginManager
from werkzeug.security import check_password_hash, generate_password_hash

from src.models import Account, LoginAttempt, Permission, Role, db
from src.services import otp_service
from src.services.authz import registered_permissions
from src.utils.config_loader import load_env_secrets

login_manager = LoginManager()
login_manager.login_view = "auth.login"


def init_login_manager(app: Flask) -> None:
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(Account, int(user_id))


def verify_credentials(db_session, username: str, password: str) -> Account | None:
    account = db_session.query(Account).filter_by(username=username).first()
    if account is None or not account.is_active:
        return None
    if not check_password_hash(account.password_hash, password):
        return None
    return account


def record_login_attempt(
    db_session, ip_address: str, account_id: int | None, success: bool
) -> LoginAttempt:
    attempt = LoginAttempt(ip_address=ip_address, account_id=account_id, success=success)
    db_session.add(attempt)
    db_session.commit()
    return attempt


def register_account(
    db_session, username: str, email: str, password: str, invite_code: str
) -> Account | None:
    invite = otp_service.find_valid_invite(db_session, invite_code)
    if invite is None:
        return None

    account = Account(
        username=username,
        email=email,
        password_hash=generate_password_hash(password),
    )
    db_session.add(account)
    otp_service.consume_invite(db_session, invite)
    db_session.commit()
    return account


def _sync_administrator_role_permissions(db_session, role: Role) -> None:
    existing_names = {p.name for p in role.permissions}
    for name in registered_permissions():
        if name in existing_names:
            continue
        permission = db_session.query(Permission).filter_by(name=name).first()
        if permission is None:
            permission = Permission(name=name)
            db_session.add(permission)
        role.permissions.append(permission)
    db_session.commit()


def ensure_bootstrap_admin(db_session, secrets_dir) -> None:
    role = db_session.query(Role).filter_by(name="Administrator").first()
    if role is None:
        role = Role(name="Administrator", description="Full-access bootstrap role")
        db_session.add(role)
        db_session.commit()

    _sync_administrator_role_permissions(db_session, role)

    if db_session.query(Account).count() > 0:
        return

    bootstrap_secrets = load_env_secrets(secrets_dir / "secret_bootstrap_admin.env")
    username = bootstrap_secrets.get("BOOTSTRAP_ADMIN_USERNAME") or "admin"
    email = bootstrap_secrets.get("BOOTSTRAP_ADMIN_EMAIL") or "admin@example.com"
    password = bootstrap_secrets.get("BOOTSTRAP_ADMIN_PASSWORD")

    generated = False
    if not password:
        password = secrets_module.token_urlsafe(16)
        generated = True

    admin = Account(
        username=username,
        email=email,
        password_hash=generate_password_hash(password),
        is_protected=True,
    )
    admin.roles.append(role)
    db_session.add(admin)
    db_session.commit()

    if generated:
        print(
            f"Bootstrap admin created: username={username} password={password} "
            "(save this now, it will not be shown again)"
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_bootstrap_admin.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Run the full `auth_service` test file to verify nothing broke**

Run: `pytest tests/test_auth_service.py -v`
Expected: PASS (9 tests, unchanged)

- [ ] **Step 6: Commit**

```bash
git add src/services/auth_service.py tests/test_bootstrap_admin.py
git commit -m "feat: add self-healing bootstrap admin creation"
```

---

### Task 6: Pages infrastructure + Auth blueprint (login/register/logout)

**Files:**
- Create: `src/pages/__init__.py` (empty)
- Create: `src/pages/__index__.py`
- Create: `src/pages/README.md`
- Create: `src/pages/__shared__/base.html`
- Create: `src/pages/__shared__/error_403.html`
- Create: `src/pages/__shared__/error_429.html`
- Create: `src/pages/Auth/__init__.py` (empty)
- Create: `src/pages/Auth/__index__.py`
- Create: `src/pages/Auth/login.html`
- Create: `src/pages/Auth/register.html`
- Create: `src/pages/Auth/style.css`
- Create: `src/pages/Auth/script.js`
- Create: `src/pages/Auth/README.md`
- Test: `tests/test_pages_index.py`
- Test: `tests/test_auth_page.py`

**Interfaces:**
- Consumes: `auth_service.verify_credentials`/`record_login_attempt`/`register_account`/`init_login_manager` (Tasks 4-5); `compute_fingerprint`/`is_new_device`/`record_device` from `src.services.security.fingerprint` (Phase 2); `SecurityEvent`, `db` from `src.models`.
- Produces: `discover_page_modules(pages_dir: Path = PAGES_DIR) -> list[str]`, `register_pages(app: Flask, pages_dir: Path = PAGES_DIR, package_prefix: str = "src.pages") -> None` in `src/pages/__index__.py`. `blueprint` (Flask `Blueprint` named `"auth"`) in `src/pages/Auth/__index__.py`, exposing `GET/POST /login`, `GET/POST /register`, `GET /logout` (prefixed `/auth` once registered).
- Later tasks: Task 7 (`run.py`) calls `register_pages(app)` and registers the 401/403/429 error handlers using `error_403.html`/`error_429.html`.

- [ ] **Step 1: Write `pages/__index__.py` and its failing test**

`src/pages/__init__.py`: empty file.

`src/pages/__index__.py`:
```python
import importlib
from pathlib import Path

from flask import Flask

PAGES_DIR = Path(__file__).resolve().parent


def discover_page_modules(pages_dir: Path = PAGES_DIR) -> list[str]:
    names = []
    for entry in sorted(Path(pages_dir).iterdir()):
        if not entry.is_dir():
            continue
        if entry.name == "__shared__" or entry.name.startswith("__pycache__"):
            continue
        if (entry / "__index__.py").exists():
            names.append(entry.name)
    return names


def _url_prefix_for(folder_name: str) -> str:
    if folder_name.lower() == "overview":
        return "/"
    return f"/{folder_name.lower()}"


def register_pages(
    app: Flask, pages_dir: Path = PAGES_DIR, package_prefix: str = "src.pages"
) -> None:
    for folder_name in discover_page_modules(pages_dir):
        module = importlib.import_module(f"{package_prefix}.{folder_name}.__index__")
        blueprint = getattr(module, "blueprint")
        app.register_blueprint(blueprint, url_prefix=_url_prefix_for(folder_name))
```

(This can't be tested standalone yet — `discover_page_modules` needs at least one real page folder with an `__index__.py` to find. Continue to Step 2, which creates `pages/Auth/`, then Step 6 tests both together.)

- [ ] **Step 2: Write `pages/__shared__/` templates**

`src/pages/__shared__/base.html`:
```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{% block title %}AuthTemplate{% endblock %}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
  <main>
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```

`src/pages/__shared__/error_403.html`:
```html
{% extends "base.html" %}
{% block title %}Access Denied{% endblock %}
{% block content %}
<h1>Access Denied</h1>
<p>You don't have permission to view this page.</p>
{% endblock %}
```

`src/pages/__shared__/error_429.html`:
```html
{% extends "base.html" %}
{% block title %}Too Many Attempts{% endblock %}
{% block content %}
<h1>Too Many Attempts</h1>
<p>Please wait before trying again.</p>
{% endblock %}
```

- [ ] **Step 3: Write `pages/Auth/__index__.py` and its templates/static files**

`src/pages/Auth/__init__.py`: empty file.

`src/pages/Auth/__index__.py`:
```python
from pathlib import Path

from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import login_user, logout_user

from src.models import SecurityEvent, db
from src.services import auth_service
from src.services.security.fingerprint import compute_fingerprint, is_new_device, record_device
from src.utils.config_loader import load_json_config

blueprint = Blueprint(
    "auth",
    __name__,
    template_folder=".",
    static_folder=".",
    static_url_path="/auth/static",
)

_FINGERPRINT_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "config_security_fingerprint.json"
)


@blueprint.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html", error=None)

    username = request.form.get("username", "")
    password = request.form.get("password", "")
    ip_address = request.remote_addr or "unknown"

    account = auth_service.verify_credentials(db.session, username, password)
    auth_service.record_login_attempt(
        db.session, ip_address, account.id if account else None, account is not None
    )

    if account is None:
        return render_template("login.html", error="Invalid username or password"), 401

    fingerprint_config = load_json_config(_FINGERPRINT_CONFIG_PATH)
    fingerprint_hash = compute_fingerprint(
        fingerprint_config,
        request.headers.get("User-Agent", ""),
        request.headers.get("Accept-Language", ""),
        ip_address,
    )
    if is_new_device(db.session, account.id, fingerprint_hash):
        db.session.add(
            SecurityEvent(
                account_id=account.id,
                event_type="new_device",
                ip_address=ip_address,
                details="First login from this device fingerprint",
            )
        )
        db.session.commit()
    record_device(db.session, account.id, fingerprint_hash)

    login_user(account)
    return redirect("/")


@blueprint.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html", error=None)

    username = request.form.get("username", "")
    email = request.form.get("email", "")
    password = request.form.get("password", "")
    invite_code = request.form.get("invite_code", "")

    account = auth_service.register_account(db.session, username, email, password, invite_code)
    if account is None:
        return render_template("register.html", error="Invalid or expired invite code"), 400

    return redirect(url_for("auth.login"))


@blueprint.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
```

`src/pages/Auth/login.html`:
```html
{% extends "base.html" %}
{% block title %}Log In{% endblock %}
{% block content %}
<link rel="stylesheet" href="{{ url_for('auth.static', filename='style.css') }}">
<h1>Log In</h1>
{% if error %}<p class="error">{{ error }}</p>{% endif %}
<form method="post" action="{{ url_for('auth.login') }}" data-auth-form>
  <input type="hidden" name="csrf_token" value="{{ csrf_token() if csrf_token is defined else '' }}">
  <label for="username">Username</label>
  <input type="text" id="username" name="username" required autofocus>
  <label for="password">Password</label>
  <input type="password" id="password" name="password" required>
  <button type="submit">Log In</button>
</form>
<p><a href="{{ url_for('auth.register') }}">Have an invite code? Register</a></p>
<script src="{{ url_for('auth.static', filename='script.js') }}"></script>
{% endblock %}
```

`src/pages/Auth/register.html`:
```html
{% extends "base.html" %}
{% block title %}Register{% endblock %}
{% block content %}
<link rel="stylesheet" href="{{ url_for('auth.static', filename='style.css') }}">
<h1>Register</h1>
{% if error %}<p class="error">{{ error }}</p>{% endif %}
<form method="post" action="{{ url_for('auth.register') }}" data-auth-form>
  <input type="hidden" name="csrf_token" value="{{ csrf_token() if csrf_token is defined else '' }}">
  <label for="username">Username</label>
  <input type="text" id="username" name="username" required autofocus>
  <label for="email">Email</label>
  <input type="email" id="email" name="email" required>
  <label for="password">Password</label>
  <input type="password" id="password" name="password" required>
  <label for="invite_code">Invite Code</label>
  <input type="text" id="invite_code" name="invite_code" required>
  <button type="submit">Register</button>
</form>
<p><a href="{{ url_for('auth.login') }}">Already have an account? Log in</a></p>
<script src="{{ url_for('auth.static', filename='script.js') }}"></script>
{% endblock %}
```

`src/pages/Auth/style.css`:
```css
body {
  font-family: system-ui, sans-serif;
  max-width: 360px;
  margin: 4rem auto;
}

form {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

label {
  font-size: 0.85rem;
  font-weight: 600;
}

input, button {
  padding: 0.5rem;
  font-size: 1rem;
}

.error {
  color: #b00020;
}
```

`src/pages/Auth/script.js`:
```javascript
document.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector("form[data-auth-form]");
  if (!form) return;
  form.addEventListener("submit", () => {
    const submitButton = form.querySelector("button[type='submit']");
    if (submitButton) {
      submitButton.disabled = true;
    }
  });
});
```

- [ ] **Step 4: Write `pages/Auth/README.md` and `pages/README.md`**

`src/pages/Auth/README.md`:
```markdown
# pages/Auth/

Merged login/registration/logout flow (spec §6, §7). URL prefix: `/auth`
(via `pages/__index__.py` auto-discovery).

## Routes

- `GET /auth/login`, `POST /auth/login` — the one application login.
  On success: verifies credentials (`auth_service.verify_credentials`),
  records a `LoginAttempt`, computes a device fingerprint and logs a
  `SecurityEvent` if it's new for the account, then issues the
  Flask-Login session and redirects to `/` (the Overview page, added in
  a later phase — until then this 404s, which is expected).
- `GET /auth/register`, `POST /auth/register` — OTP-gated registration.
  Requires a valid, unexpired, unused invite code
  (`auth_service.register_account` → `otp_service`). New accounts get
  **no roles** by default.
- `GET /auth/logout` — clears the Flask-Login session, redirects to
  `/auth/login`.

## Permissions

None — every route here is intentionally reachable without
authentication (that's the point of a login/registration page).

## Templates

`login.html` and `register.html` (not a single `view.html`, since this
page has two distinct forms) both extend `__shared__/base.html`. No
sidebar — the sidebar is for authenticated pages (added in a later
phase); this page renders standalone.
```

`src/pages/README.md`:
```markdown
# src/pages/

Each subfolder is one page: a Flask blueprint auto-discovered and
registered by `__index__.py` at app-boot time (see `register_pages()`).

## Convention

- A page folder must contain an `__index__.py` exposing a `blueprint`
  attribute (a Flask `Blueprint`).
- The URL prefix is derived from the lowercased folder name
  (`Auth` → `/auth`, `Account` → `/account`, `Admin` → `/admin`) — with
  one exception: `Overview` maps to `/`, since it's the post-login
  landing page.
- `__shared__/` is excluded from discovery — it holds `base.html` (and
  the shared error pages), the layout every page's templates extend,
  not a page itself.
- Adding a new page means adding one folder here (with its own
  README) — this file just needs one new line in the index below.

## Pages

- [`Auth/`](Auth/README.md) — the merged login/registration/logout flow.
- Overview, Account, Admin — added in later phases.
```

- [ ] **Step 5: Write the failing tests**

`tests/test_pages_index.py`:
```python
from src.pages.__index__ import discover_page_modules


def test_discover_page_modules_finds_auth_and_skips_shared():
    modules = discover_page_modules()

    assert "Auth" in modules
    assert "__shared__" not in modules
```

`tests/test_auth_page.py`:
```python
from pathlib import Path

from flask import Flask
from werkzeug.security import generate_password_hash

from src.models import Account, LoginAttempt, SecurityEvent, db
from src.pages.__index__ import register_pages
from src.services import otp_service
from src.services.auth_service import init_login_manager

_SHARED_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "src" / "pages" / "__shared__"


def _build_auth_test_app(tmp_path):
    app = Flask(__name__, template_folder=str(_SHARED_TEMPLATES_DIR))
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'auth_test.db'}"
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["SECRET_KEY"] = "test-secret"

    db.init_app(app)
    with app.app_context():
        db.create_all()

    init_login_manager(app)
    register_pages(app)

    return app


def test_login_page_renders(tmp_path):
    app = _build_auth_test_app(tmp_path)
    client = app.test_client()

    response = client.get("/auth/login")

    assert response.status_code == 200
    assert b"Log In" in response.data


def test_register_page_renders(tmp_path):
    app = _build_auth_test_app(tmp_path)
    client = app.test_client()

    response = client.get("/auth/register")

    assert response.status_code == 200
    assert b"Register" in response.data


def test_register_with_valid_invite_creates_account(tmp_path):
    app = _build_auth_test_app(tmp_path)

    with app.app_context():
        inviter = Account(username="admin", email="admin@example.com", password_hash="hashed")
        db.session.add(inviter)
        db.session.commit()
        _, code = otp_service.create_invite(db.session, inviter.id, "new@example.com", "manual")

    client = app.test_client()
    response = client.post(
        "/auth/register",
        data={
            "username": "newperson",
            "email": "new@example.com",
            "password": "s3cret!",
            "invite_code": code,
        },
    )

    assert response.status_code == 302
    with app.app_context():
        created = db.session.query(Account).filter_by(username="newperson").one()
        assert created.roles == []


def test_register_with_invalid_invite_fails(tmp_path):
    app = _build_auth_test_app(tmp_path)
    client = app.test_client()

    response = client.post(
        "/auth/register",
        data={"username": "nope", "email": "nope@example.com", "password": "pw", "invite_code": "bad-code"},
    )

    assert response.status_code == 400


def test_login_with_correct_credentials_redirects_and_sets_session(tmp_path):
    app = _build_auth_test_app(tmp_path)

    with app.app_context():
        account = Account(
            username="loginuser",
            email="loginuser@example.com",
            password_hash=generate_password_hash("correct-password"),
        )
        db.session.add(account)
        db.session.commit()

    client = app.test_client()
    response = client.post("/auth/login", data={"username": "loginuser", "password": "correct-password"})

    assert response.status_code == 302
    assert response.headers["Location"] == "/"

    with client.session_transaction() as flask_session:
        assert "_user_id" in flask_session


def test_login_with_wrong_password_fails(tmp_path):
    app = _build_auth_test_app(tmp_path)

    with app.app_context():
        account = Account(
            username="wrongpw",
            email="wrongpw@example.com",
            password_hash=generate_password_hash("correct-password"),
        )
        db.session.add(account)
        db.session.commit()

    client = app.test_client()
    response = client.post("/auth/login", data={"username": "wrongpw", "password": "not-it"})

    assert response.status_code == 401


def test_login_records_login_attempt(tmp_path):
    app = _build_auth_test_app(tmp_path)

    with app.app_context():
        account = Account(
            username="attemptuser",
            email="attemptuser@example.com",
            password_hash=generate_password_hash("correct-password"),
        )
        db.session.add(account)
        db.session.commit()

    client = app.test_client()
    client.post("/auth/login", data={"username": "attemptuser", "password": "correct-password"})

    with app.app_context():
        attempts = db.session.query(LoginAttempt).filter_by(success=True).all()

    assert len(attempts) == 1


def test_login_logs_new_device_security_event(tmp_path):
    app = _build_auth_test_app(tmp_path)

    with app.app_context():
        account = Account(
            username="deviceuser",
            email="deviceuser@example.com",
            password_hash=generate_password_hash("correct-password"),
        )
        db.session.add(account)
        db.session.commit()

    client = app.test_client()
    client.post("/auth/login", data={"username": "deviceuser", "password": "correct-password"})

    with app.app_context():
        events = db.session.query(SecurityEvent).filter_by(event_type="new_device").all()

    assert len(events) == 1


def test_logout_clears_session(tmp_path):
    app = _build_auth_test_app(tmp_path)

    with app.app_context():
        account = Account(
            username="logoutuser",
            email="logoutuser@example.com",
            password_hash=generate_password_hash("correct-password"),
        )
        db.session.add(account)
        db.session.commit()

    client = app.test_client()
    client.post("/auth/login", data={"username": "logoutuser", "password": "correct-password"})
    client.get("/auth/logout")

    with client.session_transaction() as flask_session:
        assert "_user_id" not in flask_session
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest tests/test_pages_index.py tests/test_auth_page.py -v`
Expected: PASS (1 + 9 = 10 tests)

- [ ] **Step 7: Commit**

```bash
git add src/pages tests/test_pages_index.py tests/test_auth_page.py
git commit -m "feat: add page auto-discovery and Auth blueprint (login/register/logout)"
```

---

### Task 7: Wire everything into `create_app`

**Files:**
- Modify: `src/run.py`
- Modify: `src/services/README.md`

**Interfaces:**
- Consumes: `register_pages` (Task 6), `init_login_manager`/`ensure_bootstrap_admin` (Tasks 4-5), `register_security_pipeline` (Phase 2), `db` (Phase 1). `create_app(config: dict | None = None) -> Flask` signature unchanged.

- [ ] **Step 1: Modify `src/run.py` (full replacement)**

`src/run.py`:
```python
from pathlib import Path

from flask import Flask, redirect, render_template, url_for

from src.models import db
from src.pages.__index__ import register_pages
from src.services.auth_service import ensure_bootstrap_admin, init_login_manager
from src.services.security.pipeline import load_security_configs, register_security_pipeline
from src.utils.config_loader import load_env_secrets

BASE_DIR = Path(__file__).resolve().parent


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__, template_folder=str(BASE_DIR / "pages" / "__shared__"))

    app_secrets = load_env_secrets(BASE_DIR / "secrets" / "secret_app.env")
    db_secrets = load_env_secrets(BASE_DIR / "secrets" / "secret_db.env")

    app.config["SECRET_KEY"] = app_secrets.get("SECRET_KEY") or "dev-insecure-key-change-me"
    app.config["SQLALCHEMY_DATABASE_URI"] = db_secrets.get("DATABASE_URL") or (
        f"sqlite:///{BASE_DIR / 'data' / 'app.db'}"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    if config:
        app.config.update(config)

    (BASE_DIR / "data").mkdir(parents=True, exist_ok=True)

    db.init_app(app)

    with app.app_context():
        db.create_all()

    security_configs = load_security_configs(BASE_DIR / "configs")
    register_security_pipeline(app, security_configs)

    init_login_manager(app)
    register_pages(app)

    with app.app_context():
        ensure_bootstrap_admin(db.session, BASE_DIR / "secrets")

    @app.errorhandler(401)
    def handle_unauthorized(_error):
        return redirect(url_for("auth.login"))

    @app.errorhandler(403)
    def handle_forbidden(_error):
        return render_template("error_403.html"), 403

    @app.errorhandler(429)
    def handle_rate_limited(_error):
        return render_template("error_429.html"), 429

    return app


if __name__ == "__main__":
    flask_app = create_app()
    flask_app.run(debug=True)
```

**Before writing this file, `Read` the current `src/run.py`** — a prior session added a `(BASE_DIR / "data").mkdir(parents=True, exist_ok=True)` fix before `db.init_app(app)` that isn't reflected in Phase 1/2's plan docs. The block above already includes it; if the live file has additional unrelated changes, merge them in rather than blindly overwriting.

- [ ] **Step 2: Run the full test suite**

Run: `pytest -v`
Expected: PASS (every test from Phase 1, Phase 2, and this plan's Tasks 1-6 — Phase 1's `tests/test_app_factory.py` tests still pass: `ensure_bootstrap_admin` creates an `admin` account when the table is empty, but `test_create_app_initializes_tables`'s `filter_by(username="dave").one()` only matches its own row, so the extra `admin` row doesn't break it)

- [ ] **Step 3: Update `src/services/README.md`**

Replace the four "(added in a later phase)" lines for `auth_service.py`, `otp_service.py`, and `authz.py` with their real descriptions:

```markdown
- `auth_service.py` — `login_manager` (Flask-Login singleton),
  `init_login_manager()`, `verify_credentials()`, `record_login_attempt()`,
  `register_account()`, and `ensure_bootstrap_admin()` (self-healing:
  syncs the `Administrator` role's permissions to match
  `authz.registered_permissions()` on every boot, not just first run).
- `otp_service.py` — `create_invite()`, `find_valid_invite()`,
  `consume_invite()`: the registration-gate OTP lifecycle.
- `authz.py` — `require_permission()` decorator (401 if unauthenticated,
  403 if authenticated but lacking the permission), plus
  `registered_permissions()` / `account_permissions()` / `has_permission()`.
```

Leave the `email_service.py` and `admin_service.py` lines as "(added in a later phase)" — those are Phase 4.

- [ ] **Step 4: Commit**

```bash
git add src/run.py src/services/README.md
git commit -m "feat: wire login manager, pages, bootstrap admin, and error handlers into create_app"
```

---

## Out of Scope for This Plan (later phases)

- `admin_service`, `email_service`, the Admin page (roles/permissions/invites management UI) — Phase 4.
- Overview page (post-login landing/page-picker) and Account page (profile management), plus the authenticated sidebar in `__shared__/` — Phase 5.
- Root `README.md` — Phase 6, once Overview/Account/Admin exist and the abstract permission/role/registration model can be described accurately.
- pytest fixtures/factories exactly matching spec §16's described shape (factory for accounts/roles/permissions, configurable security pipeline per test) — the existing `app` fixture plus this plan's ad-hoc `_build_auth_test_app` helper cover Phase 1-3; a shared factory module can be extracted in Phase 6 if duplication across test files becomes a problem.
