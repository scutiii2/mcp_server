# AuthTemplate Admin & Invites Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build role/permission/account administration (`admin_service`), OTP-email delivery (`email_service`), and the Admin page — the one place roles are created, permissions granted/revoked, roles assigned/removed on accounts (protected accounts guarded against role-stripping), and invites generated (manual on-screen code, or auto-emailed). This is Phase 4 of a multi-phase build, depending on the models (Phase 1), security pipeline (Phase 2), and auth core — `authz`, `otp_service`, page auto-discovery, `__shared__/base.html` (Phase 3: [2026-08-21-authtemplate-auth-core.md](2026-08-21-authtemplate-auth-core.md)).

**Architecture:** `admin_service.py` holds pure DB-backed operations (create role, grant/revoke permission, assign/remove role on an account), validated against `authz.registered_permissions()` and guarded by a `ProtectedAccountError` for `is_protected` accounts. `email_service.py` wraps Flask-Mail, configured from `secret_smtp.env`, independently testable via Flask-Mail's `record_messages()` test helper (no real SMTP needed). `pages/Admin/` is one dashboard page (single `view.html`, not split across routes) gated by `admin.roles.manage` — except invite generation, which spec §7 ties to the distinct `auth.invite` permission instead.

**Tech Stack:** Flask-Mail (`Mail`, `Message`, `record_messages()` for tests), Flask's `flash()`/`get_flashed_messages()` for one-time invite-code display across a redirect, pytest with Flask's test client.

**Spec:** [docs/superpowers/specs/2026-08-21-authtemplate-design.md](../specs/2026-08-21-authtemplate-design.md)

## Global Constraints

- `is_protected` blocks deletion and role stripping (spec §5) — `admin_service.remove_role_from_account` must refuse (raise `ProtectedAccountError`) rather than silently succeed or silently no-op.
- Only accounts holding `auth.invite` can generate an invite (spec §7) — a **distinct** permission from `admin.roles.manage`, which gates the rest of the Admin page (spec §10).
- Inviter picks delivery per invite: auto-email (Flask-Mail) or manual on-screen code — both supported, chosen per invite (spec §7).
- Permissions are namespaced strings, discovered via `@require_permission` — `admin_service.assign_permission_to_role` must reject a `permission_name` that isn't in `authz.registered_permissions()` (spec §5, §10); granting an unregistered string would be meaningless (no route ever checks it).
- Registering with a valid OTP still creates accounts with **no roles** (spec §7, unchanged from Phase 3) — Admin is where those roles get assigned afterward.
- Each `.env` file loaded independently via `dotenv_values()` into its own dict (spec §8) — `email_service.init_mail` loads `secret_smtp.env` the same way `run.py` already loads `secret_app.env`/`secret_db.env`.
- Documentation is distributed per folder (spec §17) — `src/pages/Admin/README.md` must exist; `src/pages/README.md` and `src/services/README.md` get their "(added in a later phase)" placeholders for Admin/`admin_service`/`email_service` replaced.
- `src/run.py`'s `create_app(config: dict | None = None) -> Flask` signature does not change.
- No placeholders, no TODOs.

---

## File Structure

```
src/
  services/
    admin_service.py               # list_roles, list_accounts, create_role,
                                    #   assign_permission_to_role, remove_permission_from_role,
                                    #   assign_role_to_account, remove_role_from_account,
                                    #   ProtectedAccountError
    email_service.py                # mail, init_mail, send_invite_email
  pages/
    Admin/
      __init__.py                   # empty, package marker
      __index__.py                   # blueprint: dashboard + role/permission/account/invite actions
      view.html
      style.css
      README.md
    README.md                        # MODIFIED: Admin added to the index
  run.py                              # MODIFIED: wires email_service.init_mail
  services/
    README.md                        # MODIFIED: admin_service/email_service descriptions filled in
tests/
  test_admin_service.py
  test_email_service.py
  test_admin_page.py
```

---

### Task 1: Role/permission/account admin operations

**Files:**
- Create: `src/services/admin_service.py`
- Test: `tests/test_admin_service.py`

