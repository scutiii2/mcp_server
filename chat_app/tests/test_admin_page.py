from pathlib import Path

from flask import Flask

from unittest.mock import patch

from src.models import (
    Account,
    EmailVerificationOtp,
    InviteOTP,
    LogEntry,
    Permission,
    Role,
    db,
)
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
        db.session.add(role)
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


def test_update_role_via_form(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    with app.app_context():
        role = Role(name="editable_role", description="old")
        db.session.add(role)
        db.session.commit()
        role_id = role.id

    response = client.post(
        f"/admin/roles/{role_id}/edit", data={"name": "renamed_role", "description": "new desc"}
    )

    assert response.status_code == 302
    with app.app_context():
        role = db.session.get(Role, role_id)
        assert role.name == "renamed_role"
        assert role.description == "new desc"


def test_update_role_rejects_duplicate_name_via_form(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    with app.app_context():
        db.session.add(Role(name="already_taken"))
        role = Role(name="renaming_target")
        db.session.add(role)
        db.session.commit()
        role_id = role.id

    response = client.post(
        f"/admin/roles/{role_id}/edit", data={"name": "already_taken", "description": ""}
    )

    assert response.status_code == 302
    with app.app_context():
        role = db.session.get(Role, role_id)
        assert role.name == "renaming_target"


def test_update_role_rejects_renaming_administrator_via_form(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    with app.app_context():
        admin_role_id = db.session.query(Role).filter_by(name="Administrator").one().id

    response = client.post(
        f"/admin/roles/{admin_role_id}/edit", data={"name": "NotAdmin", "description": "x"}
    )

    assert response.status_code == 302
    with app.app_context():
        role = db.session.query(Role).filter_by(name="Administrator").one_or_none()
        assert role is not None


def test_update_role_logs_action(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    with app.app_context():
        role = Role(name="log_editable_role")
        db.session.add(role)
        db.session.commit()
        role_id = role.id

    client.post(f"/admin/roles/{role_id}/edit", data={"name": "log_editable_role", "description": "d"})

    with app.app_context():
        entries = db.session.query(LogEntry).filter_by(kind="action", source="admin.update_role").all()
        assert len(entries) == 1
        assert entries[0].account_id == account_id


def test_delete_role_via_form(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    with app.app_context():
        role = Role(name="deletable_via_form")
        db.session.add(role)
        db.session.commit()
        role_id = role.id

    response = client.post(f"/admin/roles/{role_id}/delete")

    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Role, role_id) is None


def test_delete_role_rejects_administrator_via_form(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    with app.app_context():
        admin_role_id = db.session.query(Role).filter_by(name="Administrator").one().id

    response = client.post(f"/admin/roles/{admin_role_id}/delete")

    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Role, admin_role_id) is not None


def test_delete_role_logs_action(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    with app.app_context():
        role = Role(name="log_deletable_role")
        db.session.add(role)
        db.session.commit()
        role_id = role.id

    client.post(f"/admin/roles/{role_id}/delete")

    with app.app_context():
        entries = db.session.query(LogEntry).filter_by(kind="action", source="admin.delete_role").all()
        assert len(entries) == 1
        assert entries[0].account_id == account_id


def test_role_edit_and_delete_redirect_to_roles_tab(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    with app.app_context():
        role = Role(name="redirect_role")
        db.session.add(role)
        db.session.commit()
        role_id = role.id

    edit_response = client.post(
        f"/admin/roles/{role_id}/edit", data={"name": "redirect_role", "description": ""}
    )
    assert edit_response.headers["Location"] == "/admin/?tab=roles"

    delete_response = client.post(f"/admin/roles/{role_id}/delete")
    assert delete_response.headers["Location"] == "/admin/?tab=roles"


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


def test_update_account_via_form(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    with app.app_context():
        target = Account(username="editable_account", email="editable@example.com", password_hash="hashed")
        db.session.add(target)
        db.session.commit()
        target_id = target.id

    response = client.post(
        f"/admin/accounts/{target_id}/edit",
        data={"username": "renamed_account", "email": "renamed@example.com"},
    )

    assert response.status_code == 302
    with app.app_context():
        target = db.session.get(Account, target_id)
        assert target.username == "renamed_account"
        assert target.email == "renamed@example.com"


def test_update_account_refused_for_protected_account(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    with app.app_context():
        protected = Account(
            username="protected_form_edit",
            email="protected_form_edit@example.com",
            password_hash="hashed",
            is_protected=True,
        )
        db.session.add(protected)
        db.session.commit()
        protected_id = protected.id

    response = client.post(
        f"/admin/accounts/{protected_id}/edit",
        data={"username": "renamed", "email": "renamed@example.com"},
    )

    assert response.status_code == 302
    with app.app_context():
        protected = db.session.get(Account, protected_id)
        assert protected.username == "protected_form_edit"


def test_send_verification_sends_email_and_creates_otp(tmp_path):
    from src.services.email_service import mail

    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    with app.app_context():
        target = Account(
            username="unverified_account", email="unverified@example.com", password_hash="hashed"
        )
        db.session.add(target)
        db.session.commit()
        target_id = target.id

    with app.app_context():
        with mail.record_messages() as outbox:
            response = client.post(f"/admin/accounts/{target_id}/verify")

        assert response.status_code == 302
        assert len(outbox) == 1
        assert outbox[0].recipients == ["unverified@example.com"]
        assert db.session.query(EmailVerificationOtp).filter_by(account_id=target_id).count() == 1
        assert db.session.get(Account, target_id).email_verified is False


def test_send_verification_is_noop_for_already_verified_account(tmp_path):
    from src.services.email_service import mail

    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    with app.app_context():
        target = Account(
            username="already_verified",
            email="already_verified@example.com",
            password_hash="hashed",
            email_verified=True,
        )
        db.session.add(target)
        db.session.commit()
        target_id = target.id

    with app.app_context():
        with mail.record_messages() as outbox:
            client.post(f"/admin/accounts/{target_id}/verify")

        assert len(outbox) == 0
        assert db.session.query(EmailVerificationOtp).filter_by(account_id=target_id).count() == 0


def test_send_verification_logs_action(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    with app.app_context():
        target = Account(
            username="log_verify_account", email="log_verify@example.com", password_hash="hashed"
        )
        db.session.add(target)
        db.session.commit()
        target_id = target.id

    client.post(f"/admin/accounts/{target_id}/verify")

    with app.app_context():
        entries = db.session.query(LogEntry).filter_by(
            kind="action", source="admin.send_verification"
        ).all()
        assert len(entries) == 1
        assert entries[0].account_id == account_id


def test_delete_account_via_form(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    with app.app_context():
        target = Account(username="deletable_via_form", email="deletable_via_form@example.com", password_hash="hashed")
        db.session.add(target)
        db.session.commit()
        target_id = target.id

    response = client.post(f"/admin/accounts/{target_id}/delete")

    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Account, target_id) is None


def test_delete_account_refused_for_protected_account(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    with app.app_context():
        protected = Account(
            username="protected_form_delete",
            email="protected_form_delete@example.com",
            password_hash="hashed",
            is_protected=True,
        )
        db.session.add(protected)
        db.session.commit()
        protected_id = protected.id

    response = client.post(f"/admin/accounts/{protected_id}/delete")

    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Account, protected_id) is not None


def test_delete_account_refused_for_self(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.post(f"/admin/accounts/{account_id}/delete")

    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Account, account_id) is not None


def test_account_edit_and_delete_log_actions(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    with app.app_context():
        target = Account(username="log_account", email="log_account@example.com", password_hash="hashed")
        db.session.add(target)
        db.session.commit()
        target_id = target.id

    client.post(
        f"/admin/accounts/{target_id}/edit",
        data={"username": "log_account", "email": "log_account@example.com"},
    )
    client.post(f"/admin/accounts/{target_id}/delete")

    with app.app_context():
        update_entries = db.session.query(LogEntry).filter_by(kind="action", source="admin.update_account").all()
        delete_entries = db.session.query(LogEntry).filter_by(kind="action", source="admin.delete_account").all()
        assert len(update_entries) == 1
        assert len(delete_entries) == 1
        assert update_entries[0].account_id == account_id
        assert delete_entries[0].account_id == account_id


def test_account_actions_redirect_to_accounts_tab_for_edit_and_delete(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    with app.app_context():
        target = Account(username="redirect_account", email="redirect_account@example.com", password_hash="hashed")
        db.session.add(target)
        db.session.commit()
        target_id = target.id

    edit_response = client.post(
        f"/admin/accounts/{target_id}/edit",
        data={"username": "redirect_account", "email": "redirect_account@example.com"},
    )
    assert edit_response.headers["Location"] == "/admin/?tab=accounts"

    delete_response = client.post(f"/admin/accounts/{target_id}/delete")
    assert delete_response.headers["Location"] == "/admin/?tab=accounts"


def test_grant_permission_via_form(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    with app.app_context():
        permission = Permission(name="auth.invite")
        role = Role(name="grant_target_role")
        db.session.add_all([permission, role])
        db.session.commit()
        permission_id = permission.id
        role_id = role.id

    response = client.post(
        f"/admin/permissions/{permission_id}/grant", data={"role_id": role_id}
    )

    assert response.status_code == 302
    assert response.headers["Location"] == "/admin/?tab=permissions"
    with app.app_context():
        role = db.session.get(Role, role_id)
        assert [p.name for p in role.permissions] == ["auth.invite"]


def test_grant_permission_logs_action(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    with app.app_context():
        permission = db.session.query(Permission).filter_by(name="admin.roles.manage").one()
        role = Role(name="log_grant_role")
        db.session.add(role)
        db.session.commit()
        permission_id = permission.id
        role_id = role.id

    client.post(f"/admin/permissions/{permission_id}/grant", data={"role_id": role_id})

    with app.app_context():
        entries = db.session.query(LogEntry).filter_by(
            kind="action", source="admin.grant_permission"
        ).all()
        assert len(entries) == 1
        assert entries[0].account_id == account_id


def test_update_permission_via_form(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    with app.app_context():
        permission = Permission(name="editable_perm.action", description="old")
        db.session.add(permission)
        db.session.commit()
        permission_id = permission.id

    response = client.post(
        f"/admin/permissions/{permission_id}/edit", data={"description": "new description"}
    )

    assert response.status_code == 302
    with app.app_context():
        permission = db.session.get(Permission, permission_id)
        assert permission.description == "new description"
        assert permission.name == "editable_perm.action"


def test_delete_permission_via_form(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    with app.app_context():
        permission = Permission(name="deletable_perm.action")
        db.session.add(permission)
        db.session.commit()
        permission_id = permission.id

    response = client.post(f"/admin/permissions/{permission_id}/delete")

    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Permission, permission_id) is None


def test_permission_edit_and_delete_log_actions_and_redirect(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    with app.app_context():
        permission = Permission(name="log_perm.action")
        db.session.add(permission)
        db.session.commit()
        permission_id = permission.id

    edit_response = client.post(
        f"/admin/permissions/{permission_id}/edit", data={"description": "d"}
    )
    assert edit_response.headers["Location"] == "/admin/?tab=permissions"

    delete_response = client.post(f"/admin/permissions/{permission_id}/delete")
    assert delete_response.headers["Location"] == "/admin/?tab=permissions"

    with app.app_context():
        update_entries = db.session.query(LogEntry).filter_by(
            kind="action", source="admin.update_permission"
        ).all()
        delete_entries = db.session.query(LogEntry).filter_by(
            kind="action", source="admin.delete_permission"
        ).all()
        assert len(update_entries) == 1
        assert len(delete_entries) == 1


def test_dashboard_permissions_tab_lists_permissions(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    with app.app_context():
        db.session.add(Permission(name="listed_perm.action"))
        db.session.commit()

    response = client.get("/admin/?tab=permissions")

    assert b'class="tab-btn active" data-tab="permissions"' in response.data
    assert b"listed_perm.action" in response.data
    assert b'data-tab-panel="roles" hidden' in response.data


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


def test_create_role_logs_action(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    client.post("/admin/roles", data={"name": "logged_role", "description": "d"})

    with app.app_context():
        entries = db.session.query(LogEntry).filter_by(kind="action", source="admin.create_role").all()
        assert len(entries) == 1
        assert entries[0].account_id == account_id


def test_assign_and_remove_permission_log_actions(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    with app.app_context():
        role = Role(name="perm_log_role")
        db.session.add(role)
        db.session.commit()
        role_id = role.id

    client.post(f"/admin/roles/{role_id}/permissions", data={"permission_name": "admin.roles.manage"})
    client.post(f"/admin/roles/{role_id}/permissions/remove", data={"permission_name": "admin.roles.manage"})

    with app.app_context():
        assign_entries = db.session.query(LogEntry).filter_by(
            kind="action", source="admin.assign_permission"
        ).all()
        remove_entries = db.session.query(LogEntry).filter_by(
            kind="action", source="admin.remove_permission"
        ).all()
        assert len(assign_entries) == 1
        assert len(remove_entries) == 1
        assert assign_entries[0].account_id == account_id
        assert remove_entries[0].account_id == account_id


def test_assign_and_remove_role_log_actions(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    with app.app_context():
        target_account = Account(
            username="role_log_target", email="role_log_target@example.com", password_hash="hashed"
        )
        role = Role(name="role_log_role")
        db.session.add_all([target_account, role])
        db.session.commit()
        target_account_id = target_account.id
        role_id = role.id

    client.post(f"/admin/accounts/{target_account_id}/roles", data={"role_id": role_id})
    client.post(f"/admin/accounts/{target_account_id}/roles/remove", data={"role_id": role_id})

    with app.app_context():
        assign_entries = db.session.query(LogEntry).filter_by(kind="action", source="admin.assign_role").all()
        remove_entries = db.session.query(LogEntry).filter_by(kind="action", source="admin.remove_role").all()
        assert len(assign_entries) == 1
        assert len(remove_entries) == 1
        assert assign_entries[0].account_id == account_id
        assert remove_entries[0].account_id == account_id


def test_create_invite_logs_action(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["auth.invite"])
    client = app.test_client()
    _login_as(client, account_id)

    client.post("/admin/invites", data={"invitee_email": "", "delivery_method": "manual"})

    with app.app_context():
        entries = db.session.query(LogEntry).filter_by(kind="action", source="admin.create_invite").all()
        assert len(entries) == 1
        assert entries[0].account_id == account_id


def test_remove_invite_requires_auth_invite_permission(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.post("/admin/invites/1/remove")

    assert response.status_code == 403


def test_remove_invite_deletes_it(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["auth.invite"])
    client = app.test_client()
    _login_as(client, account_id)

    client.post("/admin/invites", data={"invitee_email": "", "delivery_method": "manual"})
    with app.app_context():
        invite_id = db.session.query(InviteOTP).one().id

    response = client.post(f"/admin/invites/{invite_id}/remove")

    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(InviteOTP, invite_id) is None


def test_remove_invite_logs_action(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["auth.invite"])
    client = app.test_client()
    _login_as(client, account_id)

    client.post("/admin/invites", data={"invitee_email": "", "delivery_method": "manual"})
    with app.app_context():
        invite_id = db.session.query(InviteOTP).one().id

    client.post(f"/admin/invites/{invite_id}/remove")

    with app.app_context():
        entries = db.session.query(LogEntry).filter_by(kind="action", source="admin.remove_invite").all()
        assert len(entries) == 1
        assert entries[0].account_id == account_id


def test_dashboard_defaults_to_roles_tab_active(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/admin/")

    assert b'class="tab-btn active" data-tab="roles"' in response.data
    assert b'data-tab-panel="accounts" hidden' in response.data
    assert b'data-tab-panel="invites" hidden' in response.data


def test_dashboard_tab_query_param_selects_active_tab(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/admin/?tab=accounts")

    assert b'class="tab-btn active" data-tab="accounts"' in response.data
    assert b'data-tab-panel="roles" hidden' in response.data
    assert b'data-tab-panel="invites" hidden' in response.data


def test_dashboard_unknown_tab_query_param_falls_back_to_roles(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/admin/?tab=bogus")

    assert b'class="tab-btn active" data-tab="roles"' in response.data


def test_invite_actions_redirect_to_invites_tab(tmp_path):
    app = _build_admin_test_app(tmp_path)
    account_id = _create_admin_account(app, ["admin.roles.manage", "auth.invite"])
    client = app.test_client()
    _login_as(client, account_id)

    create_response = client.post(
        "/admin/invites", data={"invitee_email": "", "delivery_method": "manual"}
    )
    assert create_response.headers["Location"] == "/admin/?tab=invites"

    with app.app_context():
        invite_id = db.session.query(InviteOTP).one().id

    remove_response = client.post(f"/admin/invites/{invite_id}/remove")
    assert remove_response.headers["Location"] == "/admin/?tab=invites"
