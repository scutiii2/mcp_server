from pathlib import Path

from flask import Flask
from werkzeug.security import generate_password_hash

from src.models import Account, LogEntry, Permission, Role, db
from src.pages.__index__ import register_pages
from src.services.auth_service import init_login_manager
from src.services.email_service import init_mail

_SHARED_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "src" / "pages" / "__shared__"


def _build_logs_test_app(tmp_path):
    app = Flask(
        __name__,
        template_folder=str(_SHARED_TEMPLATES_DIR),
        static_folder=str(_SHARED_TEMPLATES_DIR),
        static_url_path="/shared/static",
    )
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'logs_test.db'}"
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


def _create_account(app, username, permission_names):
    with app.app_context():
        account = Account(
            username=username,
            email=f"{username}@example.com",
            password_hash=generate_password_hash("pw"),
        )
        if permission_names:
            role = Role(name=f"{username}_role")
            db.session.add(role)
            for name in permission_names:
                permission = db.session.query(Permission).filter_by(name=name).first()
                if permission is None:
                    permission = Permission(name=name)
                    db.session.add(permission)
                role.permissions.append(permission)
            account.roles.append(role)
        db.session.add(account)
        db.session.commit()
        return account.id


def _login_as(client, account_id):
    with client.session_transaction() as flask_session:
        flask_session["_user_id"] = str(account_id)
        flask_session["_fresh"] = True


def test_logs_page_requires_authentication(tmp_path):
    app = _build_logs_test_app(tmp_path)
    client = app.test_client()

    response = client.get("/logs/")

    assert response.status_code == 401


def test_logs_page_forbidden_without_either_permission(tmp_path):
    app = _build_logs_test_app(tmp_path)
    account_id = _create_account(app, "nopermsuser", [])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/logs/")

    assert response.status_code == 403


def test_logs_page_shows_only_logs_tab_with_logs_view_permission(tmp_path):
    app = _build_logs_test_app(tmp_path)
    account_id = _create_account(app, "logsonly", ["logs.view"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/logs/")

    assert response.status_code == 200
    assert b'data-tab="logs"' in response.data
    assert b'data-tab="errors"' not in response.data


def test_logs_page_shows_only_errors_tab_with_errors_view_permission(tmp_path):
    app = _build_logs_test_app(tmp_path)
    account_id = _create_account(app, "errorsonly", ["logs.errors.view"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/logs/")

    assert response.status_code == 200
    assert b'data-tab="errors"' in response.data
    assert b'data-tab="logs"' not in response.data


def test_logs_page_shows_both_tabs_with_both_permissions(tmp_path):
    app = _build_logs_test_app(tmp_path)
    account_id = _create_account(app, "bothperms", ["logs.view", "logs.errors.view"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/logs/")

    assert response.status_code == 200
    assert b'data-tab="logs"' in response.data
    assert b'data-tab="errors"' in response.data


def test_logs_tab_defaults_to_server_entries(tmp_path):
    app = _build_logs_test_app(tmp_path)
    account_id = _create_account(app, "defaultserver", ["logs.view"])

    with app.app_context():
        db.session.add(LogEntry(kind="action", account_id=None, source="x", message="server did a thing"))
        db.session.add(LogEntry(kind="action", account_id=account_id, source="x", message="user did a thing"))
        db.session.commit()

    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/logs/")

    assert response.status_code == 200
    assert b"server did a thing" in response.data
    assert b"user did a thing" not in response.data


def test_logs_tab_filters_by_selected_account(tmp_path):
    app = _build_logs_test_app(tmp_path)
    account_id = _create_account(app, "filteruser", ["logs.view"])

    with app.app_context():
        db.session.add(LogEntry(kind="action", account_id=None, source="x", message="server did a thing"))
        db.session.add(LogEntry(kind="action", account_id=account_id, source="x", message="user did a thing"))
        db.session.commit()

    client = app.test_client()
    _login_as(client, account_id)

    response = client.get(f"/logs/?tab=logs&logs_actor={account_id}")

    assert response.status_code == 200
    assert b"user did a thing" in response.data
    assert b"server did a thing" not in response.data


def test_logs_only_account_requesting_unpermitted_tab_gets_logs_tab_active(tmp_path):
    app = _build_logs_test_app(tmp_path)
    account_id = _create_account(app, "logsonlyclamp", ["logs.view"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/logs/?tab=errors")

    assert response.status_code == 200
    assert b'class="tab-btn active" data-tab="logs"' in response.data
    assert b'data-tab-panel="logs">' in response.data


def test_logs_only_account_requesting_unknown_tab_gets_logs_tab_active(tmp_path):
    app = _build_logs_test_app(tmp_path)
    account_id = _create_account(app, "logsonlyclamp2", ["logs.view"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/logs/?tab=zzz")

    assert response.status_code == 200
    assert b'class="tab-btn active" data-tab="logs"' in response.data
    assert b'data-tab-panel="logs">' in response.data


def test_errors_tab_shows_details_for_error_entries(tmp_path):
    app = _build_logs_test_app(tmp_path)
    account_id = _create_account(app, "erroruser", ["logs.errors.view"])

    with app.app_context():
        db.session.add(
            LogEntry(
                kind="error",
                account_id=None,
                source="unhandled_exception",
                message="boom",
                details="Traceback...",
            )
        )
        db.session.commit()

    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/logs/")

    assert response.status_code == 200
    assert b"boom" in response.data
    assert b"Traceback..." in response.data


def test_logs_page_forbidden_without_any_of_three_permissions(tmp_path):
    app = _build_logs_test_app(tmp_path)
    account_id = _create_account(app, "nopermsuser2", [])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/logs/")

    assert response.status_code == 403


def test_logs_page_shows_only_chat_traces_tab_with_that_permission(tmp_path):
    app = _build_logs_test_app(tmp_path)
    account_id = _create_account(app, "chattraceonly", ["logs.chat.view"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/logs/")

    assert response.status_code == 200
    assert b'data-tab="chat_traces"' in response.data
    assert b'data-tab="logs"' not in response.data
    assert b'data-tab="errors"' not in response.data


def test_chat_traces_tab_shows_entries_for_selected_account(tmp_path):
    app = _build_logs_test_app(tmp_path)
    account_id = _create_account(app, "chattraceuser", ["logs.chat.view"])

    with app.app_context():
        db.session.add(
            LogEntry(kind="chat_trace", account_id=account_id, source="chat.turn", message="hi there turn", details="{}")
        )
        db.session.commit()

    client = app.test_client()
    _login_as(client, account_id)

    response = client.get(f"/logs/?tab=chat_traces&chat_traces_actor={account_id}")

    assert response.status_code == 200
    assert b"hi there turn" in response.data
