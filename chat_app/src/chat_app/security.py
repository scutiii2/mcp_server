"""Request-level security for the Flask app.

Everything here runs as ``before_request`` hooks installed by
``install_security(app)``, so it covers every route including ones added
later - a page that forgets a decorator is the usual way this kind of
protection springs a leak.

Why this matters more than it looks: ``/capabilities/api/try/<tool>``
invokes an MCP tool with caller-supplied arguments. Whatever the tools
end up doing - restarting services, writing files, sending mail - this
endpoint is the remote control for it. Three separate things have to be
true before a request gets that far.

**1. The Host header is one we expect.** An IP allowlist alone doesn't
survive DNS rebinding: an attacker's domain can resolve to their server
(so your browser loads their page), then re-resolve to 127.0.0.1, at
which point the page's requests reach *this* app from the browser's own
loopback interface. ``remote_addr`` looks perfectly local. What doesn't
match is the Host header, which still carries the attacker's domain -
so that's what gets checked.

**2. The caller is authenticated.** HTTP Basic against a single shared
credential from the environment. If none is configured, the app still
runs but serves loopback requests only - local development stays
frictionless, while exposing it to a network requires deliberately
setting a password. Note the fallback trusts ``remote_addr``: behind a
reverse proxy every request appears to come from the proxy, i.e. from
loopback, so **you must configure credentials before putting this behind
a proxy**. ``X-Forwarded-For`` is deliberately not consulted - it's
caller-supplied and trivially forged unless a proxy you control
overwrites it.

**3. The request isn't cross-site.** There are no cookies here, so
classic session-riding CSRF doesn't apply - but with the loopback
fallback active there's no credential to ride in the first place, and a
POST from any page you happen to visit would just work. ``Sec-Fetch-Site``
(sent by current browsers, not forgeable by page JavaScript) is the
primary check, with an Origin/Host comparison as the fallback.

Requiring ``Content-Type: application/json`` on the JSON endpoints is a
fourth, quieter layer, enforced at the routes via ``json_body()``. A
cross-origin ``<form>`` can only send form or text content types, and
anything that sets ``application/json`` triggers a CORS preflight the
browser blocks. That single header requirement is what makes a stray
web page unable to reach these endpoints at all.
"""

from __future__ import annotations

import ipaddress
import os
import secrets
from typing import Any
from urllib.parse import urlparse

from flask import Flask, Response, jsonify, request


AUTH_REALM = "chat_app"

# Methods that can change something. GET/HEAD/OPTIONS are exempt from the
# cross-site check on the usual grounds that they're supposed to be safe -
# which holds here, since no GET route in this app mutates anything.
_STATE_CHANGING = {"POST", "PUT", "PATCH", "DELETE"}


def configured_credentials() -> tuple[str, str] | None:
    """The shared credential, or None if auth isn't configured.

    Both halves are required: a username with no password (or vice versa)
    is a half-finished setup, and treating it as "auth enabled" would lock
    you out while treating it as "auth disabled" would silently expose
    things. Neither is a good guess, so it counts as unconfigured and the
    loopback-only fallback applies.
    """
    user = os.getenv("CHAT_AUTH_USER")
    password = os.getenv("CHAT_AUTH_PASSWORD")
    if user and password:
        return user, password
    return None


def _allowed_hosts() -> set[str]:
    raw = os.getenv("CHAT_ALLOWED_HOSTS", "")
    return {entry.strip().lower() for entry in raw.split(",") if entry.strip()}


def _is_loopback_hostname(hostname: str) -> bool:
    if hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _is_loopback_address(address: str | None) -> bool:
    if not address:
        return False
    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:
        return False


def _error(message: str, status: int, headers: dict[str, str] | None = None) -> Response:
    """Always JSON. These endpoints are called by fetch() and by curl, and
    an HTML error page is useless to both."""
    response = jsonify({"status": "error", "message": message})
    response.status_code = status
    for key, value in (headers or {}).items():
        response.headers[key] = value
    return response


