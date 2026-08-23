from pathlib import Path

from flask import Flask
from werkzeug.security import check_password_hash, generate_password_hash

from src.models import Account, LogEntry, Permission, Role, db
from src.pages.__index__ import register_pages
from src.services.auth_service import init_login_manager
from src.services.email_service import init_mail

_SHARED_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "src" / "pages" / "__shared__"


def _build_account_test_app(tmp_path):
    app = Flask(
        __name__,
        template_folder=str(_SHARED_TEMPLATES_DIR),
        static_folder=str(_SHARED_TEMPLATES_DIR),
        static_url_path="/shared/static",
    )
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'account_test.db'}"
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


def _login_as(client, account_id):
    with client.session_transaction() as flask_session:
        flask_session["_user_id"] = str(account_id)
        flask_session["_fresh"] = True


def test_account_page_requires_authentication(tmp_path):
    app = _build_account_test_app(tmp_path)
    client = app.test_client()

    response = client.get("/account/")

    assert response.status_code == 401


def test_account_page_renders_read_only_without_edit_permission(tmp_path):
    app = _build_account_test_app(tmp_path)

    with app.app_context():
        account = Account(
            username="plain",
            email="plain@example.com",
            password_hash=generate_password_hash("secret123"),
        )
        db.session.add(account)
        db.session.commit()
        account_id = account.id

    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/account/")

    assert response.status_code == 200
    assert b"plain@example.com" in response.data
    assert b"Contact an administrator" in response.data


def test_account_page_post_rejected_without_edit_permission(tmp_path):
    app = _build_account_test_app(tmp_path)

    with app.app_context():
        account = Account(
            username="noedit",
            email="noedit@example.com",
            password_hash=generate_password_hash("secret123"),
        )
        db.session.add(account)
        db.session.commit()
        account_id = account.id

    client = app.test_client()
    _login_as(client, account_id)

    response = client.post(
        "/account/",
        data={"current_password": "secret123", "email": "changed@example.com"},
    )

    assert response.status_code == 302
    with app.app_context():
        refreshed = db.session.get(Account, account_id)
        assert refreshed.email == "noedit@example.com"


def test_account_page_updates_email_with_edit_permission_and_correct_password(tmp_path):
    app = _build_account_test_app(tmp_path)

    with app.app_context():
        role = Role(name="editor_role")
        permission = Permission(name="account.edit")
        role.permissions.append(permission)
        account = Account(
            username="editor",
            email="editor@example.com",
            password_hash=generate_password_hash("secret123"),
        )
        account.roles.append(role)
        db.session.add(account)
        db.session.commit()
        account_id = account.id

    client = app.test_client()
    _login_as(client, account_id)

    response = client.post(
        "/account/",
        data={"current_password": "secret123", "email": "updated@example.com"},
    )

    assert response.status_code == 302
    with app.app_context():
        refreshed = db.session.get(Account, account_id)
        assert refreshed.email == "updated@example.com"


def test_account_page_rejects_wrong_current_password(tmp_path):
    app = _build_account_test_app(tmp_path)

    with app.app_context():
        role = Role(name="editor_role2")
        permission = Permission(name="account.edit")
        role.permissions.append(permission)
        account = Account(
            username="editor2",
            email="editor2@example.com",
            password_hash=generate_password_hash("secret123"),
        )
        account.roles.append(role)
        db.session.add(account)
        db.session.commit()
        account_id = account.id

    client = app.test_client()
    _login_as(client, account_id)

    response = client.post(
        "/account/",
        data={"current_password": "wrong-password", "email": "shouldnotchange@example.com"},
    )

    assert response.status_code == 302
    with app.app_context():
        refreshed = db.session.get(Account, account_id)
        assert refreshed.email == "editor2@example.com"


def test_account_page_updates_password_with_edit_permission(tmp_path):
    app = _build_account_test_app(tmp_path)

    with app.app_context():
        role = Role(name="editor_role3")
        permission = Permission(name="account.edit")
        role.permissions.append(permission)
        account = Account(
            username="editor3",
            email="editor3@example.com",
            password_hash=generate_password_hash("old-password"),
        )
        account.roles.append(role)
        db.session.add(account)
        db.session.commit()
        account_id = account.id

    client = app.test_client()
    _login_as(client, account_id)

    client.post(
        "/account/",
        data={"current_password": "old-password", "new_password": "new-password"},
    )

    with app.app_context():
        refreshed = db.session.get(Account, account_id)
        assert check_password_hash(refreshed.password_hash, "new-password")


def test_account_page_update_logs_action(tmp_path):
    app = _build_account_test_app(tmp_path)

    with app.app_context():
        role = Role(name="log_editor_role")
        permission = Permission(name="account.edit")
        role.permissions.append(permission)
        account = Account(
            username="logeditor",
            email="logeditor@example.com",
            password_hash=generate_password_hash("secret123"),
        )
        account.roles.append(role)
        db.session.add(account)
        db.session.commit()
        account_id = account.id

    client = app.test_client()
    _login_as(client, account_id)

    client.post(
        "/account/",
        data={"current_password": "secret123", "email": "loggedupdate@example.com"},
    )

    with app.app_context():
        entries = db.session.query(LogEntry).filter_by(
            kind="action", source="account.profile_update"
        ).all()
        assert len(entries) == 1
        assert entries[0].account_id == account_id


def test_account_page_failed_update_does_not_log_action(tmp_path):
    app = _build_account_test_app(tmp_path)

    with app.app_context():
        role = Role(name="log_editor_role2")
        permission = Permission(name="account.edit")
        role.permissions.append(permission)
        account = Account(
            username="logeditor2",
            email="logeditor2@example.com",
            password_hash=generate_password_hash("secret123"),
        )
        account.roles.append(role)
        db.session.add(account)
        db.session.commit()
        account_id = account.id

    client = app.test_client()
    _login_as(client, account_id)

    client.post(
        "/account/",
        data={"current_password": "wrong-password", "email": "shouldnotlog@example.com"},
    )

    with app.app_context():
        entries = db.session.query(LogEntry).filter_by(
            kind="action", source="account.profile_update"
        ).all()
        assert entries == []
