"""One-shot reachability checks for the watch capability.

Each check answers "is it up right now?" and returns a `CheckResult`: `up` is
True or False, or None when the answer is unknown (an app that is not listed).
`detail` is small and safe to store and show: a boolean, a status code, never
page content.

The URL check follows no redirects (a 3xx status is the response itself),
gives up after 10 seconds and reads at most 64 KB of the body, and only when
the caller asks for a text match. Private and loopback addresses are allowed
on purpose: watching a home-lab service is the main use. Because only booleans
and a status code come back, the check cannot be used to read internal pages.

These functions block; callers run them in a watcher thread.
"""

from __future__ import annotations

import http.client
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

URL_TIMEOUT = 10.0
TCP_TIMEOUT = 5.0
MAX_BODY_BYTES = 64 * 1024
MAX_URL = 500

_APP_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_TCP_HOSTNAME = re.compile(r"([A-Za-z0-9.-]+):(\d{1,5})")
_TCP_IPV6 = re.compile(r"\[([0-9A-Fa-f:.]+)\]:(\d{1,5})")


@dataclass(frozen=True)
class CheckResult:
    up: bool | None
    detail: dict[str, Any]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401, ANN001
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def validate_url(url: str) -> str:
    """The trimmed URL, or a ValueError saying why it cannot be watched."""
    text = url.strip()
    if not text:
        raise ValueError("The address is empty.")
    if len(text) > MAX_URL:
        raise ValueError(f"The address is too long (limit {MAX_URL} characters).")
    parts = urllib.parse.urlsplit(text)
    if parts.scheme not in ("http", "https"):
        raise ValueError("only http and https addresses can be watched.")
    if not parts.hostname:
        raise ValueError("The address has no host name.")
    if parts.username or parts.password:
        raise ValueError("Addresses with a user name or password are not allowed.")
    try:
        parts.port  # noqa: B018 - raises ValueError for an out-of-range port
    except ValueError as error:
        raise ValueError("The address has an invalid port.") from error
    return text


def parse_tcp_target(target: str) -> tuple[str, int]:
    """(host, port) from "host:port" or "[ipv6]:port"; ValueError otherwise."""
    text = target.strip()
    match = _TCP_IPV6.fullmatch(text) or _TCP_HOSTNAME.fullmatch(text)
    if not match:
        raise ValueError("A TCP target looks like host:port, for example 192.168.1.5:22.")
    host, port = match.group(1), int(match.group(2))
    if not 1 <= port <= 65535:
        raise ValueError("The port must be between 1 and 65535.")
    return host, port


def valid_app_name(name: str) -> bool:
    return bool(_APP_NAME.fullmatch(name))


def check_url(url: str, contains: str = "", *, timeout: float = URL_TIMEOUT) -> CheckResult:
    """Up when the request answers 200-399 and, if `contains` is given, the body holds that text."""
    request = urllib.request.Request(url, headers={"User-Agent": "ember-watcher/1"})
    body = b""
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            status = response.status
            if contains:
                body = response.read(MAX_BODY_BYTES)
    except urllib.error.HTTPError as error:
        status = error.code
        if contains:
            try:
                body = error.read(MAX_BODY_BYTES)
            except OSError:
                body = b""
        error.close()
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as error:
        return CheckResult(False, {"reachable": False, "error": type(error).__name__})
    detail: dict[str, Any] = {"reachable": True, "status": status}
    found = True
    if contains:
        found = contains.lower() in body.decode("utf-8", errors="replace").lower()
        detail["contains"] = found
    return CheckResult(200 <= status < 400 and found, detail)


def check_tcp(host: str, port: int, *, timeout: float = TCP_TIMEOUT) -> CheckResult:
    """Up when a TCP connection to host:port succeeds."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return CheckResult(True, {"open": True})
    except OSError:
        return CheckResult(False, {"open": False})


def check_app(name: str, list_apps: Callable[[], Any]) -> CheckResult:
    """Up when server_manager lists the app as running; unknown (None) when it is not listed at all."""
    for app in list_apps().apps:
        if app.name == name:
            return CheckResult(app.status == "running", {"found": True, "status": app.status})
    return CheckResult(None, {"found": False})