**Interfaces:**
- Consumes: `Account`, `Permission`, `Role`, `db` from `src.models`; `registered_permissions` from `src.services.authz` (Phase 3).
- Produces: `ProtectedAccountError` (exception), `list_roles(db_session) -> list[Role]`, `list_accounts(db_session) -> list[Account]`, `create_role(db_session, name: str, description: str | None) -> Role`, `assign_permission_to_role(db_session, role: Role, permission_name: str) -> Permission`, `remove_permission_from_role(db_session, role: Role, permission_name: str) -> None`, `assign_role_to_account(db_session, account: Account, role: Role) -> None`, `remove_role_from_account(db_session, account: Account, role: Role) -> None` (raises `ProtectedAccountError` if `account.is_protected`) in `src/services/admin_service.py`.
- Later tasks: Task 3 (`pages/Admin`) imports everything from this module.

- [ ] **Step 1: Write the failing test**

`tests/test_admin_service.py`:
```python
import pytest

from src.models import Account, Permission, Role, db
from src.services import admin_service
from src.services.authz import require_permission


def test_create_role_persists(app):
    with app.app_context():
        role = admin_service.create_role(db.session, "editor", "Can edit content")

        assert role.id is not None
        fetched = db.session.query(Role).filter_by(name="editor").one()
        assert fetched.description == "Can edit content"


def test_list_roles_returns_all_roles_sorted_by_name(app):
    with app.app_context():
        db.session.add(Role(name="zeta"))
        db.session.add(Role(name="alpha"))
        db.session.commit()

        roles = admin_service.list_roles(db.session)

        assert [r.name for r in roles] == ["alpha", "zeta"]


def test_list_accounts_returns_all_accounts_sorted_by_username(app):
    with app.app_context():
        db.session.add(Account(username="zed", email="zed@example.com", password_hash="hashed"))
        db.session.add(Account(username="amy", email="amy@example.com", password_hash="hashed"))
        db.session.commit()

        accounts = admin_service.list_accounts(db.session)

        assert [a.username for a in accounts] == ["amy", "zed"]


def test_assign_permission_to_role_creates_permission_if_missing(app):
    @require_permission("admin_test.grant_action")
    def _dummy_view():
        return "ok"

    with app.app_context():
        role = Role(name="grantee")
        db.session.add(role)
        db.session.commit()

        permission = admin_service.assign_permission_to_role(db.session, role, "admin_test.grant_action")

        assert permission.name == "admin_test.grant_action"
        fetched_role = db.session.query(Role).filter_by(name="grantee").one()
        assert [p.name for p in fetched_role.permissions] == ["admin_test.grant_action"]


def test_assign_permission_to_role_is_idempotent(app):
    @require_permission("admin_test.idempotent_action")
    def _dummy_view():
        return "ok"

    with app.app_context():
        role = Role(name="idempotent_role")
        db.session.add(role)
        db.session.commit()

        admin_service.assign_permission_to_role(db.session, role, "admin_test.idempotent_action")
        admin_service.assign_permission_to_role(db.session, role, "admin_test.idempotent_action")

        fetched_role = db.session.query(Role).filter_by(name="idempotent_role").one()
        assert len(fetched_role.permissions) == 1


def test_assign_permission_to_role_rejects_unregistered_permission(app):
    with app.app_context():
        role = Role(name="strict_role")
        db.session.add(role)
        db.session.commit()

        with pytest.raises(ValueError):
            admin_service.assign_permission_to_role(db.session, role, "totally.made_up_permission")


def test_remove_permission_from_role(app):
    with app.app_context():
        role = Role(name="revokee")
        permission = Permission(name="revoke_test.action")
        role.permissions.append(permission)
        db.session.add(role)
        db.session.commit()

        admin_service.remove_permission_from_role(db.session, role, "revoke_test.action")

        fetched_role = db.session.query(Role).filter_by(name="revokee").one()
        assert fetched_role.permissions == []


def test_assign_role_to_account(app):
    with app.app_context():
        account = Account(username="member", email="member@example.com", password_hash="hashed")
        role = Role(name="member_role")
        db.session.add_all([account, role])
        db.session.commit()

        admin_service.assign_role_to_account(db.session, account, role)

        fetched_account = db.session.query(Account).filter_by(username="member").one()
        assert [r.name for r in fetched_account.roles] == ["member_role"]


def test_remove_role_from_account(app):
    with app.app_context():
        account = Account(username="leaving", email="leaving@example.com", password_hash="hashed")
        role = Role(name="leaving_role")
        account.roles.append(role)
        db.session.add(account)
        db.session.commit()

        admin_service.remove_role_from_account(db.session, account, role)

        fetched_account = db.session.query(Account).filter_by(username="leaving").one()
        assert fetched_account.roles == []


def test_remove_role_from_account_raises_for_protected_account(app):
    with app.app_context():
        account = Account(
            username="untouchable",
            email="untouchable@example.com",
            password_hash="hashed",
            is_protected=True,
        )
        role = Role(name="untouchable_role")
        account.roles.append(role)
        db.session.add(account)
        db.session.commit()

        with pytest.raises(admin_service.ProtectedAccountError):
            admin_service.remove_role_from_account(db.session, account, role)

        fetched_account = db.session.query(Account).filter_by(username="untouchable").one()
        assert [r.name for r in fetched_account.roles] == ["untouchable_role"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_admin_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.services.admin_service'`

