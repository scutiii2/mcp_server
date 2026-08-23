"""Cross-site request rejection for state-changing requests.

Stands in for a CSRF token on routes that are exempted from Flask-WTF's
CSRFProtect (see pages/__index__.py's CSRF_EXEMPT support) - Chat and
Capabilities' JSON fetch() calls don't carry one. Sec-Fetch-Site is set
by the browser itself and unsettable from page JavaScript, so when it's
present it's trustworthy; Origin is the fallback for a browser too old
to send Sec-Fetch-Site (or a non-browser client, which sends neither and
passes through - nothing to check against). Ported from
chat_app.security.check_cross_site (MCPArchitecture), which this
project's security pipeline had no equivalent of.
"""

from __future__ import annotations

from urllib.parse import urlparse

from flask import abort, request

_STATE_CHANGING = {"POST", "PUT", "PATCH", "DELETE"}


def check_cross_site() -> None:
    if request.method not in _STATE_CHANGING:
        return

    fetch_site = request.headers.get("Sec-Fetch-Site")
    if fetch_site is not None:
        if fetch_site in {"same-origin", "none"}:
            return
        abort(403, description=f"Cross-site {request.method} requests are not allowed.")

    origin = request.headers.get("Origin")
    if origin:
        origin_host = (urlparse(origin).netloc or "").lower()
        if origin_host != (request.host or "").lower():
            abort(403, description="Cross-origin requests are not allowed.")
