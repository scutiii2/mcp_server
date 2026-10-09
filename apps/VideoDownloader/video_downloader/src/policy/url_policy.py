"""Which URLs the service may fetch: public http(s) hosts only.

yt-dlp fetches whatever it is given, and an LLM agent can call the MCP tool,
so private and loopback targets must be refused (SSRF). The host is resolved
here and every resulting address must be public. Redirects and DNS answers
that change later are covered by socket_guard.py.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from src.errors import DownloaderError, ErrorCode

Resolver = Callable[[str], Awaitable[list[str]]]

MAX_URL_LENGTH = 2048
ALLOWED_PORTS = (None, 80, 443)


_NAT64 = ipaddress.IPv6Network("64:ff9b::/96")
_IPV4_COMPATIBLE = ipaddress.IPv6Network("::/96")


def _embedded_ipv4(address: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    """The IPv4 address hidden in an IPv4-mapped, NAT64 or IPv4-compatible IPv6 address."""
    if address.ipv4_mapped is not None:
        return address.ipv4_mapped
    if address in _NAT64 or (address in _IPV4_COMPATIBLE and int(address) > 1):  # not :: or ::1
        return ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
    return None


def is_public_ip(ip: str) -> bool:
    """True only for globally routable unicast addresses.

    IPv4 embedded in IPv6 (mapped ::ffff:0:0/96, NAT64 64:ff9b::/96, compatible ::/96) is unwrapped first.
    """
    try:
        address = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address):
        embedded = _embedded_ipv4(address)
        if embedded is not None:
            address = embedded
    return address.is_global and not address.is_multicast


async def system_resolver(host: str) -> list[str]:
    """Resolve through the event loop's executor, without blocking it."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


class UrlPolicy:
    """Validates a user-supplied URL before any network fetch."""

    def __init__(self, resolver: Resolver | None = None) -> None:
        self._resolver = resolver or system_resolver

    async def check(self, url: str) -> str:
        """Return the trimmed URL, or raise DownloaderError (invalid_url / blocked_host)."""
        url = (url or "").strip()
        if not url or len(url) > MAX_URL_LENGTH:
            raise DownloaderError(ErrorCode.INVALID_URL, "That doesn't look like a valid link.")
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            raise DownloaderError(ErrorCode.INVALID_URL, "That doesn't look like a valid link.") from None
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise DownloaderError(ErrorCode.INVALID_URL, "Paste a full link that starts with http:// or https://.")
        if parts.username or parts.password:
            raise DownloaderError(ErrorCode.INVALID_URL, "Links with a user name or password are not supported.")
        if port not in ALLOWED_PORTS:
            raise DownloaderError(ErrorCode.BLOCKED_HOST, "Only standard web ports (80 and 443) are allowed.")

        host = parts.hostname
        try:
            ipaddress.ip_address(host)
            addresses = [host]
        except ValueError:
            try:
                addresses = await self._resolver(host)
            except OSError:
                raise DownloaderError(ErrorCode.INVALID_URL, "That web address could not be found.") from None
        if not addresses or not all(is_public_ip(a) for a in addresses):
            raise DownloaderError(ErrorCode.BLOCKED_HOST, "That address is not a public website, so it can't be downloaded.")
        return url
