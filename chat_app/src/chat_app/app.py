"""Flask application factory.

Pages under ``pages/`` are self-contained feature folders: each owns its
own ``routes.py`` and its own ``template/`` directory holding
``index.html``/``styles.css``/``script.js`` as separate files. Two gotchas
that come with that layout, both handled here rather than left as
per-page boilerplate:

1. Flask's default per-blueprint ``template_folder`` merges every
   blueprint's templates into one shared, unnamespaced search path - so
   two pages each naming their template ``index.html`` would silently
   collide (whichever blueprint was registered first would "win" for
   *every* page's render_template("index.html") call, not just its own).
   The ``PrefixLoader`` below keys each page's folder by name instead, so
   routes render "chat/index.html" / "capabilities/index.html" and can
   never resolve to the wrong page's file.
2. Jinja template folders aren't web-servable by default (Flask never
   exposes raw files from them to the browser). Each blueprint sets its
   own ``static_folder`` to that *same* ``template/`` directory - a
   separate Flask mechanism from the Jinja loader above - so styles.css
   and script.js become fetchable at runtime without needing a
   conventional top-level ``static/`` folder.
"""

from __future__ import annotations

from pathlib import Path

from flask import Flask
from jinja2 import FileSystemLoader, PrefixLoader

from chat_app.config import settings
from chat_app.pages.capabilities.routes import capabilities_bp
from chat_app.pages.chat.routes import chat_bp


PAGES_DIR = Path(__file__).parent / "pages"


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = settings.secret_key
    app.register_blueprint(chat_bp)
    app.register_blueprint(capabilities_bp)

    app.jinja_loader = PrefixLoader(
        {
            "chat": FileSystemLoader(str(PAGES_DIR / "chat" / "template")),
            "capabilities": FileSystemLoader(str(PAGES_DIR / "capabilities" / "template")),
        }
    )

    return app
