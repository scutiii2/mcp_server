"""Impersonated (curl_cffi) requests go through the socket guard too.

libcurl resolves names and follows redirects itself, so these tests drive yt-dlp's
curl_cffi handler against local servers and check that every hop is address-checked,
pinned to the checked IP and that redirects are followed by us, not by libcurl.
"""

from __future__ import annotations

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from curl_cffi import Curl
from curl_cffi.const import CurlOpt
from yt_dlp import YoutubeDL
from yt_dlp.networking import Request
from yt_dlp.networking.exceptions import HTTPError, TransportError
from yt_dlp.networking.impersonate import ImpersonateTarget

from src.policy import curl_guard
from src.policy.socket_guard import BlockedAddressError, SocketGuard

CHROME = ImpersonateTarget("chrome")


class _Server:
    """Local HTTP server. ``routes`` maps a path to (status, headers, body); unknown paths answer 200 "ok"."""

    def __init__(self, routes: dict[str, tuple[int, dict[str, str], bytes]] | None = None) -> None:
        self.routes = routes or {}
        self.hits: list[tuple[str, str, bytes, str]] = []  # (method, path, body, Host header)
        self.headers: list[dict[str, str]] = []  # request headers (lower-case names), one per hit
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                outer.hits.append((self.command, self.path, body, self.headers.get("Host", "")))
                outer.headers.append({k.lower(): v for k, v in self.headers.items()})
                status, headers, payload = outer.routes.get(self.path, (200, {}, b"ok"))
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(payload)

            do_GET = do_POST = do_HEAD = _handle

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def paths(self) -> list[str]:
        return [hit[1] for hit in self.hits]

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def servers():
    made: list[_Server] = []

    def make(routes=None) -> _Server:
        server = _Server(routes)
        made.append(server)
        return server

    yield make
    for server in made:
        server.close()


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


@pytest.fixture(autouse=True)
def _unpatch_curl_handler():
    """Every test leaves yt-dlp's curl_cffi handler as it found it (SocketGuard.install() patches it too)."""
    yield
    curl_guard.uninstall()


@pytest.fixture
def ydl():
    curl_guard.install()
    with YoutubeDL({"quiet": True, "no_warnings": True, "proxy": ""}) as instance:
        yield instance
    curl_guard.uninstall()


def _fetch(ydl: YoutubeDL, url: str, **kwargs):
    return ydl.urlopen(Request(url, extensions={"impersonate": CHROME}, **kwargs))


def _redirect(location: str, status: int = 302):
    return (status, {"Location": location}, b"")


def test_request_goes_through_curl_cffi(ydl, servers):
    server = servers()
    response = _fetch(ydl, f"{server.base}/x")
    assert response.read() == b"ok"
    assert response.extensions.get("impersonate") is not None  # served by the curl_cffi handler


def test_first_hop_to_disallowed_address_is_refused(ydl, servers, guard):
    server = servers()
    g = guard(lambda ip, port: False)
    with g.active():
        with pytest.raises(TransportError) as caught:
            _fetch(ydl, f"{server.base}/secret").read()
        assert g.blocked
    assert isinstance(caught.value.cause, BlockedAddressError)
    assert server.hits == []


def test_redirect_to_disallowed_address_is_not_followed(ydl, servers, guard):
    target = servers()
    first = servers({"/start": _redirect(f"{target.base}/secret")})
    g = guard(lambda ip, port: port == first.port)
    with g.active():
        with pytest.raises(TransportError) as caught:
            _fetch(ydl, f"{first.base}/start").read()
        assert g.blocked
    assert isinstance(caught.value.cause, BlockedAddressError)
    assert first.paths() == ["/start"]
    assert target.hits == []


