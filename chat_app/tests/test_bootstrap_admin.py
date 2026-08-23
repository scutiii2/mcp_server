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
