"""Address checks for yt-dlp's curl_cffi (browser impersonation) handler.

Some sites (TikTok) only answer a request that looks like a real browser, which
yt-dlp does through curl_cffi. libcurl resolves names and follows redirects in
C, so the getaddrinfo wrapper in socket_guard.py never sees those connections.

``install()`` makes yt-dlp's ``CurlCFFIRH`` use ``GuardedSession``. While the
calling thread is inside a SocketGuard's ``active()`` block, each request:

* is rebuilt from its parsed parts (scheme, host, port, path, query), so libcurl
  connects to the same host we checked; odd hosts are refused;
* resolves its host with ``SocketGuard.check_host`` (same allow rule, sets
  ``guard.blocked``) before anything is sent;
* pins libcurl to the checked IPs with ``CURLOPT_RESOLVE``, so a second DNS
  answer (rebinding) can't change the target;
* never uses a proxy (CURLOPT_PROXY "" and CURLOPT_NOPROXY "*", so *_proxy env vars
  are ignored too); a proxy configured by yt-dlp is refused, since a proxy resolves
  names itself;
* never lets libcurl follow redirects: we follow ``Location`` ourselves, up to 5
  hops, checking and pinning every hop (303, and 301/302 after POST, become GET;
  307/308 keep method and body; only http and https).

Refusals raise ``BlockedCurlRequest``: a BlockedAddressError that is also a
curl_cffi RequestsError, so yt-dlp reports it as a TransportError (and does not
retry the request on another handler). Outside ``active()`` sessions behave
exactly like curl_cffi's own.

The guard leans on yt-dlp/curl_cffi internals. ``install()`` re-checks them every
time; if one is gone after an upgrade it fails closed: the CurlCFFI handler is taken
out of yt-dlp's registry (no impersonation) and an error is logged. ``update.bat``
runs tests/test_curl_guard.py after upgrading yt-dlp.
"""

from __future__ import annotations

import importlib
import inspect
import ipaddress
import logging
import re
import threading
import urllib.parse
from dataclasses import dataclass
from typing import Any

from src.policy.socket_guard import BlockedAddressError, SocketGuard, active_guard

logger = logging.getLogger(__name__)

MAX_REDIRECTS = 5
_REDIRECT_STATUSES = (301, 302, 303, 307, 308)
_SCHEMES = {"http": 80, "https": 443}
_HOSTNAME = re.compile(r"[a-z0-9_.-]+")
_BODY_HEADERS = {"content-type", "content-length", "content-encoding", "transfer-encoding"}
_CREDENTIAL_HEADERS = {"authorization", "proxy-authorization", "cookie"}

try:
    from yt_dlp.networking import _curlcffi
except ImportError:  # curl_cffi missing or unsupported: yt-dlp has no curl handler, nothing to guard
    _curlcffi = None

# yt-dlp has a curl handler but something the guard needs is gone (API drift): install() fails closed.
_import_error: Exception | None = None
if _curlcffi is not None:
    try:
        import curl_cffi.requests as _cffi_requests
        from curl_cffi import Curl as _Curl
        from curl_cffi.const import CurlECode, CurlOpt
        from curl_cffi.requests.exceptions import DNSError, RequestException, TooManyRedirects
        from yt_dlp.networking._helper import get_redirect_method

        _PROXY_OPTIONS = (CurlOpt.PROXY, CurlOpt.PRE_PROXY)
    except (ImportError, AttributeError) as exc:
        _import_error = exc


