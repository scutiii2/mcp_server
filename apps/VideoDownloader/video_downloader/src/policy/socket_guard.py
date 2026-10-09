"""Block connections to non-public addresses, including redirect targets.

yt-dlp follows HTTP redirects inside its own HTTP handler, so a URL that passed
UrlPolicy could still redirect to http://127.0.0.1/... The guard wraps
socket.getaddrinfo, which every outgoing connection goes through (urllib,
urllib3, http.client), and refuses disallowed answers while a thread is inside
``active()``. It also closes DNS-rebinding gaps, because the checked answer is
the one the connection uses. Threads outside ``active()`` (uvicorn, the event
loop's resolver) are untouched.

The default rule also refuses ports other than 80 and 443, so a redirect can't
reach a non-web service on a public host either.

External downloaders (ffmpeg and friends) open their own sockets, which this
guard can't see; ytdlp.py refuses them while the guard is active and refuses
live streams up front.

libcurl (yt-dlp's curl_cffi impersonation handler) resolves names and follows
redirects in C, also out of sight. curl_guard.py checks every curl_cffi hop
with ``check_host`` and pins libcurl to the checked IPs.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from src.policy.url_policy import ALLOWED_PORTS, is_public_ip

AllowFn = Callable[[str, int | None], bool]


class BlockedAddressError(OSError):
    """Raised instead of connecting to a non-public address."""


def _allow_public(ip: str, port: int | None) -> bool:
    return is_public_ip(ip) and port in ALLOWED_PORTS


def _as_port(port: object) -> int | None:
    try:
        return int(port)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


_installed: list[SocketGuard] = []  # in install order; curl_guard asks which one is active


def active_guard() -> SocketGuard | None:
    """The most recently installed guard that is active in this thread, if any."""
    for guard in reversed(_installed):
        if guard.is_active:
            return guard
    return None


class SocketGuard:
    def __init__(self, allow: AllowFn = _allow_public) -> None:
        self._allow = allow
        self._local = threading.local()
        self._original: Callable | None = None

    def install(self) -> None:
        """Replace socket.getaddrinfo with the guarded wrapper (idempotent).

        Also routes yt-dlp's curl_cffi requests through ``check_host`` (see curl_guard.py).
        """
        from src.policy import curl_guard  # late import: curl_guard imports this module

        curl_guard.install()
        if self._original is None:
            self._original = socket.getaddrinfo
            socket.getaddrinfo = self._getaddrinfo
            _installed.append(self)

    def uninstall(self) -> None:
        if self._original is not None:
            socket.getaddrinfo = self._original
            self._original = None
            if self in _installed:
                _installed.remove(self)

    @property
    def is_active(self) -> bool:
        """True while this thread is inside ``active()``."""
        return getattr(self._local, "depth", 0) > 0

    def check_host(self, host: str, port: int) -> list[str]:
        """Resolve ``host`` through the guarded lookup and return the checked IPs.

        For clients that resolve on their own (libcurl): connect only to the returned IPs.
        Inside ``active()`` a disallowed answer raises BlockedAddressError and sets ``blocked``.
        """
        if self._original is None:
            raise RuntimeError("SocketGuard.check_host needs the guard installed")
        results = self._getaddrinfo(host, port, type=socket.SOCK_STREAM)
        ips: list[str] = []
        for _family, _type, _proto, _canon, sockaddr in results:
            ip = str(sockaddr[0])
            if ip not in ips:
                ips.append(ip)
        return ips

    @contextmanager
    def active(self) -> Iterator[None]:
        """Guard every lookup made by this thread inside the block."""
        depth = getattr(self._local, "depth", 0)
        if depth == 0:
            self._local.blocked = False
        self._local.depth = depth + 1
        try:
            yield
        finally:
            self._local.depth -= 1

    @property
    def blocked(self) -> bool:
        """True if this thread's current ``active()`` block hit a blocked address."""
        return bool(getattr(self._local, "blocked", False))

    def _getaddrinfo(self, host, port, *args, **kwargs):
        assert self._original is not None
        results = self._original(host, port, *args, **kwargs)
        if getattr(self._local, "depth", 0) > 0:
            number = _as_port(port)
            for _family, _type, _proto, _canon, sockaddr in results:
                if not self._allow(str(sockaddr[0]), number):
                    self._local.blocked = True
                    raise BlockedAddressError("Connection to a non-public address was blocked.")
        return results


GUARD = SocketGuard()
