from flask_login import LoginManager, login_user

from src.models import Account, Permission, Role, db
from src.services.authz import (
    account_permissions,
    has_permission,
    register_permission,
    registered_permissions,
    require_login,
    require_permission,
)


def test_require_permission_registers_permission_name():
    @require_permission("test_module.some_action")
    def view():
        return "ok"

    assert "test_module.some_action" in registered_permissions()


def test_account_permissions_returns_union_across_roles(app):
    with app.app_context():
        account = Account(username="grace", email="grace@example.com", password_hash="hashed")
        role_a = Role(name="role_a")
        role_b = Role(name="role_b")
        perm_a = Permission(name="a.read")
        perm_b = Permission(name="b.write")
        role_a.permissions.append(perm_a)
        role_b.permissions.append(perm_b)
        account.roles.extend([role_a, role_b])
        db.session.add(account)
        db.session.commit()

        permissions = account_permissions(account)

    assert permissions == {"a.read", "b.write"}


def test_has_permission_true_when_granted(app):
    with app.app_context():
        account = Account(username="heidi", email="heidi@example.com", password_hash="hashed")
        role = Role(name="role_c")
        permission = Permission(name="c.manage")
        role.permissions.append(permission)
        account.roles.append(role)
        db.session.add(account)
        db.session.commit()

        assert has_permission(account, "c.manage") is True
        assert has_permission(account, "c.other") is False


def test_require_permission_blocks_unauthenticated_request(app):
    login_manager = LoginManager()
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(Account, int(user_id))

    @app.route("/protected")
    @require_permission("protected.view")
    def protected():
        return "secret"

    client = app.test_client()
    response = client.get("/protected")

    assert response.status_code == 401


def test_require_permission_blocks_authenticated_without_permission(app):
    login_manager = LoginManager()
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(Account, int(user_id))

    @app.route("/login-as/<int:account_id>")
    def login_as(account_id):
        account = db.session.get(Account, account_id)
        login_user(account)
        return "logged in"

    @app.route("/protected2")
    @require_permission("protected2.view")
    def protected2():
        return "secret"

    with app.app_context():
        account = Account(username="ivan2", email="ivan2@example.com", password_hash="hashed")
        db.session.add(account)
        db.session.commit()
        account_id = account.id

    client = app.test_client()
    client.get(f"/login-as/{account_id}")
    response = client.get("/protected2")

    assert response.status_code == 403


def test_require_permission_allows_authenticated_with_permission(app):
    login_manager = LoginManager()
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(Account, int(user_id))

    @app.route("/login-as2/<int:account_id>")
    def login_as2(account_id):
        account = db.session.get(Account, account_id)
        login_user(account)
        return "logged in"

    @app.route("/protected3")
    @require_permission("protected3.view")
    def protected3():
        return "secret"

    with app.app_context():
        account = Account(username="judy", email="judy@example.com", password_hash="hashed")
        role = Role(name="role_d")
        permission = Permission(name="protected3.view")
        role.permissions.append(permission)
        account.roles.append(role)
        db.session.add(account)
        db.session.commit()
        account_id = account.id

    client = app.test_client()
    client.get(f"/login-as2/{account_id}")
    response = client.get("/protected3")

    assert response.status_code == 200
    assert response.data == b"secret"


def test_register_permission_adds_to_registry():
    register_permission("standalone.registered_permission")

    assert "standalone.registered_permission" in registered_permissions()


def test_require_login_blocks_unauthenticated_request(app):
    login_manager = LoginManager()
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(Account, int(user_id))

    @app.route("/needs-login")
    @require_login()
    def needs_login():
        return "ok"

    client = app.test_client()
    response = client.get("/needs-login")

    assert response.status_code == 401


def test_require_login_allows_any_authenticated_account(app):
    login_manager = LoginManager()
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(Account, int(user_id))

    @app.route("/login-as3/<int:account_id>")
    def login_as3(account_id):
        account = db.session.get(Account, account_id)
        login_user(account)
        return "logged in"

    @app.route("/needs-login2")
    @require_login()
    def needs_login2():
        return "ok"

    with app.app_context():
        account = Account(username="karen", email="karen@example.com", password_hash="hashed")
        db.session.add(account)
        db.session.commit()
        account_id = account.id

    client = app.test_client()
    client.get(f"/login-as3/{account_id}")
    response = client.get("/needs-login2")

    assert response.status_code == 200
