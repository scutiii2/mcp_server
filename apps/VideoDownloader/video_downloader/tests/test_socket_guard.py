from __future__ import annotations

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from yt_dlp import YoutubeDL

from src.policy.socket_guard import BlockedAddressError, SocketGuard, _allow_public


class _Server:
    """A tiny local HTTP server that records requests; optionally redirects."""

    def __init__(self, redirect_to: str | None = None) -> None:
        self.hits: list[str] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.hits.append(self.path)
                if redirect_to:
                    self.send_response(302)
                    self.send_header("Location", redirect_to)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                else:
                    body = b"ok"
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def guard():
    created: list[SocketGuard] = []

    def make(allow):
        g = SocketGuard(allow=allow)
        g.install()
        created.append(g)
        return g

    yield make
    for g in reversed(created):
        g.uninstall()


def test_install_and_uninstall_restore_getaddrinfo(guard):
    original = socket.getaddrinfo
    g = guard(lambda ip, port: True)
    assert socket.getaddrinfo is not original
    g.uninstall()
    assert socket.getaddrinfo is original


def test_inactive_guard_lets_everything_through(guard):
    guard(lambda ip, port: False)
    assert socket.getaddrinfo("127.0.0.1", 80)  # not inside active(): untouched


def test_active_guard_blocks_disallowed_address(guard):
    g = guard(lambda ip, port: False)
    with g.active():
        with pytest.raises(BlockedAddressError):
            socket.getaddrinfo("127.0.0.1", 80)
        assert g.blocked
    with g.active():
        assert not g.blocked  # flag resets on a fresh outermost entry


@pytest.mark.parametrize(
    "ip, port, allowed",
    [
        ("93.184.216.34", 443, True),
        ("93.184.216.34", 80, True),
        ("93.184.216.34", None, True),
        ("93.184.216.34", 8080, False),
        ("93.184.216.34", 22, False),
        ("127.0.0.1", 443, False),
    ],
)
def test_default_rule_allows_public_web_ports_only(ip, port, allowed):
    assert _allow_public(ip, port) is allowed


def test_yt_dlp_redirect_to_blocked_target_is_stopped(guard):
    """The first hop is allowed, the redirect target is not: its server must never be hit."""
    target = _Server()
    first = _Server(redirect_to=f"http://127.0.0.1:{target.port}/secret")
    try:
        g = guard(lambda ip, port: port == first.port)
        with YoutubeDL({"quiet": True, "no_warnings": True}) as ydl, g.active():
            with pytest.raises(Exception):
                ydl.urlopen(f"http://127.0.0.1:{first.port}/start").read()
            assert g.blocked
        assert first.hits == ["/start"]
        assert target.hits == []
    finally:
        first.close()
        target.close()
