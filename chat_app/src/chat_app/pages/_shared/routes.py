"""Assets shared across page templates - currently just the sidebar's CSS
and JS, included via Jinja from chat/capabilities/account's own templates
(see pages/_shared/template/sidebar.html). No routes of its own: this
blueprint exists only to give that directory a ``shared.static`` Flask
endpoint, the same static-folder-doubles-as-template-folder trick every
other page blueprint uses - see app.py's docstring.
"""

from __future__ import annotations

from flask import Blueprint


shared_bp = Blueprint(
    "shared",
    __name__,
    static_folder="template",
    static_url_path="/pages/shared/assets",
)
