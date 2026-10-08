"""guard.py: which addresses a private extension may reach, and that every
connection and redirect is checked and pinned to the checked address."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from src.private_extensions import guard
from src.private_extensions.guard import BlockedAddress, RedirectRefused

HOSTS = {
    "example.com": ["93.184.216.34"],
    "lan.test": ["192.168.1.9"],
    "mixed.test": ["10.0.0.5", "127.0.0.1"],
    "rebind.test": ["169.254.169.254"],
    "other.test": ["93.184.216.35"],
}


async def resolver(host: str, port: int) -> list[str]:
    return HOSTS[host]


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1", "127.1.2.3", "::1", "0.0.0.0", "::", "0.5.5.5", "169.254.1.1", "169.254.169.254",
        "fe80::1", "fd00:ec2::254", "100.100.100.200", "224.0.0.1", "ff02::1", "240.0.0.1",
        "::ffff:127.0.0.1", "::ffff:169.254.169.254", "64:ff9b::7f00:1", "fe80::1%eth0",
    ],
)
def test_blocked_addresses(address):
    assert guard.is_blocked(address)


@pytest.mark.parametrize(
    "address", ["93.184.216.34", "10.0.0.5", "172.16.3.4", "192.168.1.9", "100.64.0.1", "fc00::1", "2001:db8::1", "::ffff:10.0.0.5"]
)
def test_allowed_addresses(address):
    assert not guard.is_blocked(address)


def test_a_host_with_any_blocked_address_is_blocked():
    with pytest.raises(BlockedAddress):
        run(guard.checked_addresses("mixed.test", 80, resolver))


def test_a_literal_ip_is_checked_without_resolving():
    async def never(host, port):
        raise AssertionError("must not resolve a literal address")

    assert run(guard.checked_addresses("93.184.216.34", 80, never)) == ["93.184.216.34"]
    with pytest.raises(BlockedAddress):
        run(guard.checked_addresses("[::1]", 80, never))


def test_a_name_that_does_not_resolve_is_a_connect_error():
    async def failing(host, port):
        raise OSError("nope")

    with pytest.raises(httpx.ConnectError):
        run(guard.checked_addresses("nowhere.test", 80, failing))


def test_localhost_is_blocked_with_the_real_resolver():
    with pytest.raises(BlockedAddress):
        run(guard.checked_addresses("localhost", 80))


class Recorder:
    def __init__(self):
        self.seen: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        if request.url.path == "/hop":
            return httpx.Response(307, headers={"location": "/mcp/"})
        if request.url.path == "/away":
            return httpx.Response(307, headers={"location": "http://other.test/x"})
        if request.url.path == "/loop":
            return httpx.Response(307, headers={"location": "/loop"})
        return httpx.Response(200, json={"ok": True})


def client(recorder: Recorder, **headers) -> httpx.AsyncClient:
    return guard.guarded_client_factory(resolver, httpx.MockTransport(recorder))(headers or None)


def test_the_request_goes_to_the_checked_address_with_the_host_kept():
    recorder = Recorder()

    async def go():
        async with client(recorder, **{"X-Key": "s3cret"}) as c:
            return await c.post("https://example.com/mcp", json={})

    assert run(go()).status_code == 200
    sent = recorder.seen[-1]
    assert sent.url.host == "93.184.216.34"
    assert sent.headers["host"] == "example.com"
    assert sent.extensions["sni_hostname"] == "example.com"
    assert sent.headers["x-key"] == "s3cret"


def test_plain_http_has_no_sni_and_keeps_the_port_in_the_host_header():
    recorder = Recorder()

    async def go():
        async with client(recorder) as c:
            return await c.post("http://example.com:8080/mcp", json={})

    run(go())
    sent = recorder.seen[-1]
    assert "sni_hostname" not in sent.extensions
    assert sent.headers["host"] == "example.com:8080"
    assert sent.url.port == 8080


def test_lan_addresses_are_allowed():
    recorder = Recorder()

    async def go():
        async with client(recorder) as c:
            return await c.post("http://lan.test/mcp", json={})

    assert run(go()).status_code == 200
    assert recorder.seen[-1].url.host == "192.168.1.9"


def test_a_blocked_host_is_refused_before_anything_is_sent():
    recorder = Recorder()

    async def go():
        async with client(recorder) as c:
            await c.get("http://rebind.test/")

    with pytest.raises(BlockedAddress):
        run(go())
    assert recorder.seen == []


def test_a_same_origin_redirect_is_followed_through_the_guard():
    recorder = Recorder()

    async def go():
        async with client(recorder) as c:
            return await c.post("http://example.com/hop", json={})

    assert run(go()).status_code == 200
    assert [r.url.path for r in recorder.seen] == ["/hop", "/mcp/"]
    assert recorder.seen[-1].headers["host"] == "example.com"


def test_a_redirect_to_another_host_is_refused_so_headers_never_follow():
    recorder = Recorder()

    async def go():
        async with client(recorder, **{"X-Key": "s3cret"}) as c:
            await c.post("http://example.com/away", json={})

    with pytest.raises(RedirectRefused):
        run(go())
    assert [r.url.path for r in recorder.seen] == ["/away"]


def test_a_redirect_loop_stops():
    recorder = Recorder()

    async def go():
        async with client(recorder) as c:
            await c.post("http://example.com/loop", json={})

    with pytest.raises(httpx.TooManyRedirects):
        run(go())
    assert len(recorder.seen) <= guard.MAX_REDIRECTS + 1
