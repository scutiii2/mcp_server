"""Tests for the watch capability's reachability checks, against real local sockets."""

from __future__ import annotations

import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from src.capabilities.watchers.utils import checks
from src.capabilities.watchers.utils.checks import (
    check_app,
    check_tcp,
    check_url,
    parse_tcp_target,
    valid_app_name,
    validate_url,
)


@pytest.fixture
def server():
    """A local HTTP server whose answers the test sets in `routes`: path -> (status, headers, body); status None sleeps."""
    routes: dict[str, tuple] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            status, headers, body = routes.get(self.path, (404, {}, b"missing"))
            if status is None:
                time.sleep(0.5)
                status, headers, body = 200, {}, b"late"
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield SimpleNamespace(base=f"http://127.0.0.1:{httpd.server_address[1]}", routes=routes)
    httpd.shutdown()
    httpd.server_close()


def closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_a_200_is_up(server):
    server.routes["/ok"] = (200, {}, b"hello")

    result = check_url(server.base + "/ok")

    assert result.up is True and result.detail == {"reachable": True, "status": 200}


def test_contains_is_case_insensitive_and_reported(server):
    server.routes["/page"] = (200, {}, b"Welcome Back")

    found = check_url(server.base + "/page", "welcome")
    absent = check_url(server.base + "/page", "goodbye")

    assert found.up is True and found.detail["contains"] is True
    assert absent.up is False and absent.detail == {"reachable": True, "status": 200, "contains": False}


def test_error_statuses_are_down_but_reachable(server):
    server.routes["/boom"] = (500, {}, b"oops")

    assert check_url(server.base + "/boom").detail == {"reachable": True, "status": 500}
    assert check_url(server.base + "/boom").up is False
    assert check_url(server.base + "/nope").up is False


def test_a_redirect_is_not_followed_and_counts_as_a_response(server):
    server.routes["/old"] = (302, {"Location": "/ok"}, b"")
    server.routes["/ok"] = (200, {}, b"fine")

    result = check_url(server.base + "/old")

    assert result.detail["status"] == 302 and result.up is True


def test_a_refused_connection_and_a_timeout_are_down_and_unreachable(server):
    refused = check_url(f"http://127.0.0.1:{closed_port()}/")
    server.routes["/slow"] = (None, {}, b"")
    slow = check_url(server.base + "/slow", timeout=0.1)

    assert refused.up is False and refused.detail["reachable"] is False
    assert slow.up is False and slow.detail["reachable"] is False


def test_validate_url_accepts_http_and_https_only_without_credentials():
    assert validate_url("  https://example.com/a?b=1 ") == "https://example.com/a?b=1"
    for bad in ("ftp://example.com", "file:///etc/passwd", "http://user:pw@example.com/", "http:///path", "", "http://x:99999/"):
        with pytest.raises(ValueError):
            validate_url(bad)
    with pytest.raises(ValueError, match="too long"):
        validate_url("http://example.com/" + "a" * 600)


def test_parse_tcp_target():
    assert parse_tcp_target("example.com:80") == ("example.com", 80)
    assert parse_tcp_target(" 192.168.1.5:22 ") == ("192.168.1.5", 22)
    assert parse_tcp_target("[::1]:8080") == ("::1", 8080)
    for bad in ("nohost", "host:0", "host:70000", "ho st:80", "host:abc", ":80", "[::1]"):
        with pytest.raises(ValueError):
            parse_tcp_target(bad)


def test_check_tcp_sees_open_and_closed_ports():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        assert check_tcp("127.0.0.1", port).up is True
    assert check_tcp("127.0.0.1", closed_port(), timeout=1.0).up is False


def test_check_tcp_treats_an_unresolvable_host_as_down():
    assert check_tcp("a" * 70 + ".com", 80, timeout=1.0).up is False
    assert check_tcp("..", 80, timeout=1.0).up is False


def fake_apps(*pairs):
    return lambda: SimpleNamespace(apps=[SimpleNamespace(name=name, status=status) for name, status in pairs])


def test_check_app_running_stopped_and_unknown():
    apps = fake_apps(("web", "running"), ("db", "exited"))

    assert check_app("web", apps).up is True
    assert check_app("db", apps) .up is False
    assert check_app("db", apps).detail == {"found": True, "status": "exited"}
    missing = check_app("ghost", apps)
    assert missing.up is None and missing.detail == {"found": False}


def test_valid_app_name():
    assert valid_app_name("my-app_1.2") and not valid_app_name("bad name") and not valid_app_name("") and not valid_app_name("-x")
    assert checks.MAX_BODY_BYTES == 64 * 1024
