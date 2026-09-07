import os
import traceback
from pathlib import Path

from flask import Flask, redirect, render_template, request, url_for
from flask_login import current_user
from werkzeug.exceptions import HTTPException

from src.models import db
from src.pages.__index__ import register_pages
from src.services import log_service
from src.services.auth_service import ensure_bootstrap_admin, init_login_manager
from src.services.email_service import init_mail
from src.services.security.pipeline import load_security_configs, register_security_pipeline
from src.utils.config_loader import load_env_secrets

BASE_DIR = Path(__file__).resolve().parent

# Max length of the LogEntry.message column (db.String(500)); truncate to stay
# well under that so a real backend (Postgres/MySQL) never raises a DataError
# from inside the error handler itself.
_MESSAGE_MAX = 200


def _resolve_sqlite_uri(raw_uri: str, base_dir: Path) -> str:
    """Resolve a relative sqlite:/// path against base_dir instead of the cwd.

    A bare relative path (e.g. from a DATABASE_URL override in secrets) is
    otherwise resolved by sqlite against the process's working directory,
    which varies by how the app is launched (double-click vs "Run as
    Administrator" vs an IDE debugger) and silently breaks db file creation.
    """
    prefix = "sqlite:///"
    if not raw_uri.startswith(prefix) or raw_uri.startswith("sqlite:////"):
        return raw_uri
    db_path = Path(raw_uri[len(prefix):])
    if not db_path.is_absolute():
        db_path = base_dir / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"{prefix}{db_path.resolve()}"


def create_app(config: dict | None = None) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "pages" / "__shared__"),
        static_folder=str(BASE_DIR / "pages" / "__shared__"),
        static_url_path="/shared/static",
    )

    app_secrets = load_env_secrets(BASE_DIR / "secrets" / "secret_app.env")
    db_secrets = load_env_secrets(BASE_DIR / "secrets" / "secret_db.env")
    llm_secrets = load_env_secrets(BASE_DIR / "secrets" / "secret_llm.env")
    for key, value in llm_secrets.items():
        if value:
            os.environ.setdefault(key, value)
    # BASE_DIR-resolved, not CWD-relative - same reasoning as
    # _resolve_sqlite_uri below for app.db. A real CHATS_DB_PATH/
    # STAGED_PLANS_DB_PATH/CHAT_CONFIG_PATH env var (including one already
    # set via secret_llm.env above) still wins - setdefault is a no-op once
    # the key is already present.
    os.environ.setdefault("CHATS_DB_PATH", str(BASE_DIR / "data" / "chats.db"))
    os.environ.setdefault("STAGED_PLANS_DB_PATH", str(BASE_DIR / "data" / "staged_plans.db"))
    os.environ.setdefault("CHAT_CONFIG_PATH", str(BASE_DIR / "configs" / "config_chat.json"))
    os.environ.setdefault("ATTACHMENTS_DIR", str(BASE_DIR / "data" / "attachments"))
    os.environ.setdefault("ATTACHMENTS_CONFIG_PATH", str(BASE_DIR / "configs" / "config_attachments.json"))

    app.config["SECRET_KEY"] = app_secrets.get("SECRET_KEY") or "dev-insecure-key-change-me"
    raw_db_uri = db_secrets.get("DATABASE_URL") or f"sqlite:///{BASE_DIR / 'data' / 'app.db'}"
    app.config["SQLALCHEMY_DATABASE_URI"] = _resolve_sqlite_uri(raw_db_uri, BASE_DIR)
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    # Prevent bound SQL parameters (which can contain password hashes, emails,
    # etc.) from leaking into str(error)/traceback text when a SQLAlchemy
    # error is logged by the unhandled-exception handler below.
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"hide_parameters": True}

    if config:
        app.config.update(config)

    db.init_app(app)

    with app.app_context():
        db.create_all()

    security_configs = load_security_configs(BASE_DIR / "configs")
    csrf_extension = register_security_pipeline(app, security_configs)

    init_login_manager(app)
    init_mail(app, BASE_DIR / "secrets")
    register_pages(app, csrf=csrf_extension)

    with app.app_context():
        ensure_bootstrap_admin(db.session, BASE_DIR / "secrets")

    @app.errorhandler(401)
    def handle_unauthorized(_error):
        return redirect(url_for("auth.login"))

    @app.errorhandler(403)
    def handle_forbidden(_error):
        return render_template("error_403.html"), 403

    @app.errorhandler(429)
    def handle_rate_limited(_error):
        return render_template("error_429.html"), 429

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        if isinstance(error, HTTPException):
            return error
        db.session.rollback()
        log_service.log_error(
            db.session,
            current_user if current_user.is_authenticated else None,
            source="unhandled_exception",
            message=f"{type(error).__name__}: {error}"[:_MESSAGE_MAX],
            details=traceback.format_exc(),
        )
        raise error

    return app


if __name__ == "__main__":
    flask_app = create_app()
    flask_app.run(debug=True)
