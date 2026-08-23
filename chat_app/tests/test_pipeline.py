from datetime import datetime, timezone

from flask import Flask

from src.models import LoginAttempt, db
from src.services.security.pipeline import register_security_pipeline


def _build_test_app(tmp_path, ip_filter_config=None, rate_limit_config=None, headers_config=None):
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'pipeline_test.db'}"
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret"
    db.init_app(app)
    with app.app_context():
        db.create_all()

    @app.route("/ping")
    def ping():
        return "pong"

    configs = {
        "config_security_ip_filter": ip_filter_config or {"enabled": False},
        "config_security_rate_limit": rate_limit_config or {"enabled": False},
        "config_security_headers": headers_config or {"enabled": False},
    }
    register_security_pipeline(app, configs)
    return app


def test_pipeline_allows_request_when_all_checks_disabled(tmp_path):
    app = _build_test_app(tmp_path)
    client = app.test_client()

    response = client.get("/ping")

    assert response.status_code == 200
    assert response.data == b"pong"


def test_pipeline_blocks_denied_ip(tmp_path):
    app = _build_test_app(
        tmp_path,
        ip_filter_config={
            "enabled": True,
            "deny_list": ["127.0.0.1"],
            "allow_list": [],
            "geofencing": {"enabled": False},
        },
    )
    client = app.test_client()

    response = client.get("/ping")

    assert response.status_code == 403


def test_pipeline_applies_security_headers(tmp_path):
    app = _build_test_app(
        tmp_path,
        headers_config={
            "enabled": True,
            "content_security_policy": "default-src 'self'",
            "hsts_max_age": 63072000,
            "force_https": False,
            "csrf_enabled": False,
        },
    )
    client = app.test_client()

    response = client.get("/ping")

    assert response.status_code == 200
    assert response.headers["Content-Security-Policy"] == "default-src 'self'"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_pipeline_rate_limits_after_threshold(tmp_path):
    app = _build_test_app(
        tmp_path,
        rate_limit_config={
            "enabled": True,
            "max_attempts": 2,
            "window_seconds": 300,
            "lockout_seconds": 900,
            "scope": "ip",
        },
    )

    with app.app_context():
        for _ in range(2):
            db.session.add(
                LoginAttempt(
                    ip_address="127.0.0.1",
                    account_id=None,
                    success=False,
                    created_at=datetime.now(timezone.utc),
                )
            )
        db.session.commit()

    client = app.test_client()
    response = client.get("/ping")

    assert response.status_code == 429


def test_pipeline_enables_csrf_protection_when_configured(tmp_path):
    app = _build_test_app(
        tmp_path,
        headers_config={
            "enabled": True,
            "content_security_policy": None,
            "hsts_max_age": None,
            "force_https": False,
            "csrf_enabled": True,
        },
    )

    assert app.extensions.get("csrf") is not None


def test_pipeline_rejects_cross_site_post(tmp_path):
    app = _build_test_app(tmp_path)
    client = app.test_client()

    response = client.post("/ping", headers={"Sec-Fetch-Site": "cross-site"})

    assert response.status_code == 403


def test_pipeline_allows_same_origin_post(tmp_path):
    app = _build_test_app(tmp_path)
    client = app.test_client()

    response = client.post("/ping", headers={"Sec-Fetch-Site": "same-origin"})

    # /ping only handles GET - a 405 here (not 403) proves the cross-site
    # check let the request through to normal Flask routing, which then
    # rejects the method itself.
    assert response.status_code == 405


def test_register_security_pipeline_returns_csrf_extension_when_enabled(tmp_path):
    from flask import Flask
    from flask_wtf import CSRFProtect

    from src.models import db
    from src.services.security.pipeline import register_security_pipeline

    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'csrf_return_test.db'}"
    app.config["SECRET_KEY"] = "test-secret"
    db.init_app(app)
    with app.app_context():
        db.create_all()

    result = register_security_pipeline(
        app,
        {
            "config_security_headers": {
                "enabled": True,
                "content_security_policy": None,
                "hsts_max_age": None,
                "force_https": False,
                "csrf_enabled": True,
            }
        },
    )

    assert isinstance(result, CSRFProtect)


def test_register_security_pipeline_returns_none_when_csrf_disabled(tmp_path):
    from flask import Flask

    from src.models import db
    from src.services.security.pipeline import register_security_pipeline

    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'csrf_return_test2.db'}"
    app.config["SECRET_KEY"] = "test-secret"
    db.init_app(app)
    with app.app_context():
        db.create_all()

    result = register_security_pipeline(app, {"config_security_headers": {"enabled": False}})

    assert result is None