def check_host() -> Response | None:
    """Reject a Host header we don't recognize - see DNS rebinding above."""
    host = (request.host or "").lower()
    hostname = host.rsplit(":", 1)[0] if ":" in host and not host.endswith("]") else host
    hostname = hostname.strip("[]")

    if _is_loopback_hostname(hostname):
        return None
    allowed = _allowed_hosts()
    if host in allowed or hostname in allowed:
        return None
    return _error(
        f"Host '{request.host}' is not allowed. Add it to CHAT_ALLOWED_HOSTS "
        f"if this app is meant to be reachable under that name.",
        403,
    )


def check_auth() -> Response | None:
    credentials = configured_credentials()

    if credentials is None:
        if _is_loopback_address(request.remote_addr):
            return None
        return _error(
            "This app is not configured for network access. Set CHAT_AUTH_USER "
            "and CHAT_AUTH_PASSWORD to enable authenticated remote access.",
            403,
        )

    user, password = credentials
    supplied = request.authorization
    if supplied is None or supplied.type != "basic":
        return _error("Authentication required.", 401, {"WWW-Authenticate": f'Basic realm="{AUTH_REALM}"'})

    # compare_digest on both halves, and never short-circuit between them:
    # a plain == leaks how much of the credential was right via timing.
    user_ok = secrets.compare_digest((supplied.username or ""), user)
    password_ok = secrets.compare_digest((supplied.password or ""), password)
    if not (user_ok and password_ok):
        return _error("Invalid credentials.", 401, {"WWW-Authenticate": f'Basic realm="{AUTH_REALM}"'})
    return None


def check_cross_site() -> Response | None:
    """Block state-changing requests initiated by another site."""
    if request.method not in _STATE_CHANGING:
        return None

    # Set by the browser itself and unsettable from page JavaScript, so
    # when it's present it's trustworthy. "none" means a direct navigation
    # (typed URL, bookmark) rather than another site's request.
    fetch_site = request.headers.get("Sec-Fetch-Site")
    if fetch_site is not None:
        if fetch_site in {"same-origin", "none"}:
            return None
        return _error(f"Cross-site {request.method} requests are not allowed.", 403)

    # No Sec-Fetch-Site: either a non-browser client (curl, a script) or a
    # browser too old to send it. Fall back to Origin, which browsers do
    # send on cross-origin state-changing requests.
    origin = request.headers.get("Origin")
    if origin:
        origin_host = (urlparse(origin).netloc or "").lower()
        if origin_host != (request.host or "").lower():
            return _error("Cross-origin requests are not allowed.", 403)
    return None


class UnsupportedMediaType(Exception):
    """Raised by json_body(); turned into a 415 by the app error handler."""


def json_body() -> dict[str, Any]:
    """Parse a JSON request body, insisting on the JSON content type.

    Replaces ``request.get_json(force=True)``, which parsed the body no
    matter what Content-Type claimed. That was the hole: a cross-origin
    HTML form can POST ``text/plain`` without tripping a CORS preflight,
    so any page on the internet could have driven these endpoints. With
    the content type enforced, a form can't reach them and a fetch() that
    sets the header gets preflighted and blocked.

    An empty body is still fine and means "no arguments"; only the wrong
    content type is an error.
    """
    if not request.is_json:
        raise UnsupportedMediaType()
    return request.get_json(silent=True) or {}


def install_security(app: Flask) -> None:
    """Wire every check above into the app.

    Order matters: reject an unrecognized Host before doing anything else,
    then authenticate, then check cross-site. Each returns a response to
    short-circuit, or None to continue.
    """

    @app.before_request
    def _guard() -> Response | None:  # pyright: ignore[reportUnusedFunction]
        for check in (check_host, check_auth, check_cross_site):
            failure = check()
            if failure is not None:
                return failure
        return None

    @app.errorhandler(UnsupportedMediaType)
    def _unsupported_media_type(_exc: UnsupportedMediaType) -> Response:  # pyright: ignore[reportUnusedFunction]
        return _error("Expected Content-Type: application/json.", 415)
