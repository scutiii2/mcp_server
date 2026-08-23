from pathlib import Path

from flask import Flask
from werkzeug.security import generate_password_hash

from src.models import Account, LogEntry, LoginAttempt, SecurityEvent, db
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


def test_login_logs_action(tmp_path):
    app = _build_auth_test_app(tmp_path)

    with app.app_context():
        account = Account(
            username="loguser",
            email="loguser@example.com",
            password_hash=generate_password_hash("correct-password"),
        )
        db.session.add(account)
        db.session.commit()
        account_id = account.id

    client = app.test_client()
    client.post("/auth/login", data={"username": "loguser", "password": "correct-password"})

    with app.app_context():
        entries = db.session.query(LogEntry).filter_by(kind="action", source="auth.login").all()
        assert len(entries) == 1
        assert entries[0].account_id == account_id


def test_logout_logs_action(tmp_path):
    app = _build_auth_test_app(tmp_path)

    with app.app_context():
        account = Account(
            username="logoutlog",
            email="logoutlog@example.com",
            password_hash=generate_password_hash("correct-password"),
        )
        db.session.add(account)
        db.session.commit()
        account_id = account.id

    client = app.test_client()
    client.post("/auth/login", data={"username": "logoutlog", "password": "correct-password"})
    client.get("/auth/logout")

    with app.app_context():
        entries = db.session.query(LogEntry).filter_by(kind="action", source="auth.logout").all()
        assert len(entries) == 1
        assert entries[0].account_id == account_id


def test_register_logs_action(tmp_path):
    app = _build_auth_test_app(tmp_path)

    with app.app_context():
        inviter = Account(username="reginviter", email="reginviter@example.com", password_hash="hashed")
        db.session.add(inviter)
        db.session.commit()
        _, code = otp_service.create_invite(db.session, inviter.id, "regnew@example.com", "manual")

    client = app.test_client()
    client.post(
        "/auth/register",
        data={
            "username": "regnewperson",
            "email": "regnew@example.com",
            "password": "s3cret!",
            "invite_code": code,
        },
    )

    with app.app_context():
        entries = db.session.query(LogEntry).filter_by(kind="action", source="auth.register").all()
        created = db.session.query(Account).filter_by(username="regnewperson").one()
        assert len(entries) == 1
        assert entries[0].account_id == created.id
