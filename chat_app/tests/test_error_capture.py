from flask import Flask
from werkzeug.security import generate_password_hash

from src.models import Account, LogEntry, db
from src.run import create_app


def _add_raising_route(app: Flask) -> None:
    @app.route("/__test_raise__")
    def _raise():
        raise ValueError("boom")


def test_unhandled_exception_logs_server_error_when_not_authenticated(tmp_path):
    app = create_app(
        {
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'error_test.db'}",
            "TESTING": True,
            "PROPAGATE_EXCEPTIONS": False,
        }
    )
    _add_raising_route(app)
    client = app.test_client()

    response = client.get("/__test_raise__")

    assert response.status_code == 500
    with app.app_context():
        entries = db.session.query(LogEntry).filter_by(kind="error", source="unhandled_exception").all()
        assert len(entries) == 1
        assert entries[0].account_id is None
        assert "boom" in entries[0].message
        assert "ValueError" in entries[0].details


def test_unhandled_exception_logs_account_error_when_authenticated(tmp_path):
    app = create_app(
        {
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'error_test2.db'}",
            "TESTING": True,
            "PROPAGATE_EXCEPTIONS": False,
        }
    )
    _add_raising_route(app)

    with app.app_context():
        account = Account(
            username="erroruser2",
            email="erroruser2@example.com",
            password_hash=generate_password_hash("pw"),
        )
        db.session.add(account)
        db.session.commit()
        account_id = account.id

    client = app.test_client()
    with client.session_transaction() as flask_session:
        flask_session["_user_id"] = str(account_id)
        flask_session["_fresh"] = True

    client.get("/__test_raise__")

    with app.app_context():
        entries = db.session.query(LogEntry).filter_by(kind="error", source="unhandled_exception").all()
        assert len(entries) == 1
        assert entries[0].account_id == account_id


def test_404_does_not_log_an_error(tmp_path):
    app = create_app(
        {
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'error_test3.db'}",
            "TESTING": True,
        }
    )
    client = app.test_client()

    response = client.get("/this-route-does-not-exist")

    assert response.status_code == 404
    with app.app_context():
        entries = db.session.query(LogEntry).filter_by(kind="error").all()
        assert entries == []


def test_integrity_error_does_not_leak_bound_sql_parameters(tmp_path):
    """SQLAlchemy's hide_parameters engine option (set in create_app) must
    keep bound parameters -- e.g. a password hash -- out of both the
    LogEntry.message and .details text for a real IntegrityError, while
    still leaving useful diagnostic info (the error type / SQLite message).
    """
    app = create_app(
        {
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'error_test4.db'}",
            "TESTING": True,
            "PROPAGATE_EXCEPTIONS": False,
        }
    )
    secret_hash = generate_password_hash("super-secret-password-123")

    @app.route("/__test_duplicate_insert__")
    def _duplicate_insert():
        db.session.add(
            Account(username="dupuser", email="dupuser@example.com", password_hash=secret_hash)
        )
        db.session.commit()
        # Same username again -> IntegrityError (unique constraint), with
        # secret_hash as one of the bound parameters on the failing INSERT.
        db.session.add(
            Account(username="dupuser", email="dupuser2@example.com", password_hash=secret_hash)
        )
        db.session.commit()
        return "unreachable"

    client = app.test_client()

    response = client.get("/__test_duplicate_insert__")

    assert response.status_code == 500
    with app.app_context():
        entries = db.session.query(LogEntry).filter_by(kind="error", source="unhandled_exception").all()
        assert len(entries) == 1
        entry = entries[0]

        # The secret bound parameter must not appear anywhere in the logged text.
        assert secret_hash not in entry.message
        assert secret_hash not in entry.details

        # Diagnostic value must still be present.
        assert "IntegrityError" in entry.message
        assert "UNIQUE constraint" in entry.details


def test_long_exception_message_is_truncated_in_log_entry_message(tmp_path):
    app = create_app(
        {
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'error_test5.db'}",
            "TESTING": True,
            "PROPAGATE_EXCEPTIONS": False,
        }
    )

    @app.route("/__test_raise_long__")
    def _raise_long():
        raise ValueError("x" * 1000)

    client = app.test_client()

    response = client.get("/__test_raise_long__")

    assert response.status_code == 500
    with app.app_context():
        entries = db.session.query(LogEntry).filter_by(kind="error", source="unhandled_exception").all()
        assert len(entries) == 1
        entry = entries[0]
        assert len(entry.message) <= 200
        # Full untruncated text is preserved in details (db.Text, unbounded).
        assert len(entry.details) > 200
        assert "x" * 1000 in entry.details