def test_redirect_chain_to_allowed_addresses_returns_final_body(ydl, servers, guard):
    final = servers({"/end": (200, {}, b"final body")})
    middle = servers({"/mid": _redirect(f"{final.base}/end", 301)})
    first = servers({"/start": _redirect(f"{middle.base}/mid")})
    g = guard(lambda ip, port: ip == "127.0.0.1")
    with g.active():
        response = _fetch(ydl, f"{first.base}/start")
        assert response.read() == b"final body"
        assert response.url == f"{final.base}/end"
        assert not g.blocked
    assert (first.paths(), middle.paths(), final.paths()) == (["/start"], ["/mid"], ["/end"])


def test_relative_location_and_303_turns_post_into_get(ydl, servers, guard):
    server = servers({"/dir/form": _redirect("done", 303), "/dir/done": (200, {}, b"thanks")})
    g = guard(lambda ip, port: ip == "127.0.0.1")
    with g.active():
        response = _fetch(ydl, f"{server.base}/dir/form", data=b"a=1")
        assert response.read() == b"thanks"
    assert [(m, p, b) for m, p, b, _h in server.hits] == [("POST", "/dir/form", b"a=1"), ("GET", "/dir/done", b"")]


def test_307_keeps_method_and_body(ydl, servers, guard):
    server = servers({"/a": _redirect("/b", 307), "/b": (200, {}, b"kept")})
    g = guard(lambda ip, port: ip == "127.0.0.1")
    with g.active():
        assert _fetch(ydl, f"{server.base}/a", data=b"payload").read() == b"kept"
    assert [(m, p, b) for m, p, b, _h in server.hits] == [("POST", "/a", b"payload"), ("POST", "/b", b"payload")]


def test_more_than_five_redirects_raises(ydl, servers, guard):
    server = servers({f"/r{i}": _redirect(f"/r{i + 1}") for i in range(10)})
    g = guard(lambda ip, port: ip == "127.0.0.1")
    with g.active():
        with pytest.raises(HTTPError) as caught:
            _fetch(ydl, f"{server.base}/r0")
        assert caught.value.redirect_loop
    assert server.paths() == [f"/r{i}" for i in range(6)]  # first request plus 5 followed redirects


def test_redirect_to_non_http_scheme_is_refused(ydl, servers, guard):
    server = servers({"/a": _redirect("ftp://127.0.0.1/file")})
    g = guard(lambda ip, port: ip == "127.0.0.1")
    with g.active():
        with pytest.raises(TransportError):
            _fetch(ydl, f"{server.base}/a").read()
    assert server.paths() == ["/a"]


def test_outside_active_block_nothing_is_checked(ydl, servers, guard):
    target = servers()
    first = servers({"/start": _redirect(f"{target.base}/end")})
    guard(lambda ip, port: False)  # installed but not active in this thread
    assert _fetch(ydl, f"{first.base}/start").read() == b"ok"
    assert first.paths() == ["/start"] and target.paths() == ["/end"]