- [ ] **Step 3: Implement `admin_service.py`**

`src/services/admin_service.py`:
```python
from src.models import Account, Permission, Role
from src.services.authz import registered_permissions


class ProtectedAccountError(Exception):
    pass


def list_roles(db_session) -> list[Role]:
    return db_session.query(Role).order_by(Role.name).all()


def list_accounts(db_session) -> list[Account]:
    return db_session.query(Account).order_by(Account.username).all()


def create_role(db_session, name: str, description: str | None) -> Role:
    role = Role(name=name, description=description)
    db_session.add(role)
    db_session.commit()
    return role


def assign_permission_to_role(db_session, role: Role, permission_name: str) -> Permission:
    if permission_name not in registered_permissions():
        raise ValueError(f"Unknown permission: {permission_name}")

    permission = db_session.query(Permission).filter_by(name=permission_name).first()
    if permission is None:
        permission = Permission(name=permission_name)
        db_session.add(permission)
    if permission not in role.permissions:
        role.permissions.append(permission)
    db_session.commit()
    return permission


def remove_permission_from_role(db_session, role: Role, permission_name: str) -> None:
    role.permissions = [p for p in role.permissions if p.name != permission_name]
    db_session.commit()


def assign_role_to_account(db_session, account: Account, role: Role) -> None:
    if role not in account.roles:
        account.roles.append(role)
    db_session.commit()


def remove_role_from_account(db_session, account: Account, role: Role) -> None:
    if account.is_protected:
        raise ProtectedAccountError(
            f"Account '{account.username}' is protected; its roles cannot be stripped"
        )
    account.roles = [r for r in account.roles if r.id != role.id]
    db_session.commit()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_admin_service.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add src/services/admin_service.py tests/test_admin_service.py
git commit -m "feat: add role/permission/account admin operations"
```

---

### Task 2: OTP email delivery

**Files:**
- Create: `src/services/email_service.py`
- Test: `tests/test_email_service.py`

**Interfaces:**
- Consumes: `load_env_secrets` from `src.utils.config_loader` (Phase 1).
- Produces: `mail` (module-level Flask-Mail `Mail` singleton, mirroring the `db`/`login_manager` pattern), `init_mail(app: Flask, secrets_dir) -> None`, `send_invite_email(invitee_email: str, code: str, expires_at) -> None` in `src/services/email_service.py`.
- Later tasks: Task 3 (`pages/Admin`) calls `send_invite_email`. Task 4 (`run.py`) calls `init_mail`.

- [ ] **Step 1: Write the failing test**

`tests/test_email_service.py`:
```python
from datetime import datetime, timedelta, timezone

from flask import Flask

from src.services.email_service import init_mail, mail, send_invite_email


def _build_mail_test_app(tmp_path, secrets_dir):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["MAIL_SUPPRESS_SEND"] = True
    init_mail(app, secrets_dir)
    return app


def test_init_mail_uses_configured_smtp_settings(tmp_path):
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "secret_smtp.env").write_text(
        "SMTP_HOST=smtp.example.com\n"
        "SMTP_PORT=2525\n"
        "SMTP_USERNAME=bot\n"
        "SMTP_PASSWORD=hunter2\n"
        "SMTP_USE_TLS=false\n"
        "MAIL_FROM_ADDRESS=noreply@example.com\n"
    )

    app = _build_mail_test_app(tmp_path, secrets_dir)

    assert app.config["MAIL_SERVER"] == "smtp.example.com"
    assert app.config["MAIL_PORT"] == 2525
    assert app.config["MAIL_USERNAME"] == "bot"
    assert app.config["MAIL_USE_TLS"] is False
    assert app.config["MAIL_DEFAULT_SENDER"] == "noreply@example.com"


def test_init_mail_falls_back_to_defaults_when_secrets_missing(tmp_path):
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()

    app = _build_mail_test_app(tmp_path, secrets_dir)

    assert app.config["MAIL_SERVER"] == "localhost"
    assert app.config["MAIL_USE_TLS"] is True


def test_send_invite_email_sends_message_with_code(tmp_path):
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    app = _build_mail_test_app(tmp_path, secrets_dir)

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)

    with app.app_context():
        with mail.record_messages() as outbox:
            send_invite_email("invitee@example.com", "abc123code", expires_at)

    assert len(outbox) == 1
    sent = outbox[0]
    assert sent.recipients == ["invitee@example.com"]
    assert "abc123code" in sent.body
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_email_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.services.email_service'`

