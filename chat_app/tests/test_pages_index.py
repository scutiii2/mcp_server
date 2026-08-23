from src.pages.__index__ import discover_page_modules, register_pages


def test_discover_page_modules_finds_auth_and_skips_shared():
    modules = discover_page_modules()

    assert "Auth" in modules
    assert "__shared__" not in modules


def test_register_pages_builds_page_registry_with_permissions():
    from flask import Flask

    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret"
    register_pages(app)

    pages_by_name = {p["name"]: p for p in app.config["PAGES"]}
    assert pages_by_name["Auth"]["permission"] is None
    assert pages_by_name["Admin"]["permission"] == "admin.roles.manage"
    assert pages_by_name["Admin"]["url_prefix"] == "/admin"


def test_register_pages_defaults_layout_to_full():
    from flask import Flask

    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret"
    register_pages(app)

    pages_by_name = {p["name"]: p for p in app.config["PAGES"]}
    assert pages_by_name["Admin"]["layout"] == "full"
    assert pages_by_name["Overview"]["layout"] == "full"


def test_page_layout_context_matches_current_blueprint():
    from flask import Blueprint, Flask, render_template_string

    from src.services.auth_service import init_login_manager

    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret"
    init_login_manager(app)
    register_pages(app)

    fake_blueprint = Blueprint("faketab", __name__)

    @fake_blueprint.route("/faketab")
    def index():
        return render_template_string("{{ page_layout }}")

    app.register_blueprint(fake_blueprint)
    app.config["PAGES"].append(
        {
            "name": "FakeTab",
            "url_prefix": "/faketab",
            "permission": None,
            "description": None,
            "layout": "centered",
        }
    )

    client = app.test_client()
    response = client.get("/faketab")

    assert response.data == b"centered"


def test_page_layout_defaults_to_full_for_unlisted_blueprint():
    from flask import Blueprint, Flask, render_template_string

    from src.services.auth_service import init_login_manager

    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret"
    init_login_manager(app)
    register_pages(app)

    fake_blueprint = Blueprint("unlisted", __name__)

    @fake_blueprint.route("/unlisted")
    def index():
        return render_template_string("{{ page_layout }}")

    app.register_blueprint(fake_blueprint)

    client = app.test_client()
    response = client.get("/unlisted")

    assert response.data == b"full"


def test_nav_pages_includes_page_when_account_holds_any_of_a_tuple_permission(tmp_path):
    from flask import Flask, render_template_string

    from src.models import Account, Permission, Role, db
    from src.pages.__index__ import register_pages
    from src.services.auth_service import init_login_manager

    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'nav_test.db'}"
    app.config["SECRET_KEY"] = "test-secret"
    app.config["TESTING"] = True
    db.init_app(app)
    with app.app_context():
        db.create_all()
    init_login_manager(app)
    register_pages(app)

    with app.app_context():
        permission = Permission(name="tuple.perm.b")
        role = Role(name="tuple_role")
        role.permissions.append(permission)
        account = Account(username="tupleuser", email="tupleuser@example.com", password_hash="hashed")
        account.roles.append(role)
        db.session.add(account)
        db.session.commit()
        account_id = account.id

    app.config["PAGES"].append(
        {
            "name": "FakeTuplePage",
            "url_prefix": "/faketuple",
            "permission": ("tuple.perm.a", "tuple.perm.b"),
            "description": None,
        }
    )

    @app.route("/render-nav")
    def render_nav():
        return render_template_string("{% for p in nav_pages %}{{ p.name }},{% endfor %}")

    client = app.test_client()
    with client.session_transaction() as flask_session:
        flask_session["_user_id"] = str(account_id)
        flask_session["_fresh"] = True

    response = client.get("/render-nav")

    assert b"FakeTuplePage" in response.data


def test_nav_pages_excludes_page_when_account_holds_none_of_a_tuple_permission(tmp_path):
    from flask import Flask, render_template_string

    from src.models import Account, db
    from src.pages.__index__ import register_pages
    from src.services.auth_service import init_login_manager

    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'nav_test2.db'}"
    app.config["SECRET_KEY"] = "test-secret"
    app.config["TESTING"] = True
    db.init_app(app)
    with app.app_context():
        db.create_all()
    init_login_manager(app)
    register_pages(app)

    with app.app_context():
        account = Account(username="notupleuser", email="notupleuser@example.com", password_hash="hashed")
        db.session.add(account)
        db.session.commit()
        account_id = account.id

    app.config["PAGES"].append(
        {
            "name": "FakeTuplePage",
            "url_prefix": "/faketuple",
            "permission": ("tuple.perm.a", "tuple.perm.b"),
            "description": None,
        }
    )

    @app.route("/render-nav")
    def render_nav():
        return render_template_string("{% for p in nav_pages %}{{ p.name }},{% endfor %}")

    client = app.test_client()
    with client.session_transaction() as flask_session:
        flask_session["_user_id"] = str(account_id)
        flask_session["_fresh"] = True

    response = client.get("/render-nav")

    assert b"FakeTuplePage" not in response.data


def test_register_pages_exempts_csrf_only_when_flagged():
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from flask import Blueprint, Flask

    import src.pages.__index__ as pages_index

    exempt_blueprint = Blueprint("exemptfake", __name__)
    normal_blueprint = Blueprint("normalfake", __name__)
    exempt_module = SimpleNamespace(blueprint=exempt_blueprint, CSRF_EXEMPT=True)
    normal_module = SimpleNamespace(blueprint=normal_blueprint)  # no CSRF_EXEMPT attribute at all

    def fake_import_module(name):
        return exempt_module if name.endswith(".ExemptFake.__index__") else normal_module

    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret"
    csrf = MagicMock()

    with patch.object(pages_index, "discover_page_modules", return_value=["ExemptFake", "NormalFake"]), \
         patch.object(pages_index.importlib, "import_module", side_effect=fake_import_module):
        pages_index.register_pages(app, csrf=csrf)

    csrf.exempt.assert_called_once_with(exempt_blueprint)


def test_register_pages_never_calls_exempt_when_csrf_is_none():
    from types import SimpleNamespace
    from unittest.mock import patch

    from flask import Blueprint, Flask

    import src.pages.__index__ as pages_index

    exempt_blueprint = Blueprint("exemptfake2", __name__)
    exempt_module = SimpleNamespace(blueprint=exempt_blueprint, CSRF_EXEMPT=True)

    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret"

    with patch.object(pages_index, "discover_page_modules", return_value=["ExemptFake2"]), \
         patch.object(pages_index.importlib, "import_module", return_value=exempt_module):
        pages_index.register_pages(app, csrf=None)  # must not raise
