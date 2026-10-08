"""Which addresses a private extension may reach.

The URL is typed by a user and this process connects to it, so every
connection passes through `GuardedTransport`: it resolves the host itself,
refuses the host if ANY resolved address is blocked, and then connects to the
checked IP (the original host stays in the Host header and as the TLS server
name). Because every connection - including every redirect hop - passes
through it, a second DNS answer (rebinding) cannot change where it connects.

A redirect is followed only to the same scheme, host and port, so a header
configured for this server (a token) is never sent anywhere else.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

MAX_REDIRECTS = 3
Resolver = Callable[[str, int], Awaitable[list[str]]]


class BlockedAddress(Exception):
    """The address is not allowed. The message is safe to show the user."""

    def __init__(self, message: str = "That address is not allowed") -> None:
        super().__init__(message)


class RedirectRefused(Exception):
    """The server redirected to another host. The message is safe to show."""

    def __init__(self) -> None:
        super().__init__("That address redirects to another host, which is not followed")


_METADATA = frozenset(ipaddress.ip_address(a) for a in ("169.254.169.254", "fd00:ec2::254", "100.100.100.200"))
_BLOCKED_NETWORKS = tuple(ipaddress.ip_network(n) for n in ("0.0.0.0/8", "64:ff9b::/96"))


def is_blocked(address: str | ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for loopback, link-local, unspecified, multicast, reserved and
    cloud-metadata addresses (also as IPv4-mapped IPv6). Private LAN ranges
    are allowed."""
    ip = ipaddress.ip_address(address.split("%", 1)[0]) if isinstance(address, str) else address
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_unspecified
        or ip.is_multicast
        or ip.is_reserved
        or ip in _METADATA
        or any(ip in network for network in _BLOCKED_NETWORKS)
    )


async def system_resolver(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]).split("%", 1)[0] for info in infos]


async def checked_addresses(host: str, port: int, resolver: Resolver = system_resolver) -> list[str]:
    """The addresses `host` resolves to, if none is blocked; BlockedAddress
    otherwise. A literal IP is checked as it is, without resolving."""
    bare = host.strip("[]")
    try:
        addresses = [str(ipaddress.ip_address(bare))]
    except ValueError:
        try:
            addresses = await resolver(bare, port)
        except OSError as error:
            raise httpx.ConnectError("Couldn't resolve the host") from error
    if not addresses:
        raise httpx.ConnectError("Couldn't resolve the host")
    if any(is_blocked(address) for address in addresses):
        raise BlockedAddress()
    return addresses


class GuardedTransport(httpx.AsyncBaseTransport):
    """Checks the host of every request, then sends it to the checked IP."""

    def __init__(self, resolver: Resolver = system_resolver, inner: httpx.AsyncBaseTransport | None = None) -> None:
        self._resolver = resolver
        self._inner = inner if inner is not None else httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        port = request.url.port or (443 if request.url.scheme == "https" else 80)
        addresses = await checked_addresses(host, port, self._resolver)
        extensions: dict[str, Any] = dict(request.extensions)
        if request.url.scheme == "https":
            # The certificate is checked against the name, not the pinned IP.
            extensions["sni_hostname"] = host
        pinned = httpx.Request(
            request.method,
            request.url.copy_with(host=addresses[0]),
            headers=request.headers,
            stream=request.stream,
            extensions=extensions,
        )
        return await self._inner.handle_async_request(pinned)

    async def aclose(self) -> None:
        await self._inner.aclose()


def _origin(url: httpx.URL) -> tuple[str, str, int]:
    return (url.scheme, url.host, url.port or (443 if url.scheme == "https" else 80))


async def _refuse_foreign_redirect(response: httpx.Response) -> None:
    if not response.is_redirect:
        return
    location = response.headers.get("location")
    if location is None:
        return
    if _origin(response.request.url.join(location)) != _origin(response.request.url):
        raise RedirectRefused()


def guarded_client_factory(
    resolver: Resolver = system_resolver, inner: httpx.AsyncBaseTransport | None = None
) -> Callable[..., httpx.AsyncClient]:
    """A factory with the shape the MCP SDK's `httpx_client_factory` expects."""

    def factory(
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=GuardedTransport(resolver, inner),
            headers=headers,
            timeout=timeout if timeout is not None else httpx.Timeout(30.0),
            auth=auth,
            follow_redirects=True,
            max_redirects=MAX_REDIRECTS,
            event_hooks={"response": [_refuse_foreign_redirect]},
        )

    return factory