- [ ] **Step 3: Implement `email_service.py`**

`src/services/email_service.py`:
```python
from pathlib import Path

from flask import Flask
from flask_mail import Mail, Message

from src.utils.config_loader import load_env_secrets

mail = Mail()


def init_mail(app: Flask, secrets_dir: Path) -> None:
    smtp_secrets = load_env_secrets(Path(secrets_dir) / "secret_smtp.env")

    app.config["MAIL_SERVER"] = smtp_secrets.get("SMTP_HOST") or "localhost"
    app.config["MAIL_PORT"] = int(smtp_secrets.get("SMTP_PORT") or 587)
    app.config["MAIL_USERNAME"] = smtp_secrets.get("SMTP_USERNAME") or None
    app.config["MAIL_PASSWORD"] = smtp_secrets.get("SMTP_PASSWORD") or None
    app.config["MAIL_USE_TLS"] = (smtp_secrets.get("SMTP_USE_TLS") or "true").lower() == "true"
    app.config["MAIL_DEFAULT_SENDER"] = smtp_secrets.get("MAIL_FROM_ADDRESS") or "no-reply@example.com"

    mail.init_app(app)


def send_invite_email(invitee_email: str, code: str, expires_at) -> None:
    message = Message(
        subject="You're invited",
        recipients=[invitee_email],
        body=(
            "You've been invited to register.\n\n"
            f"Invite code: {code}\n"
            f"This code expires at {expires_at.isoformat()} and can only be used once.\n"
        ),
    )
    mail.send(message)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_email_service.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/services/email_service.py tests/test_email_service.py
git commit -m "feat: add OTP invite email delivery via Flask-Mail"
```

---

### Task 3: Admin page (roles, permissions, accounts, invites)

**Files:**
- Create: `src/pages/Admin/__init__.py` (empty)
- Create: `src/pages/Admin/__index__.py`
- Create: `src/pages/Admin/view.html`
- Create: `src/pages/Admin/style.css`
- Create: `src/pages/Admin/README.md`
- Modify: `src/pages/README.md`
- Test: `tests/test_admin_page.py`

**Interfaces:**
- Consumes: `admin_service.*` (Task 1), `email_service.send_invite_email` (Task 2), `otp_service.create_invite` (Phase 3), `require_permission`/`registered_permissions` from `src.services.authz` (Phase 3), `discover_page_modules`/`register_pages` from `src.pages.__index__` (Phase 3).
- Produces: `blueprint` (Flask `Blueprint` named `"admin"`) in `src/pages/Admin/__index__.py`, exposing `GET /` (dashboard), `POST /roles`, `POST /roles/<int:role_id>/permissions`, `POST /roles/<int:role_id>/permissions/remove`, `POST /accounts/<int:account_id>/roles`, `POST /accounts/<int:account_id>/roles/remove`, `POST /invites` (prefixed `/admin` once registered).
- Every route except `/invites` requires `admin.roles.manage`; `/invites` requires `auth.invite` specifically (spec §7 vs §10 — see Global Constraints).

- [ ] **Step 1: Write `pages/Admin/__index__.py`**

`src/pages/Admin/__init__.py`: empty file.

