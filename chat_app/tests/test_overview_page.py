from pathlib import Path

from flask import Flask

from src.models import Account, Permission, Role, db
from src.pages.__index__ import register_pages
from src.services.auth_service import init_login_manager
from src.services.email_service import init_mail

_SHARED_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "src" / "pages" / "__shared__"


def _build_overview_test_app(tmp_path):
    app = Flask(
        __name__,
        template_folder=str(_SHARED_TEMPLATES_DIR),
        static_folder=str(_SHARED_TEMPLATES_DIR),
        static_url_path="/shared/static",
    )
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'overview_test.db'}"
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


def test_overview_requires_authentication(tmp_path):
    app = _build_overview_test_app(tmp_path)
    client = app.test_client()

    response = client.get("/")

    assert response.status_code == 401


def test_overview_shows_only_accessible_pages(tmp_path):
    app = _build_overview_test_app(tmp_path)

    with app.app_context():
        account = Account(username="viewer", email="viewer@example.com", password_hash="hashed")
        db.session.add(account)
        db.session.commit()
        account_id = account.id

    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/")

    assert response.status_code == 200
    assert b'href="/admin"' not in response.data
    assert b'href="/auth"' not in response.data


def test_overview_shows_admin_tile_for_admin_account(tmp_path):
    app = _build_overview_test_app(tmp_path)

    with app.app_context():
        role = Role(name="Administrator")
        permission = Permission(name="admin.roles.manage")
        role.permissions.append(permission)
        account = Account(username="admin_user", email="admin_user@example.com", password_hash="hashed")
        account.roles.append(role)
        db.session.add(account)
        db.session.commit()
        account_id = account.id

    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/")

    assert response.status_code == 200
    assert b'href="/admin"' in response.data


def test_overview_has_no_sidebar(tmp_path):
    app = _build_overview_test_app(tmp_path)

    with app.app_context():
        account = Account(username="nosidebar", email="nosidebar@example.com", password_hash="hashed")
        db.session.add(account)
        db.session.commit()
        account_id = account.id

    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/")

    assert response.status_code == 200
    assert b'id="sidebar"' not in response.data