if _curlcffi is not None and _import_error is None:

    class BlockedCurlRequest(RequestException, BlockedAddressError):
        """A curl_cffi request the guard refused."""

    @dataclass(frozen=True)
    class _Target:
        url: str  # rebuilt URL handed to libcurl
        host: str  # ASCII, lowercase, no brackets
        port: int
        is_ip: bool

        @property
        def origin(self) -> tuple[str, str, int]:
            return (urllib.parse.urlsplit(self.url).scheme, self.host, self.port)

    def _target(url: str) -> _Target:
        """Parse and rebuild ``url`` so libcurl and we agree on the host. Refuses anything unusual."""
        try:
            parts = urllib.parse.urlsplit(url)
            scheme = parts.scheme.lower()
            explicit_port = parts.port
            host = parts.hostname or ""
        except ValueError as exc:
            raise RequestException(f"Invalid URL: {exc}") from exc
        if scheme not in _SCHEMES:
            raise RequestException(f"Unsupported URL scheme: {scheme or 'none'}")
        if not host.isascii():
            try:
                host = host.encode("idna").decode("ascii")
            except UnicodeError as exc:
                raise RequestException("Invalid host name") from exc
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            ip = None
            if not _HOSTNAME.fullmatch(host):
                raise RequestException("Invalid host name")
        netloc = f"[{host}]" if ip is not None and ip.version == 6 else host
        if explicit_port is not None:
            netloc = f"{netloc}:{explicit_port}"
        if parts.username is not None:
            userinfo = urllib.parse.quote(urllib.parse.unquote(parts.username), safe="")
            if parts.password is not None:
                userinfo += ":" + urllib.parse.quote(urllib.parse.unquote(parts.password), safe="")
            netloc = f"{userinfo}@{netloc}"
        rebuilt = urllib.parse.urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))
        return _Target(rebuilt, host, explicit_port or _SCHEMES[scheme], ip is not None)

    def _resolve_entry(target: _Target, ips: list[str]) -> str:
        addresses = ",".join(f"[{ip}]" if ":" in ip else ip for ip in ips)
        return f"{target.host}:{target.port}:{addresses}"

    def _check(guard: SocketGuard, host: str, port: int) -> list[str]:
        try:
            ips = guard.check_host(host, port)
        except BlockedAddressError as exc:
            raise BlockedCurlRequest(str(exc)) from exc
        except OSError as exc:
            raise DNSError(f"Could not resolve host: {host}", CurlECode.COULDNT_RESOLVE_HOST) from exc
        if not ips:
            raise DNSError(f"Could not resolve host: {host}", CurlECode.COULDNT_RESOLVE_HOST)
        return ips

    def _same_ip(a: str, b: str) -> bool:
        try:
            return ipaddress.ip_address(a) == ipaddress.ip_address(b)
        except ValueError:
            return False

    def _without(headers: Any, names: set[str]) -> dict:
        return {k: v for k, v in (headers or {}).items() if str(k).lower() not in names}

    class _ProxyAwareCurl(_Curl):
        """Curl handle that remembers whether a proxy was set on it (libcurl can't be asked)."""

        _vd_proxy: Any = ""

        def setopt(self, option, value):  # type: ignore[override]
            if option in _PROXY_OPTIONS:
                self._vd_proxy = value
            return super().setopt(option, value)

        def reset(self) -> None:
            self._vd_proxy = ""
            super().reset()

    class GuardedSession(_cffi_requests.Session):
        """curl_cffi Session whose requests are address-checked, IP-pinned and redirect-checked while a guard is active."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._hop = threading.local()  # per-hop curl handle that carries the RESOLVE pin
            super().__init__(*args, **kwargs)

        @property
        def curl(self):  # type: ignore[override]
            hop = getattr(self._hop, "curl", None)
            if hop is not None:
                return hop
            base = super().curl
            if type(base) is _Curl:
                base.__class__ = _ProxyAwareCurl  # so a proxy set by the caller (yt-dlp) is seen
            return base

        def request(self, method, url, *args, **kwargs):  # type: ignore[override]
            guard = active_guard()
            if guard is None:
                return super().request(method, url, *args, **kwargs)
            if args:
                raise TypeError("GuardedSession.request takes keyword arguments only while guarded")
            return self._guarded_request(guard, method, url, **kwargs)

        def _guarded_request(self, guard: SocketGuard, method: str, url: str, **kwargs: Any):
            follow = kwargs.pop("allow_redirects", None) is not False
            wanted = kwargs.pop("max_redirects", None)
            limit = MAX_REDIRECTS if wanted is None or wanted < 0 else min(wanted, MAX_REDIRECTS)
            data = kwargs.pop("data", None)
            headers = kwargs.pop("headers", None)
            stream = bool(kwargs.get("stream"))
            kwargs["allow_redirects"] = False  # libcurl must never follow a Location on its own
            kwargs["max_redirects"] = 0

            # Options the caller set on session.curl (yt-dlp: timeouts, verbose, client cert) are kept
            # in a template; every hop gets a fresh copy of it plus its own RESOLVE pin.
            base = self.curl
            # A proxy resolves names itself, so the RESOLVE pin and the address check would not apply.
            proxied = not isinstance(base, _ProxyAwareCurl) or bool(base._vd_proxy)
            if proxied or self.proxies or kwargs.get("proxy") or kwargs.get("proxies"):
                base.reset()
                raise BlockedCurlRequest("A proxy is not allowed while URL policy checks are active")
            template = base.duphandle()
            base.reset()
            try:
                hop_number = 0
                while True:
                    target = _target(url)
                    ips = _check(guard, target.host, target.port)
                    handle = template.duphandle()
                    # Never a proxy, not even one from http_proxy/https_proxy/all_proxy in the environment.
                    handle.setopt(CurlOpt.PROXY, "")
                    handle.setopt(CurlOpt.NOPROXY, "*")
                    if not target.is_ip:
                        handle.setopt(CurlOpt.RESOLVE, [_resolve_entry(target, ips)])
                    self._hop.curl = handle
                    try:
                        response = super().request(method=method, url=target.url, data=data, headers=headers, **kwargs)
                    finally:
                        self._hop.curl = None
                        # A stream runs on a duplicate of it; a plain response is fully parsed by now.
                        handle.close()
                    self._check_peer(guard, response, ips, target, stream)

                    location = response.headers.get("location") if response.status_code in _REDIRECT_STATUSES else None
                    if not follow or not location:
                        return response
                    if hop_number >= limit:
                        raise TooManyRedirects(
                            f"Maximum ({limit}) redirects followed", CurlECode.TOO_MANY_REDIRECTS, response
                        )
                    next_url = urllib.parse.urljoin(target.url, location)
                    if urllib.parse.urlsplit(next_url).scheme.lower() not in _SCHEMES:
                        self._close(response, stream)
                        raise RequestException("Redirect to an unsupported URL scheme was refused")
                    next_method = get_redirect_method(method, response.status_code)
                    if next_method != method:
                        data = None
                        headers = _without(headers, _BODY_HEADERS)
                    next_target = _target(next_url)
                    if next_target.origin != target.origin:
                        headers = _without(headers, _CREDENTIAL_HEADERS)
                    self._close(response, stream)
                    url, method = next_url, next_method
                    hop_number += 1
            finally:
                template.close()

        @staticmethod
        def _close(response, stream: bool) -> None:
            if stream:
                response.close()

        def _check_peer(self, guard: SocketGuard, response, ips: list[str], target: _Target, stream: bool) -> None:
            """Defence in depth: the address libcurl actually used must be one we checked (or pass the rule itself)."""
            peer = getattr(response, "primary_ip", "") or ""
            if not peer or any(_same_ip(peer, ip) for ip in ips):
                return
            logger.warning("curl_cffi connected to an unchecked address for %s", target.host)
            try:
                _check(guard, peer, target.port)
            except RequestException:
                self._close(response, stream)
                raise


_original_create_instance: Any = None  # CurlCFFIRH._create_instance before install()
_unregistered: dict[str, Any] = {}  # handlers install() took out of yt-dlp's registry (fail closed)

# What GuardedSession relies on, checked again at every install() so a yt-dlp/curl_cffi upgrade that
# renames or drops any of it disables impersonation instead of silently skipping the guard.
_REQUIRED = (
    ("curl_cffi", "Curl"),
    ("curl_cffi.requests", "Session"),
    ("curl_cffi.requests.exceptions", "DNSError"),
    ("curl_cffi.requests.exceptions", "RequestException"),
    ("curl_cffi.requests.exceptions", "TooManyRedirects"),
    ("yt_dlp.networking._helper", "get_redirect_method"),
    ("yt_dlp.networking._helper", "InstanceStoreMixin"),
)
_CURL_OPTIONS = ("RESOLVE", "PROXY", "PRE_PROXY", "NOPROXY")
_CURL_CODES = ("TOO_MANY_REDIRECTS", "COULDNT_RESOLVE_HOST")
_CURL_METHODS = ("setopt", "duphandle", "reset", "close")
_REQUEST_ARGS = ("method", "url", "data", "headers", "allow_redirects", "max_redirects", "stream", "proxy", "proxies")


def _calls(func: Any, needle: str) -> bool:
    try:
        return needle in inspect.getsource(func)
    except (OSError, TypeError):
        return False


def _accepts(func: Any, names: tuple[str, ...]) -> bool:
    try:
        params = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return False
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return True
    return all(name in params for name in names)


def _problems() -> list[str]:
    """Why the guard can't be trusted with this yt-dlp / curl_cffi pair (empty when it can)."""
    if _import_error is not None:
        return [f"import failed: {_import_error!r}"]
    problems = []
    for module_name, attr in _REQUIRED:
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            module = None
        if not hasattr(module, attr):
            problems.append(f"{module_name}.{attr} is missing")
    from curl_cffi import const

    problems += [f"CurlOpt.{n} is missing" for n in _CURL_OPTIONS if not hasattr(getattr(const, "CurlOpt", None), n)]
    problems += [f"CurlECode.{n} is missing" for n in _CURL_CODES if not hasattr(getattr(const, "CurlECode", None), n)]
    curl_class = getattr(importlib.import_module("curl_cffi"), "Curl", None)
    problems += [f"Curl.{n} is missing" for n in _CURL_METHODS if not callable(getattr(curl_class, n, None))]
    session = getattr(importlib.import_module("curl_cffi.requests"), "Session", None)
    if not isinstance(inspect.getattr_static(session, "curl", None), property):
        problems.append("Session.curl is no longer a property")
    if not _accepts(getattr(session, "__init__", None), ("cookies",)):
        problems.append("Session() no longer takes cookies=")
    if not _accepts(getattr(session, "request", None), _REQUEST_ARGS):
        problems.append("Session.request() signature changed")
    handler = _curlcffi.CurlCFFIRH
    if "_create_instance" not in vars(handler) and _original_create_instance is None:
        problems.append("CurlCFFIRH._create_instance is missing")
    if not _calls(getattr(handler, "_send", None), "self._get_instance("):
        problems.append("CurlCFFIRH._send no longer gets its session from self._get_instance")
    if not _calls(getattr(handler, "_get_instance", None), "self._create_instance("):
        problems.append("CurlCFFIRH._get_instance no longer builds sessions with self._create_instance")
    return problems