`src/pages/Admin/__index__.py`:
```python
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user

from src.models import Account, InviteOTP, Role, db
from src.services import admin_service, email_service, otp_service
from src.services.authz import registered_permissions, require_permission

blueprint = Blueprint(
    "admin",
    __name__,
    template_folder=".",
    static_folder=".",
    static_url_path="/admin/static",
)


@blueprint.route("/")
@require_permission("admin.roles.manage")
def dashboard():
    roles = admin_service.list_roles(db.session)
    accounts = admin_service.list_accounts(db.session)
    invites = db.session.query(InviteOTP).order_by(InviteOTP.created_at.desc()).limit(20).all()
    return render_template(
        "view.html",
        roles=roles,
        accounts=accounts,
        invites=invites,
        available_permissions=sorted(registered_permissions()),
    )


@blueprint.route("/roles", methods=["POST"])
@require_permission("admin.roles.manage")
def create_role():
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip() or None
    if not name:
        flash("Role name is required")
    else:
        admin_service.create_role(db.session, name, description)
        flash(f"Role '{name}' created")
    return redirect(url_for("admin.dashboard"))


@blueprint.route("/roles/<int:role_id>/permissions", methods=["POST"])
@require_permission("admin.roles.manage")
def assign_permission(role_id):
    role = db.session.get(Role, role_id)
    permission_name = request.form.get("permission_name", "")
    if role is None:
        flash("Role not found")
    else:
        try:
            admin_service.assign_permission_to_role(db.session, role, permission_name)
            flash(f"Granted '{permission_name}' to role '{role.name}'")
        except ValueError as error:
            flash(str(error))
    return redirect(url_for("admin.dashboard"))


@blueprint.route("/roles/<int:role_id>/permissions/remove", methods=["POST"])
@require_permission("admin.roles.manage")
def remove_permission(role_id):
    role = db.session.get(Role, role_id)
    permission_name = request.form.get("permission_name", "")
    if role is None:
        flash("Role not found")
    else:
        admin_service.remove_permission_from_role(db.session, role, permission_name)
        flash(f"Revoked '{permission_name}' from role '{role.name}'")
    return redirect(url_for("admin.dashboard"))


@blueprint.route("/accounts/<int:account_id>/roles", methods=["POST"])
@require_permission("admin.roles.manage")
def assign_role(account_id):
    account = db.session.get(Account, account_id)
    role_id = request.form.get("role_id", type=int)
    role = db.session.get(Role, role_id) if role_id else None
    if account is None or role is None:
        flash("Account or role not found")
    else:
        admin_service.assign_role_to_account(db.session, account, role)
        flash(f"Assigned role '{role.name}' to '{account.username}'")
    return redirect(url_for("admin.dashboard"))


@blueprint.route("/accounts/<int:account_id>/roles/remove", methods=["POST"])
@require_permission("admin.roles.manage")
def remove_role(account_id):
    account = db.session.get(Account, account_id)
    role_id = request.form.get("role_id", type=int)
    role = db.session.get(Role, role_id) if role_id else None
    if account is None or role is None:
        flash("Account or role not found")
    else:
        try:
            admin_service.remove_role_from_account(db.session, account, role)
            flash(f"Removed role '{role.name}' from '{account.username}'")
        except admin_service.ProtectedAccountError as error:
            flash(str(error))
    return redirect(url_for("admin.dashboard"))


@blueprint.route("/invites", methods=["POST"])
@require_permission("auth.invite")
def create_invite():
    invitee_email = request.form.get("invitee_email", "").strip() or None
    delivery_method = request.form.get("delivery_method", "manual")

    invite, code = otp_service.create_invite(
        db.session, current_user.id, invitee_email, delivery_method
    )

    if delivery_method == "email" and invitee_email:
        email_service.send_invite_email(invitee_email, code, invite.expires_at)
        flash(f"Invite emailed to {invitee_email}")
    else:
        flash(f"Invite code (copy and share manually — shown once): {code}")

    return redirect(url_for("admin.dashboard"))
```

- [ ] **Step 2: Write the templates and static files**

