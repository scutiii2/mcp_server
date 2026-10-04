"""Internal, non-user-facing HTTP routes for calls FROM mcp_server.

Not a page: deliberately not under src/pages/ (excluded from that
folder's auto-discovery on purpose, see pages/README.md) - nothing here
should ever appear as a nav tile or Overview card, since there's no
browser session on the other end of these requests.

Authenticated with a static shared secret (X-Internal-Token, compared
constant-time) instead of a login session, since the caller is another
service, not a person - see secrets/secret_internal_api.env. No routes
are registered today; add new service-to-service endpoints here.
"""

from __future__ import annotations

import hmac

from flask import Blueprint, current_app, request

blueprint = Blueprint("internal", __name__)


def _token_valid() -> bool:
    expected = current_app.config.get("INTERNAL_API_TOKEN", "")
    provided = request.headers.get("X-Internal-Token", "")
    # An unset expected token must never validate against an equally
    # empty header - that would turn "forgot to configure this" into
    # "anyone can call it".
    if not expected:
        return False
    return hmac.compare_digest(expected, provided)


def install_internal_routes(app, internal_api_token: str, csrf=None) -> None:
    app.config["INTERNAL_API_TOKEN"] = internal_api_token
    app.register_blueprint(blueprint)
    if csrf is not None:
        # A CSRF token is a browser-session concept - mcp_server has
        # neither a session nor a cookie jar here, and its authorization
        # is the X-Internal-Token header instead (see _token_valid above).
        csrf.exempt(blueprint)
