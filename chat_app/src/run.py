import argparse
import logging
import os
import traceback
from pathlib import Path

# Parsed and applied before any project import below - src.services.llm.settings
# resolves mcp_server_url from the environment at import time (see that
# module), same reasoning as ai_agent/src/server.py's --gateway/--role.
_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument(
    "--mcp-url",
    help=(
        "Override this run's mcp_server URL (src/services/llm/settings.py), "
        "e.g. http://127.0.0.1:8010/mcp to point at a different host/port. "
        "Takes precedence over MCP_SERVER_URL."
    ),
)
_args, _ = _parser.parse_known_args()
if _args.mcp_url:
    os.environ["MCP_SERVER_URL"] = _args.mcp_url

from flask import Flask, redirect, render_template, request, url_for
from flask_login import current_user
from werkzeug.exceptions import HTTPException

from src.internal_routes import install_internal_routes
from src.models import db
from src.pages.__index__ import register_pages
from src.services import log_service
from src.services.auth_service import ensure_bootstrap_admin, init_login_manager
from src.services.config_validation import install_config_guard
from src.services.db_migrations import apply_additive_column_migrations, drop_retired_tables
from src.services.email_service import init_mail
from src.services.security.pipeline import load_security_configs, register_security_pipeline
from src.utils.config_loader import load_env_secrets, load_json_config

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
# data/, configs/ and secrets/ all live one level up from src/ (repo root
# of this project), not under BASE_DIR - nothing in them is package code,
# so none needs to sit next to the modules that use it.
APP_DIR = BASE_DIR.parent
DATA_DIR = APP_DIR / "data"

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

    app_secrets = load_env_secrets(APP_DIR / "secrets" / "secret_app.env")
    db_secrets = load_env_secrets(APP_DIR / "secrets" / "secret_db.env")
    llm_secrets = load_env_secrets(APP_DIR / "secrets" / "secret_llm.env")
    mcp_secrets = load_env_secrets(APP_DIR / "secrets" / "secret_mcp.env")
    internal_api_secrets = load_env_secrets(APP_DIR / "secrets" / "secret_internal_api.env")
    for key, value in llm_secrets.items():
        if value:
            os.environ.setdefault(key, value)
    for key, value in mcp_secrets.items():
        if value:
            os.environ.setdefault(key, value)
    # DATA_DIR-resolved, not CWD-relative - same reasoning as
    # _resolve_sqlite_uri below for app.db. A real CHATS_DB_PATH env var
    # (including one already set via secret_llm.env above) still wins -
    # setdefault is a no-op once the key is already present.
    os.environ.setdefault("CHATS_DB_PATH", str(DATA_DIR / "chats.db"))
    os.environ.setdefault("CAPABILITY_CACHE_PATH", str(DATA_DIR / "capability_tool_cache.json"))
    os.environ.setdefault("USAGE_DB_PATH", str(DATA_DIR / "usage.db"))

    # A broken config must not crash boot: the config guard below redirects
    # every page to the ConfigIssues page, which lists what is wrong.
    try:
        app.config["APP_NAME"] = load_json_config(APP_DIR / "configs" / "config_app.json").get(
            "app_name", "Chat"
        )
    except (OSError, ValueError, AttributeError):
        app.config["APP_NAME"] = "Chat"
    app.config["SECRET_KEY"] = app_secrets.get("SECRET_KEY") or "dev-insecure-key-change-me"
    raw_db_uri = db_secrets.get("DATABASE_URL") or f"sqlite:///{DATA_DIR / 'app.db'}"
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
        # create_all() only creates missing tables - it never alters an
        # existing one when a model gains a new column, which is exactly
        # how Account.email_verified took prod down on startup. This closes
        # that gap for the next column someone adds; see db_migrations.py.
        added_columns = apply_additive_column_migrations(db.engine, db.metadata)
        if added_columns:
            logger.warning("Added missing column(s) to existing tables: %s", ", ".join(added_columns))
        dropped_tables = drop_retired_tables(db.engine)
        if dropped_tables:
            logger.warning("Dropped retired table(s): %s", ", ".join(dropped_tables))

    try:
        security_configs = load_security_configs(APP_DIR / "configs")
    except (OSError, ValueError):
        security_configs = {}
    csrf_extension = register_security_pipeline(app, security_configs)
    install_config_guard(app, APP_DIR)

    init_login_manager(app)
    init_mail(app, APP_DIR / "secrets")
    register_pages(app, csrf=csrf_extension)
    install_internal_routes(app, internal_api_secrets.get("INTERNAL_API_TOKEN", ""), csrf=csrf_extension)

    with app.app_context():
        ensure_bootstrap_admin(db.session, APP_DIR / "secrets")

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
    # CHAT_APP_PORT lets a second instance run alongside the default one
    # (e.g. server_launcher's auto-assigned port when 5000 is taken) -
    # Flask's own run() has no env-var port lookup of its own.
    flask_app.run(port=int(os.getenv("CHAT_APP_PORT", "5000")), debug=True)