`src/pages/Admin/view.html`:
```html
{% extends "base.html" %}
{% block title %}Admin{% endblock %}
{% block content %}
<link rel="stylesheet" href="{{ url_for('admin.static', filename='style.css') }}">
<h1>Admin</h1>

{% with messages = get_flashed_messages() %}
  {% if messages %}
  <ul class="flash">
    {% for message in messages %}<li>{{ message }}</li>{% endfor %}
  </ul>
  {% endif %}
{% endwith %}

<section>
  <h2>Roles</h2>
  <form method="post" action="{{ url_for('admin.create_role') }}">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() if csrf_token is defined else '' }}">
    <input type="text" name="name" placeholder="Role name" required>
    <input type="text" name="description" placeholder="Description">
    <button type="submit">Create Role</button>
  </form>

  {% for role in roles %}
  <div class="role">
    <h3>{{ role.name }}</h3>
    <p>{{ role.description or "" }}</p>
    <ul>
      {% for permission in role.permissions %}
      <li>
        {{ permission.name }}
        <form method="post" action="{{ url_for('admin.remove_permission', role_id=role.id) }}" class="inline">
          <input type="hidden" name="csrf_token" value="{{ csrf_token() if csrf_token is defined else '' }}">
          <input type="hidden" name="permission_name" value="{{ permission.name }}">
          <button type="submit">Revoke</button>
        </form>
      </li>
      {% endfor %}
    </ul>
    <form method="post" action="{{ url_for('admin.assign_permission', role_id=role.id) }}" class="inline">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() if csrf_token is defined else '' }}">
      <select name="permission_name">
        {% for permission_name in available_permissions %}
        <option value="{{ permission_name }}">{{ permission_name }}</option>
        {% endfor %}
      </select>
      <button type="submit">Grant Permission</button>
    </form>
  </div>
  {% endfor %}
</section>

<section>
  <h2>Accounts</h2>
  {% for account in accounts %}
  <div class="account">
    <h3>{{ account.username }}{% if account.is_protected %} (protected){% endif %}</h3>
    <p>
      Roles:
      {% for role in account.roles %}
      {{ role.name }}
      <form method="post" action="{{ url_for('admin.remove_role', account_id=account.id) }}" class="inline">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() if csrf_token is defined else '' }}">
        <input type="hidden" name="role_id" value="{{ role.id }}">
        <button type="submit" {% if account.is_protected %}disabled{% endif %}>Remove</button>
      </form>
      {% endfor %}
    </p>
    <form method="post" action="{{ url_for('admin.assign_role', account_id=account.id) }}" class="inline">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() if csrf_token is defined else '' }}">
      <select name="role_id">
        {% for role in roles %}
        <option value="{{ role.id }}">{{ role.name }}</option>
        {% endfor %}
      </select>
      <button type="submit">Assign Role</button>
    </form>
  </div>
  {% endfor %}
</section>

<section>
  <h2>Invites</h2>
  <form method="post" action="{{ url_for('admin.create_invite') }}">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() if csrf_token is defined else '' }}">
    <input type="email" name="invitee_email" placeholder="Invitee email (optional for manual delivery)">
    <select name="delivery_method">
      <option value="manual">Manual (show code on screen)</option>
      <option value="email">Auto-email</option>
    </select>
    <button type="submit">Generate Invite</button>
  </form>

  <ul>
    {% for invite in invites %}
    <li>
      {{ invite.invitee_email or "(no email)" }} —
      {% if invite.used_at %}used{% else %}pending{% endif %}
      (expires {{ invite.expires_at }})
    </li>
    {% endfor %}
  </ul>
</section>
{% endblock %}
```

`src/pages/Admin/style.css`:
```css
section {
  margin-bottom: 2rem;
}

.role, .account {
  border: 1px solid #ccc;
  border-radius: 4px;
  padding: 0.75rem;
  margin-bottom: 0.5rem;
}

form.inline {
  display: inline;
}

.flash {
  background: #fff3cd;
  border: 1px solid #ffe69c;
  padding: 0.5rem;
  list-style: none;
}
```

- [ ] **Step 3: Write `pages/Admin/README.md` and update `pages/README.md`**

`src/pages/Admin/README.md`:
```markdown
# pages/Admin/

Role/permission/account administration and invite generation (spec §10).
URL prefix: `/admin`.

## Routes

- `GET /admin/` — dashboard: lists roles (with their permissions),
  accounts (with their roles), and the 20 most recent invites.
- `POST /admin/roles` — create a role (`name`, `description`).
- `POST /admin/roles/<id>/permissions` — grant a permission to a role
  (`permission_name`, must be one `authz.registered_permissions()`
  already knows about — a page has to declare it via
  `@require_permission` before it can be granted).
- `POST /admin/roles/<id>/permissions/remove` — revoke a permission.
- `POST /admin/accounts/<id>/roles` — assign a role to an account
  (`role_id`).
- `POST /admin/accounts/<id>/roles/remove` — remove a role from an
  account. Refuses (flashes an error, no-ops) if the account is
  `is_protected`.
- `POST /admin/invites` — generate an invite (`invitee_email`,
  `delivery_method` = `manual` or `email`). Manual invites flash the
  plaintext code once (never shown again); email invites send it via
  `email_service.send_invite_email` instead.

## Permissions

Every route requires `admin.roles.manage` **except** `/admin/invites`,
which requires `auth.invite` specifically — spec §7 ties invite
generation to that distinct permission, separate from the broader admin
gate. (In this single-dashboard-page implementation, reaching the
invite form still requires `admin.roles.manage` to view the page at
all; a role holding only `auth.invite` has no route to it yet — giving
invite generation its own page is a natural extension for a project
cloning this template.)

## Templates

`view.html` extends `__shared__/base.html`. One page, sectioned into
Roles / Accounts / Invites, rather than three separate pages — kept
together since every action here is an admin action.
```