def test_connection_is_pinned_to_the_checked_ip(ydl, servers, guard, monkeypatch):
    """libcurl can't resolve pinned.invalid itself; it only connects because we pinned the checked IP."""
    server = servers({"/x": (200, {}, b"pinned")})
    real = socket.getaddrinfo

    def fake_dns(host, port, *args, **kwargs):
        if host == "pinned.invalid":
            return real("127.0.0.1", port, *args, **kwargs)
        return real(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", fake_dns)
    resolve_values: list = []
    real_setopt = Curl.setopt

    def spy(self, option, value):
        if option == CurlOpt.RESOLVE:
            resolve_values.append(value)
        return real_setopt(self, option, value)

    monkeypatch.setattr(Curl, "setopt", spy)
    seen: list[tuple[str, int | None]] = []

    def allow(ip, port):
        seen.append((ip, port))
        return ip == "127.0.0.1" and port == server.port

    g = guard(allow)
    with g.active():
        response = _fetch(ydl, f"http://pinned.invalid:{server.port}/x")
        assert response.read() == b"pinned"
    assert ("127.0.0.1", server.port) in seen
    assert [f"pinned.invalid:{server.port}:127.0.0.1"] in resolve_values
    assert server.hits[0][3] == f"pinned.invalid:{server.port}"


def test_check_host_returns_checked_ips(guard):
    g = guard(lambda ip, port: True)
    with g.active():
        assert "127.0.0.1" in g.check_host("127.0.0.1", 80)
    blocking = guard(lambda ip, port: False)
    with blocking.active():
        with pytest.raises(OSError):
            blocking.check_host("127.0.0.1", 80)
        assert blocking.blocked


def test_installing_a_socket_guard_patches_the_curl_handler(guard):
    from yt_dlp.networking._curlcffi import CurlCFFIRH

    guard(lambda ip, port: True)
    assert getattr(CurlCFFIRH._create_instance, "_vd_guarded", False)
    session = CurlCFFIRH._create_instance(None)
    assert isinstance(session, curl_guard.GuardedSession)
    session.close()


_PROXY_ENV = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")


def _env_proxy(monkeypatch, proxy: _Server) -> None:
    for name in ("no_proxy", "NO_PROXY"):
        monkeypatch.delenv(name, raising=False)
    for name in _PROXY_ENV:
        monkeypatch.setenv(name, proxy.base)


def _pinned_dns(monkeypatch, host: str = "pinned.invalid") -> None:
    real = socket.getaddrinfo

    def fake_dns(name, port, *args, **kwargs):
        return real("127.0.0.1" if name == host else name, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", fake_dns)


def test_proxy_environment_variables_are_ignored_while_guarded(ydl, servers, guard, monkeypatch):
    """With yt-dlp's proxy set to "", libcurl would fall back to *_proxy env vars and let the proxy resolve names."""
    target = servers({"/x": (200, {}, b"direct")})
    proxy = servers()
    _env_proxy(monkeypatch, proxy)
    _pinned_dns(monkeypatch)
    g = guard(lambda ip, port: ip == "127.0.0.1" and port == target.port)
    with g.active():
        assert _fetch(ydl, f"http://pinned.invalid:{target.port}/x").read() == b"direct"
    assert proxy.hits == []
    assert target.paths() == ["/x"]


def test_configured_proxy_is_refused_while_guarded(servers, guard):
    target = servers()
    proxy = servers()
    curl_guard.install()
    g = guard(lambda ip, port: ip == "127.0.0.1")
    with YoutubeDL({"quiet": True, "no_warnings": True, "proxy": proxy.base}) as instance:
        with g.active():
            with pytest.raises(TransportError) as caught:
                _fetch(instance, f"{target.base}/x").read()
    assert isinstance(caught.value.cause, curl_guard.BlockedCurlRequest)
    assert proxy.hits == [] and target.hits == []


def test_proxy_environment_variables_do_not_reach_other_handlers(ydl, servers, monkeypatch):
    target = servers({"/x": (200, {}, b"direct")})
    proxy = servers()
    _env_proxy(monkeypatch, proxy)
    assert ydl.urlopen(Request(f"{target.base}/x")).read() == b"direct"  # urllib / requests handler
    assert proxy.hits == []
    assert target.paths() == ["/x"]


def test_uninstall_restores_the_original_session_factory():
    from yt_dlp.networking._curlcffi import CurlCFFIRH

    curl_guard.uninstall()
    original = CurlCFFIRH._create_instance
    curl_guard.install()
    assert CurlCFFIRH._create_instance is not original
    curl_guard.uninstall()
    assert CurlCFFIRH._create_instance is original
    session = CurlCFFIRH._create_instance(None)
    assert not isinstance(session, curl_guard.GuardedSession)
    session.close()
    curl_guard.uninstall()  # idempotent
    assert CurlCFFIRH._create_instance is original


def test_non_stream_request_closes_every_hop_handle(servers, guard, monkeypatch):
    server = servers({"/a": _redirect("/b"), "/b": (200, {}, b"done")})
    copies: list[Curl] = []
    real_dup = Curl.duphandle

    def spy(self):
        copy = real_dup(self)
        copies.append(copy)
        return copy

    monkeypatch.setattr(Curl, "duphandle", spy)
    g = guard(lambda ip, port: ip == "127.0.0.1")
    session = curl_guard.GuardedSession()
    try:
        with g.active():
            response = session.request(method="GET", url=f"{server.base}/a")
        assert response.content == b"done"
        assert server.paths() == ["/a", "/b"]
        assert len(copies) == 3  # template + one per hop
        assert all(copy._curl is None for copy in copies)  # all closed
        response.close()  # closing the response afterwards stays harmless
    finally:
        session.close()


@pytest.fixture
def handler_registry():
    """yt-dlp's request handler registry, restored in place after the test."""
    from yt_dlp.networking.common import _REQUEST_HANDLERS

    saved = dict(_REQUEST_HANDLERS)
    yield _REQUEST_HANDLERS
    curl_guard.uninstall()
    _REQUEST_HANDLERS.clear()
    _REQUEST_HANDLERS.update(saved)


def _assert_impersonation_unavailable(servers) -> None:
    server = servers()
    with YoutubeDL({"quiet": True, "no_warnings": True, "proxy": ""}) as instance:
        with pytest.raises(Exception):
            _fetch(instance, f"{server.base}/x").read()
    assert server.hits == []


def test_normal_install_keeps_the_curl_handler_registered(handler_registry):
    from yt_dlp.networking._curlcffi import CurlCFFIRH

    curl_guard.install()
    assert handler_registry.get("CurlCFFI") is CurlCFFIRH
    assert getattr(CurlCFFIRH._create_instance, "_vd_guarded", False)


def test_missing_guard_dependency_unregisters_the_curl_handler(handler_registry, servers, monkeypatch, caplog):
    import yt_dlp.networking._helper as helper

    monkeypatch.delattr(helper, "get_redirect_method")
    curl_guard.install()
    assert "CurlCFFI" not in handler_registry
    assert any(r.levelname == "ERROR" for r in caplog.records)
    _assert_impersonation_unavailable(servers)


def test_send_not_using_get_instance_unregisters_the_curl_handler(handler_registry, servers, monkeypatch):
    from yt_dlp.networking._curlcffi import CurlCFFIRH

    def _send(self, request):  # a yt-dlp version that builds its session another way
        return curl_cffi_session_from_somewhere_else(request)  # noqa: F821

    monkeypatch.setattr(CurlCFFIRH, "_send", _send)
    curl_guard.install()
    assert "CurlCFFI" not in handler_registry
    _assert_impersonation_unavailable(servers)


def test_uninstall_registers_an_unregistered_curl_handler_again(handler_registry, monkeypatch):
    import yt_dlp.networking._helper as helper
    from yt_dlp.networking._curlcffi import CurlCFFIRH

    monkeypatch.delattr(helper, "get_redirect_method")
    curl_guard.install()
    assert "CurlCFFI" not in handler_registry
    curl_guard.uninstall()
    assert handler_registry.get("CurlCFFI") is CurlCFFIRH


def test_guarded_requests_go_through_the_guarded_session(ydl, servers, guard, monkeypatch):
    """Post-install self-check, end to end: CurlCFFIRH._send obtains its session via _get_instance -> GuardedSession."""
    server = servers()
    used: list = []
    real = curl_guard.GuardedSession._guarded_request

    def spy(self, *args, **kwargs):
        used.append(self)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(curl_guard.GuardedSession, "_guarded_request", spy)
    g = guard(lambda ip, port: ip == "127.0.0.1")
    with g.active():
        assert _fetch(ydl, f"{server.base}/x").read() == b"ok"
    assert used and all(isinstance(s, curl_guard.GuardedSession) for s in used)


def test_install_raises_when_the_handler_cannot_be_unregistered(handler_registry, monkeypatch):
    import yt_dlp.networking._helper as helper
    import yt_dlp.networking.common as common

    monkeypatch.delattr(helper, "get_redirect_method")
    monkeypatch.setattr(common, "_REQUEST_HANDLERS", None)
    with pytest.raises(RuntimeError):
        curl_guard.install()


_SECRETS = {"Cookie": "session=secret", "Authorization": "Bearer secret"}


def test_credentials_are_kept_on_a_same_origin_redirect(ydl, servers, guard):
    server = servers({"/a": _redirect("/b")})
    g = guard(lambda ip, port: ip == "127.0.0.1")
    with g.active():
        assert _fetch(ydl, f"{server.base}/a", headers=_SECRETS).read() == b"ok"
    assert [(h.get("cookie"), h.get("authorization")) for h in server.headers] == [
        ("session=secret", "Bearer secret")
    ] * 2


def _assert_credentials_stripped(first: _Server, final: _Server) -> None:
    start, end = first.headers[0], final.headers[-1]
    assert (start.get("cookie"), start.get("authorization")) == ("session=secret", "Bearer secret")
    assert final.paths()[-1] == "/end"
    assert "cookie" not in end and "authorization" not in end


def test_credentials_are_stripped_on_a_redirect_to_another_port(ydl, servers, guard):
    final = servers()
    first = servers({"/start": _redirect(f"{final.base}/end")})  # same host, other port
    g = guard(lambda ip, port: ip == "127.0.0.1")
    with g.active():
        assert _fetch(ydl, f"{first.base}/start", headers=_SECRETS).read() == b"ok"
    _assert_credentials_stripped(first, final)


def test_credentials_are_stripped_on_a_redirect_to_another_host(ydl, servers, guard, monkeypatch):
    _pinned_dns(monkeypatch, "other.invalid")
    server = servers()
    server.routes["/start"] = _redirect(f"http://other.invalid:{server.port}/end")  # same port, other host
    g = guard(lambda ip, port: ip == "127.0.0.1")
    with g.active():
        assert _fetch(ydl, f"{server.base}/start", headers=_SECRETS).read() == b"ok"
    assert server.hits[-1][3] == f"other.invalid:{server.port}"
    _assert_credentials_stripped(server, server)


def test_trailing_dot_host_is_checked_and_pinned(ydl, servers, guard, monkeypatch):
    """libcurl can't resolve pinned.invalid. itself; it only connects through our pin."""
    server = servers({"/x": (200, {}, b"dot")})
    _pinned_dns(monkeypatch, "pinned.invalid.")
    seen: list[str] = []

    def allow(ip, port):
        seen.append(ip)
        return ip == "127.0.0.1" and port == server.port

    g = guard(allow)
    with g.active():
        assert _fetch(ydl, f"http://pinned.invalid.:{server.port}/x").read() == b"dot"
    assert seen == ["127.0.0.1"]


def test_trailing_dot_host_to_disallowed_address_is_refused(ydl, servers, guard, monkeypatch):
    server = servers()
    _pinned_dns(monkeypatch, "pinned.invalid.")
    g = guard(lambda ip, port: False)
    with g.active():
        with pytest.raises(TransportError) as caught:
            _fetch(ydl, f"http://pinned.invalid.:{server.port}/x").read()
        assert g.blocked
    assert isinstance(caught.value.cause, BlockedAddressError)
    assert server.hits == []


def test_ipv4_mapped_ipv6_literal_is_refused(ydl, servers, guard):
    from src.policy.url_policy import is_public_ip

    server = servers()
    g = guard(lambda ip, port: is_public_ip(ip))
    with g.active():
        with pytest.raises(TransportError) as caught:
            _fetch(ydl, f"http://[::ffff:127.0.0.1]:{server.port}/").read()
        assert g.blocked
    assert isinstance(caught.value.cause, BlockedAddressError)
    assert server.hits == []