def _disable_curl_handler(problems: list[str]) -> None:
    """Fail closed: take CurlCFFI out of yt-dlp's handler registry, or stop startup if that's impossible."""
    handler = _curlcffi.CurlCFFIRH
    registry = getattr(importlib.import_module("yt_dlp.networking.common"), "_REQUEST_HANDLERS", None)
    if not isinstance(registry, dict):
        raise RuntimeError(f"curl_cffi requests can't be guarded and yt-dlp's handler can't be disabled: {problems}")
    for key in [key for key, value in registry.items() if value is handler or key == "CurlCFFI"]:
        _unregistered[key] = registry.pop(key)
    logger.error(
        "curl_cffi requests can't be address-checked with this yt-dlp/curl_cffi version, so browser "
        "impersonation is disabled: %s",
        "; ".join(problems),
    )


def install() -> None:
    """Make yt-dlp's curl_cffi handler create GuardedSession instances (idempotent).

    Called by SocketGuard.install(), so any process that guards sockets also guards libcurl. Must run
    before a YoutubeDL is created. If the guard's assumptions about yt-dlp/curl_cffi no longer hold,
    the curl handler is unregistered instead (no impersonation, but no unguarded requests either).
    """
    if _curlcffi is None:
        return
    global _original_create_instance
    problems = _problems()
    if not problems:
        handler = _curlcffi.CurlCFFIRH
        if not getattr(handler._create_instance, "_vd_guarded", False):

            def _create_instance(self, cookiejar=None):
                return GuardedSession(cookies=cookiejar)

            _create_instance._vd_guarded = True  # type: ignore[attr-defined]
            _original_create_instance = handler.__dict__["_create_instance"]
            handler._create_instance = _create_instance
        if not getattr(handler._create_instance, "_vd_guarded", False):  # post-install self-check
            problems.append("CurlCFFIRH._create_instance could not be replaced")
    if problems:
        _disable_curl_handler(problems)


def uninstall() -> None:
    """Undo ``install()``: plain sessions again, and an unregistered curl handler is registered again (idempotent)."""
    global _original_create_instance
    if _original_create_instance is not None:
        _curlcffi.CurlCFFIRH._create_instance = _original_create_instance
        _original_create_instance = None
    if _unregistered:
        registry = importlib.import_module("yt_dlp.networking.common")._REQUEST_HANDLERS
        registry.update(_unregistered)
        _unregistered.clear()