Update `src/pages/README.md`'s "## Pages" section:
```markdown
## Pages

- [`Auth/`](Auth/README.md) — the merged login/registration/logout flow.
- [`Admin/`](Admin/README.md) — role/permission/account administration
  and invite generation.
- Overview, Account — added in a later phase.
```

- [ ] **Step 4: Write the failing tests**

`tests/test_admin_page.py`:
```python
from pathlib import Path

from flask import Flask

from src.models import Account, InviteOTP, Permission, Role, db
from src.pages.__index__ import register_pages
from src.services.auth_service import init_login_manager
from src.services.email_service import init_mail

_SHARED_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "src" / "pages" / "__shared__"


def _build_admin_test_app(tmp_path):
    app = Flask(__name__, template_folder=str(_SHARED_TEMPLATES_DIR))
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'admin_test.db'}"
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["SECRET_KEY"] = "test-secret"
    app.config["MAIL_SUPPRESS_SEND"] = True

    db.init_app(app)
    with app.app_context():
        db.create_all()

    init_login_manager(app)
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    init_mail(app, secrets_dir)
    register_pages(app)

    return app


def _create_admin_account(app, permission_names):
    with app.app_context():
        role = Role(name="Administrator")
        for name in permission_names:
            permission = db.session.query(Permission).filter_by(name=name).first()
            if permission is None:
                permission = Permission(name=name)
                db.session.add(permission)
            role.permissions.append(permission)
        account = Account(username="boss", email="boss@example.com", password_hash="hashed")
        account.roles.append(role)
        db.session.add(account)
        db.session.commit()
        return account.id


def _login_as(client, account_id):
    with client.session_transaction() as flask_session:
        flask_session["_user_id"] = str(account_id)
        flask_session["_fresh"] = True


def test_dashboard_requires_authentication(tmp_path):
    app = _build_admin_test_app(tmp_path)
    client = app.test_client()

    response = client.get("/admin/")

    assert response.status_code == 401


def test_dashboard_requires_admin_permission(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, [])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/admin/")

    assert response.status_code == 403


def test_dashboard_renders_for_admin(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/admin/")

    assert response.status_code == 200
    assert b"Admin" in response.data
    assert b"boss" in response.data


def test_create_role_via_form(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.post("/admin/roles", data={"name": "editor", "description": "Edits stuff"})

    assert response.status_code == 302
    with app.app_context():
        role = db.session.query(Role).filter_by(name="editor").one()
        assert role.description == "Edits stuff"


def test_assign_and_remove_permission_via_form(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    with app.app_context():
        role = Role(name="target_role")
        db.session.add(role)
        db.session.commit()
        role_id = role.id

    assign_response = client.post(
        f"/admin/roles/{role_id}/permissions", data={"permission_name": "admin.roles.manage"}
    )
    assert assign_response.status_code == 302
    with app.app_context():
        role = db.session.get(Role, role_id)
        assert [p.name for p in role.permissions] == ["admin.roles.manage"]

    remove_response = client.post(
        f"/admin/roles/{role_id}/permissions/remove", data={"permission_name": "admin.roles.manage"}
    )
    assert remove_response.status_code == 302
    with app.app_context():
        role = db.session.get(Role, role_id)
        assert role.permissions == []


def test_assign_and_remove_role_via_form(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    with app.app_context():
        target_account = Account(username="target", email="target@example.com", password_hash="hashed")
        role = Role(name="assignable_role")
        db.session.add_all([target_account, role])
        db.session.commit()
        target_account_id = target_account.id
        role_id = role.id

    assign_response = client.post(
        f"/admin/accounts/{target_account_id}/roles", data={"role_id": role_id}
    )
    assert assign_response.status_code == 302
    with app.app_context():
        target_account = db.session.get(Account, target_account_id)
        assert [r.name for r in target_account.roles] == ["assignable_role"]

    remove_response = client.post(
        f"/admin/accounts/{target_account_id}/roles/remove", data={"role_id": role_id}
    )
    assert remove_response.status_code == 302
    with app.app_context():
        target_account = db.session.get(Account, target_account_id)
        assert target_account.roles == []


def test_remove_role_from_protected_account_is_refused(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    with app.app_context():
        protected_account = Account(
            username="protected_target",
            email="protected_target@example.com",
            password_hash="hashed",
            is_protected=True,
        )
        role = Role(name="protected_role")
        protected_account.roles.append(role)
        db.session.add(protected_account)
        db.session.commit()
        protected_account_id = protected_account.id
        role_id = role.id

    response = client.post(
        f"/admin/accounts/{protected_account_id}/roles/remove", data={"role_id": role_id}
    )

    assert response.status_code == 302
    with app.app_context():
        protected_account = db.session.get(Account, protected_account_id)
        assert [r.name for r in protected_account.roles] == ["protected_role"]


def test_create_invite_requires_auth_invite_permission_not_admin_roles_manage(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.post("/admin/invites", data={"delivery_method": "manual"})

    assert response.status_code == 403


def test_create_manual_invite_persists_invite(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["auth.invite"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.post(
        "/admin/invites", data={"invitee_email": "", "delivery_method": "manual"}
    )

    assert response.status_code == 302
    with app.app_context():
        invites = db.session.query(InviteOTP).filter_by(created_by_account_id=account_id).all()
        assert len(invites) == 1
        assert invites[0].delivery_method == "manual"


def test_create_email_invite_sends_message(tmp_path):
    from src.services.email_service import mail

    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["auth.invite"])
    client = app.test_client()
    _login_as(client, account_id)

    with app.app_context():
        with mail.record_messages() as outbox:
            response = client.post(
                "/admin/invites",
                data={"invitee_email": "invitee@example.com", "delivery_method": "email"},
            )

        assert response.status_code == 302
        assert len(outbox) == 1
        assert outbox[0].recipients == ["invitee@example.com"]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_admin_page.py -v`
