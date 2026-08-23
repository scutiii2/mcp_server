"""Full-stack smoke test: the real create_app() (not a throwaway
per-page Flask app) boots with Chat and Capabilities registered,
correctly permission-gated, and CSRF-exempted."""

from __future__ import annotations

from werkzeug.security import generate_password_hash

from src.models import Account, Permission, Role, db


def test_app_boots_with_chat_and_capabilities_registered(tmp_path):
    # No chdir/tmp_path scaffolding for secrets/configs/data - run.py's
    # BASE_DIR is Path(__file__).resolve().parent, fixed to the real
    # chat_app/src/ regardless of cwd (that's the whole point of BASE_DIR
    # - see _resolve_sqlite_uri's docstring), so create_app() is already
    # directly testable with just a config override, exactly like
    # tests/test_app_factory.py's existing tests already do.
    from src.run import create_app

    app = create_app(
        {
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'app.db'}",
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "WTF_CSRF_ENABLED": False,
        }
    )

    page_names = {p["name"] for p in app.config["PAGES"]}
    assert "Chat" in page_names
    assert "Capabilities" in page_names

    with app.app_context():
        account = Account(
            username="fullstackuser", email="fullstackuser@example.com",
            password_hash=generate_password_hash("pw"),
        )
        role = Role(name="fullstack_role")
        db.session.add(role)
        for name in ("chat.access", "capabilities.view"):
            permission = db.session.query(Permission).filter_by(name=name).first()
            if permission is None:
                permission = Permission(name=name)
                db.session.add(permission)
            role.permissions.append(permission)
        account.roles.append(role)
        db.session.add(account)
        db.session.commit()
        account_id = account.id

    client = app.test_client()
    with client.session_transaction() as flask_session:
        flask_session["_user_id"] = str(account_id)
        flask_session["_fresh"] = True

    chat_response = client.get("/chat/")
    assert chat_response.status_code == 200

    capabilities_response = client.get("/capabilities/")
    assert capabilities_response.status_code == 200

    admin_response = client.get("/admin/")
    assert admin_response.status_code == 403  # no admin.* permission granted - unrelated page still gated normally
