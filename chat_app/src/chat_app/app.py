"""Flask application factory."""

from __future__ import annotations

from flask import Flask

from chat_app.config import settings
from chat_app.routes.capabilities import capabilities_bp
from chat_app.routes.chat import chat_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = settings.secret_key
    app.register_blueprint(chat_bp)
    app.register_blueprint(capabilities_bp)
    return app