Expected: PASS (11 tests)

- [ ] **Step 6: Run the full test suite**

Run: `pytest -v`
Expected: PASS (every test from Phases 1-3 plus this plan's Tasks 1-3)

- [ ] **Step 7: Commit**

```bash
git add src/pages/Admin src/pages/README.md tests/test_admin_page.py
git commit -m "feat: add Admin page (roles, permissions, accounts, invites)"
```

---

### Task 4: Wire email into `create_app` + docs

**Files:**
- Modify: `src/run.py`
- Modify: `src/services/README.md`

**Interfaces:**
- Consumes: `email_service.init_mail` (Task 2). `create_app(config: dict | None = None) -> Flask` signature unchanged.

- [ ] **Step 1: Modify `src/run.py`**

Add the import and one call, alongside the existing pipeline/login-manager/pages wiring:

```python
from src.services.email_service import init_mail
```

Add after `init_login_manager(app)` and before `register_pages(app)` (order doesn't matter between these three, but keep it readable):

```python
    init_login_manager(app)
    init_mail(app, BASE_DIR / "secrets")
    register_pages(app)
```

**Before editing, `Read` the current `src/run.py`** to confirm the exact surrounding lines (Phase 3 already modified this file; match its actual current content rather than assuming).

- [ ] **Step 2: Run the full test suite**

Run: `pytest -v`
Expected: PASS (unchanged count — `run.py` isn't directly tested by name, but `test_app_factory.py`'s `create_app()` calls now also initialize Flask-Mail with no secret file present, which must not raise)

- [ ] **Step 3: Update `src/services/README.md`**

Replace the `admin_service.py` and `email_service.py` "(added in a later phase)" lines:

```markdown
- `admin_service.py` — `list_roles()`, `list_accounts()`, `create_role()`,
  `assign_permission_to_role()` (validated against
  `authz.registered_permissions()`), `remove_permission_from_role()`,
  `assign_role_to_account()`, `remove_role_from_account()` (raises
  `ProtectedAccountError` for `is_protected` accounts).
- `email_service.py` — `mail` (Flask-Mail singleton), `init_mail()`,
  `send_invite_email()`: the auto-email delivery option for invites
  generated on the Admin page.
```

- [ ] **Step 4: Commit**

```bash
git add src/run.py src/services/README.md
git commit -m "feat: wire Flask-Mail into create_app"
```

---

## Out of Scope for This Plan (later phases)

- Overview page (post-login landing/page-picker) and Account page (profile management), plus the authenticated sidebar in `__shared__/` — Phase 5.
- Root `README.md` — Phase 6, once Overview/Account/Admin all exist and the abstract permission/role/registration model can be described accurately.
- Splitting invite generation onto its own page reachable by an `auth.invite`-only role without `admin.roles.manage` — noted as a known simplification in `pages/Admin/README.md`, not addressed here.
