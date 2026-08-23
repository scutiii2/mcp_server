from unittest.mock import patch

from types import SimpleNamespace

from flask import Flask
from werkzeug.security import generate_password_hash

from src.models import Account, Permission, Role, db
from src.pages.__index__ import register_pages
from src.services.auth_service import init_login_manager
from src.services.email_service import init_mail

from pathlib import Path

_SHARED_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "src" / "pages" / "__shared__"


def _build_capabilities_test_app(tmp_path):
    app = Flask(
        __name__,
        template_folder=str(_SHARED_TEMPLATES_DIR),
        static_folder=str(_SHARED_TEMPLATES_DIR),
        static_url_path="/shared/static",
    )
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'capabilities_test.db'}"
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


def test_capabilities_page_requires_authentication(tmp_path):
    app = _build_capabilities_test_app(tmp_path)
    client = app.test_client()

    response = client.get("/capabilities/")

    assert response.status_code == 401


def test_capabilities_page_forbidden_without_either_permission(tmp_path):
    app = _build_capabilities_test_app(tmp_path)
    account_id = _create_account(app, "nocapaccess", [])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/capabilities/")

    assert response.status_code == 403


def test_capabilities_page_renders_with_view_permission(tmp_path):
    app = _build_capabilities_test_app(tmp_path)
    account_id = _create_account(app, "capviewer", ["capabilities.view"])
    client = app.test_client()
    _login_as(client, account_id)

    with patch("src.pages.Capabilities.__index__.list_tools", return_value=[]), \
         patch("src.pages.Capabilities.__index__.list_resource_templates", return_value=[]), \
         patch("src.pages.Capabilities.__index__.fetch_extensions", return_value=[]):
        response = client.get("/capabilities/")

    assert response.status_code == 200


def test_try_tool_forbidden_with_only_view_permission(tmp_path):
    app = _build_capabilities_test_app(tmp_path)
    account_id = _create_account(app, "capviewonly", ["capabilities.view"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.post("/capabilities/api/try/some_tool", json={})

    assert response.status_code == 403


def test_try_tool_allowed_with_try_permission(tmp_path):
    app = _build_capabilities_test_app(tmp_path)
    account_id = _create_account(app, "captryer", ["capabilities.try"])
    client = app.test_client()
    _login_as(client, account_id)

    with patch("src.pages.Capabilities.__index__.call_tool", return_value="ok result"):
        response = client.post("/capabilities/api/try/some_tool", json={})

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "result": "ok result"}


def test_api_tools_forbidden_with_only_try_permission(tmp_path):
    app = _build_capabilities_test_app(tmp_path)
    account_id = _create_account(app, "captryonly", ["capabilities.try"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/capabilities/api/tools")

    assert response.status_code == 403


def test_capabilities_page_has_no_inline_event_handlers(tmp_path):
    app = _build_capabilities_test_app(tmp_path)
    account_id = _create_account(app, "cspuser", ["capabilities.view"])
    client = app.test_client()
    _login_as(client, account_id)

    with patch("src.pages.Capabilities.__index__.list_tools", return_value=[]), \
         patch("src.pages.Capabilities.__index__.list_resource_templates", return_value=[]), \
         patch("src.pages.Capabilities.__index__.fetch_extensions", return_value=[]):
        response = client.get("/capabilities/")

    assert response.status_code == 200
    assert b"onclick=" not in response.data
    assert b"onsubmit=" not in response.data
    assert b'style="display:none"' not in response.data
