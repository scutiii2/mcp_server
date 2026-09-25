"""Request-level security (port of chat_app/src/services/security/):
client IP resolution, IP allow/deny lists and security headers.

Login rate limiting lives in services/rate_limiter.py, since it needs the
database; everything here is pure and runs before any route.
"""

from __future__ import annotations

import ipaddress
import json
from collections.abc import Iterable

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.config import SecuritySettings

# A JSON API: nothing it returns should ever run script, load resources or
# be framed. (The Vue app itself is served by Vite, which sets its own CSP.)
_API_CSP = "default-src 'none'; frame-ancestors 'none'"


def _networks(entries: Iterable[str]) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Parses CIDRs/addresses; a bad entry is a config error, not silently skipped."""
    networks = []
    for entry in entries:
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError as error:
            raise ValueError(f"security: invalid IP or network {entry!r}") from error
    return networks


def _in(address: str, networks: list) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in network for network in networks)


class ClientIpResolver:
    """The real client address. X-Forwarded-For is honoured only when the
    socket peer is a trusted proxy, and then only its last hop (the one that
    proxy appended) - earlier entries are client-controlled."""

    def __init__(self, trusted_proxies: Iterable[str]) -> None:
        self._trusted = _networks(trusted_proxies)

    def resolve(self, scope: Scope) -> str:
        client = scope.get("client")
        peer = client[0] if client else "unknown"
        if not _in(peer, self._trusted):
            return peer
        forwarded = dict(scope.get("headers", [])).get(b"x-forwarded-for", b"").decode("latin-1")
        last_hop = forwarded.split(",")[-1].strip()
        return last_hop if last_hop and _is_ip(last_hop) else peer


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


class IpFilter:
    def __init__(self, allow: Iterable[str], deny: Iterable[str]) -> None:
        self._allow = _networks(allow)
        self._deny = _networks(deny)

    @property
    def active(self) -> bool:
        return bool(self._allow or self._deny)

    def allows(self, address: str) -> bool:
        if _in(address, self._deny):
            return False
        return not self._allow or _in(address, self._allow)


def security_headers(settings: SecuritySettings) -> list[tuple[bytes, bytes]]:
    if not settings.security_headers:
        return []
    headers = [
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"no-referrer"),
        (b"content-security-policy", _API_CSP.encode()),
    ]
    if settings.hsts_max_age > 0:
        headers.append((b"strict-transport-security", f"max-age={settings.hsts_max_age}; includeSubDomains".encode()))
    return headers


class SecurityMiddleware:
    """Stores the resolved client IP in scope["state"]["client_ip"], refuses
    filtered IPs with 403, and adds the security headers to every response.
    Pure ASGI (not BaseHTTPMiddleware), so the MCP proxy's streams pass
    through unbuffered."""

    def __init__(self, app: ASGIApp, settings: SecuritySettings) -> None:
        self.app = app
        self._resolver = ClientIpResolver(settings.trusted_proxies)
        self._filter = IpFilter(settings.ip_allow_list, settings.ip_deny_list)
        self._headers = security_headers(settings)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        client_ip = self._resolver.resolve(scope)
        scope.setdefault("state", {})["client_ip"] = client_ip

        if self._filter.active and not self._filter.allows(client_ip):
            await self._send_json(send, 403, {"detail": "Access from this address is not allowed"})
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start" and self._headers:
                names = {name.lower() for name, _ in message.get("headers", [])}
                extra = [(n, v) for n, v in self._headers if n not in names]
                message = {**message, "headers": [*message.get("headers", []), *extra]}
            await send(message)

        await self.app(scope, receive, send_with_headers)

    async def _send_json(self, send: Send, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    *self._headers,
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def client_ip(request) -> str:
    """The address SecurityMiddleware resolved for this request."""
    return getattr(request.state, "client_ip", None) or (request.client.host if request.client else "unknown")
