# Private Extensions, Part 1: ai_agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `ai_agent` can connect, for one turn and one account, to MCP servers whose URL and headers `ember_api` hands it; offer their tools to the model, run them (always after the user approves), and probe a URL for the add-extension flow. Nothing else changes for existing turns.

**Architecture:** A new package `src/private_extensions/` holds an address guard (a custom `httpx` transport that checks and pins every connection), a validated `PrivateSpec`, a session pool, and a per-turn `PrivateTurn` bound in a `ContextVar` (like `tool_filter` and `approvals`). `ask()` gets one optional argument, `private_extensions`. Tools are fetched asynchronously before the provider runs, so the providers' blocking `list_tools()` only reads a cache; calls are routed by `mcp_upstream.call_tool`. Approval uses a new `ask_prefixes` field on `ApprovalPolicy`.

**Tech Stack:** Python 3.14, `mcp` SDK (`streamablehttp_client(httpx_client_factory=...)`), `httpx`, FastMCP, pytest (plain `asyncio.run` tests, as in the existing suite).

**Spec:** `docs/superpowers/specs/2026-10-08-private-extensions-design.md` (part 1 = its `ai_agent` section). Parts 2 (`ember_api`) and 3 (`ember_web`) get their own plans afterwards; part 1 must be merged first because `ember_api` checks the `private_extensions` flag in `status()`.

## Global Constraints

- All work is in `apps/ai_agent`. Run tests from there: `python -m pytest <path> -q`.
- Private tool names are `u_<slug>__<tool>`: at most 64 characters, matching `^[A-Za-z0-9_-]+$`. A slug matches `^[a-z0-9]+(_[a-z0-9]+)*$` (so it never contains `__`), at most 40 characters. At most 100 tools per extension.
- Allowed addresses: `http` and `https` only. Always blocked: loopback, link-local, unspecified, multicast, reserved, `0.0.0.0/8`, `64:ff9b::/96`, the metadata addresses `169.254.169.254`, `fd00:ec2::254`, `100.100.100.200`, and IPv4-mapped IPv6 forms. Private LAN ranges (`10/8`, `172.16/12`, `192.168/16`, `fc00::/7`) are allowed. If any address a host resolves to is blocked, the host is blocked.
- Header limits: at most 20 headers, name `^[A-Za-z0-9-]{1,64}$`, value 1 to 2000 characters with no control characters. Refused names: `host`, `content-length`, `transfer-encoding`, `connection`, `upgrade`, `te`, `trailer`, `proxy-authorization`, `cookie`. URL: at most 1000 characters, a host, no username or password.
- Timeouts: connect 10 s, call 120 s. Pool: at most 5 sessions per account, 50 in total, idle for 300 s means closed on the next use.
- A header value never appears in a log, an exception message, an event or a reply. A URL's query string is never logged.
- Private extensions are never forwarded to a delegated agent.
- `ask()` passes `private_extensions` on to `run_chat` only when it is non-empty (existing tests replace `run_chat` with fakes that do not accept it).
- Before adding a reusable helper, follow the `checking-the-catalog` skill (look for an existing `@catalog` block). Commit style: `feat(ai_agent): ...`. Do not add Co-Authored-By lines when ChatGPT executes this plan; Claude adds `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## File Structure

Create:
- `src/private_extensions/__init__.py`: package docstring only.
- `src/private_extensions/guard.py`: `BlockedAddress`, `RedirectRefused`, `is_blocked`, `checked_addresses`, `GuardedTransport`, `guarded_client_factory`.
- `src/private_extensions/spec.py`: `PrivateSpec`, `InvalidSpec`, `describe_error`.
- `src/private_extensions/pool.py`: `open_private_session`, `PrivateSessionPool`.
- `src/private_extensions/turn.py`: `PrivateTurn`, `TOOL_PREFIX`, `bind`, `reset`, `current`.
- `tests/test_private_guard.py`, `tests/test_private_spec.py`, `tests/test_private_pool.py`, `tests/test_private_turn.py`, `tests/test_private_upstream.py`, `tests/test_private_approvals.py`, `tests/test_private_server.py`.

Modify: `src/mcp_client/sync_wrapper.py`, `src/mcp_client/mcp_upstream.py`, `src/core/approvals.py`, `src/llm/base_provider.py` (`ChatResult`), `src/agents/agent_config.py`, `src/server.py`, `tests/test_server.py` (status test), `README.md` of `apps/ai_agent`, and the spec.

---

### Task 0: Fold what the investigation found back into the spec

**Files:**
- Modify: `docs/superpowers/specs/2026-10-08-private-extensions-design.md`

- [ ] **Step 1: Edit the spec**

Make these replacements (find the quoted old text, replace with the new):

1. Approval, three bullets starting "`ApprovalPolicy` gets `ask_tools`...", "`needs_approval(tool)` becomes...", "In `review()`, a tool in `ask_tools`...": replace all three with:
   - "`ApprovalPolicy` gets `ask_prefixes: tuple[str, ...]`, set to `("u_",)` for a turn that has private extensions. Every private tool name starts with `u_`; no built-in or server-listed name does (those start with `main__`)."
   - "`needs_approval(tool)` becomes: `tool not in allowed_tools` and (`mode != "off"` or the name starts with one of `ask_prefixes`)."
   - "In `review()`, such a tool under mode `off` is handled as `ask`; under mode `deny` it is refused as today."
2. In "Wiring", the sentence "The system prompt for that turn gets one line naming the unavailable extension, so the model can tell the user." is removed. (The notice reaches the user through `private_extension_errors`; the model simply does not see the missing tools.)
3. In "Wiring", "`status()` adds `private_extensions: True`." becomes "`status()` adds `private_extensions`: true, except when the agent's provider is `laya` (it has its own tool shortlist and does not list tools through `mcp_upstream`)."
4. In "Wiring", after the bullet about `mcp_upstream.list_tools`, add: "The tools are fetched before the provider starts, by an async `prefetch` run from `agent_config.run_chat` that connects to every extension concurrently on the connection loop. The providers' blocking `list_tools()` then only reads that cache, so it never waits on a network connection."
5. In "Connector and guard", replace "Redirects are followed at most 3 hops, each through the guard." with: "A redirect is followed only to the same scheme, host and port, at most 3 hops; any other target raises `RedirectRefused`, so a configured header (a token) is never sent to another host. Each hop also passes the guard. A connection is made to the checked IP address, with the original host kept in the `Host` header and as the TLS server name, so a second DNS answer cannot change where it connects."
6. In "Connector and guard", add a bullet: "Before `streamablehttp_client` is used, `open_private_session` makes one plain `initialize` POST through the same guarded client and raises on an HTTP error status (a wrong token is a 401). `mcp_server`'s `extensions.py` documents why: such a failure inside the SDK's own task group corrupts the event loop's cancel scopes."
7. In "Connector and guard", replace "Idle expiry 300 seconds" with "A session idle for more than 300 seconds is closed the next time the pool is used (and all are closed at shutdown)".
8. Under "Risks to check early", replace the first bullet with: "Settled: `streamablehttp_client` accepts `httpx_client_factory` (mcp SDK in use). A factory returns an `httpx.AsyncClient`; the guard is installed as its `transport`."

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-10-08-private-extensions-design.md docs/superpowers/plans/2026-10-08-private-extensions-part1-ai-agent.md
git commit -m "docs: private extensions spec refinements; part 1 plan"
```

---

### Task 1: The address guard

**Files:**
- Create: `apps/ai_agent/src/private_extensions/__init__.py`
- Create: `apps/ai_agent/src/private_extensions/guard.py`
- Test: `apps/ai_agent/tests/test_private_guard.py`

**Interfaces:**
- Produces: `BlockedAddress(Exception)` (message `"That address is not allowed"`), `RedirectRefused(Exception)`, `is_blocked(address) -> bool`, `async checked_addresses(host, port, resolver=system_resolver) -> list[str]`, `GuardedTransport(resolver=system_resolver, inner=None)`, `guarded_client_factory(resolver=system_resolver, inner=None)` returning a callable `(headers=None, timeout=None, auth=None) -> httpx.AsyncClient`, `MAX_REDIRECTS = 3`.

- [ ] **Step 1: Write the failing tests**

Create `apps/ai_agent/src/private_extensions/__init__.py` containing only:

```python
"""Per-account MCP servers ("private extensions") that ember_api hands to a turn."""
```

Create `apps/ai_agent/tests/test_private_guard.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_private_guard.py -q`
Expected: FAIL (module `src.private_extensions.guard` not found).

- [ ] **Step 3: Write `guard.py`**

Create `apps/ai_agent/src/private_extensions/guard.py` (this exact code was run against the installed `httpx`):

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_private_guard.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/ai_agent/src/private_extensions apps/ai_agent/tests/test_private_guard.py
git commit -m "feat(ai_agent): address guard for private extensions"
```

---

### Task 2: The validated spec and safe error text

**Files:**
- Create: `apps/ai_agent/src/private_extensions/spec.py`
- Test: `apps/ai_agent/tests/test_private_spec.py`

**Interfaces:**
- Consumes: `BlockedAddress`, `RedirectRefused` from Task 1.
- Produces: `InvalidSpec(ValueError)`; `PrivateSpec(slug: str, label: str, url: str, headers: tuple[tuple[str, str], ...])` frozen dataclass with `PrivateSpec.parse(raw: Any) -> PrivateSpec`, `PrivateSpec.from_probe(url: str, headers: Mapping[str, str] | None) -> PrivateSpec`, `.header_map -> dict[str, str]`, `.host -> str`, `.secrets -> tuple[str, ...]`, `.key() -> str`; `describe_error(error: BaseException, secrets: Iterable[str] = ()) -> str`.

- [ ] **Step 1: Write the failing tests**

Create `apps/ai_agent/tests/test_private_spec.py`:

```python
"""spec.py: what ember_api may send for one private extension, and error text that never leaks a secret."""

from __future__ import annotations

import httpx
import pytest

from src.private_extensions.guard import BlockedAddress, RedirectRefused
from src.private_extensions.spec import InvalidSpec, PrivateSpec, describe_error

GOOD = {"id": "notes", "label": "My notes", "url": "https://notes.example.com/mcp", "headers": {"X-Api-Key": "abc123"}}


def test_a_good_spec_parses():
    spec = PrivateSpec.parse(GOOD)

    assert (spec.slug, spec.label, spec.url) == ("notes", "My notes", "https://notes.example.com/mcp")
    assert spec.header_map == {"X-Api-Key": "abc123"}
    assert spec.host == "notes.example.com"
    assert spec.secrets == ("abc123",)


def test_headers_are_optional_and_the_label_defaults_to_the_slug():
    spec = PrivateSpec.parse({"id": "a1", "url": "http://10.0.0.5:8000/mcp"})

    assert spec.header_map == {}
    assert spec.label == "a1"


@pytest.mark.parametrize("bad", ["", "Notes", "a__b", "_a", "a_", "a b", "x" * 41, 5, None])
def test_bad_slugs_are_refused(bad):
    with pytest.raises(InvalidSpec):
        PrivateSpec.parse({**GOOD, "id": bad})


@pytest.mark.parametrize(
    "url",
    ["", "ftp://x.com/mcp", "notes.example.com", "https:///mcp", "https://user:pw@x.com/mcp", "https://x.com/" + "a" * 1000, 5, None],
)
def test_bad_urls_are_refused(url):
    with pytest.raises(InvalidSpec):
        PrivateSpec.parse({**GOOD, "url": url})


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "evil"}, {"cookie": "a=b"}, {"Content-Length": "5"}, {"bad name": "v"}, {"X": ""}, {"X": "a\nb"},
        {"X": "a" * 2001}, {f"H{i}": "v" for i in range(21)}, {"X": 5}, ["X", "v"],
    ],
)
def test_bad_headers_are_refused(headers):
    with pytest.raises(InvalidSpec):
        PrivateSpec.parse({**GOOD, "headers": headers})


def test_a_non_object_is_refused():
    with pytest.raises(InvalidSpec):
        PrivateSpec.parse("https://x.com")


def test_the_key_changes_with_the_url_or_headers_and_not_with_header_order():
    a = PrivateSpec.parse({**GOOD, "headers": {"A": "1", "B": "2"}})
    b = PrivateSpec.parse({**GOOD, "headers": {"B": "2", "A": "1"}})
    c = PrivateSpec.parse({**GOOD, "headers": {"A": "1", "B": "3"}})
    d = PrivateSpec.parse({**GOOD, "headers": {"A": "1", "B": "2"}, "url": "https://other.example.com/mcp"})

    assert a.key() == b.key()
    assert len({a.key(), c.key(), d.key()}) == 3


def test_a_probe_spec_is_validated_the_same_way():
    spec = PrivateSpec.from_probe("https://x.example.com/mcp", {"Authorization": "Bearer t0ken"})

    assert spec.secrets == ("Bearer t0ken",)
    with pytest.raises(InvalidSpec):
        PrivateSpec.from_probe("file:///etc/passwd", None)


def test_describe_error_uses_the_safe_messages_as_they_are():
    assert describe_error(BlockedAddress()) == "That address is not allowed"
    assert "redirects to another host" in describe_error(RedirectRefused())


def test_describe_error_hides_secrets_and_keeps_one_short_line():
    error = RuntimeError("401 for header Bearer t0ken at host\nsecond line with t0ken")

    text = describe_error(error, ["Bearer t0ken", "t0ken"])

    assert "t0ken" not in text
    assert "\n" not in text
    assert "***" in text
    assert len(describe_error(RuntimeError("x" * 500))) <= 200


def test_describe_error_unwraps_exception_groups_and_names_timeouts():
    assert describe_error(BaseExceptionGroup("g", [BlockedAddress()])) == "That address is not allowed"
    assert describe_error(httpx.ReadTimeout("slow")) == "Timed out"
    assert describe_error(TimeoutError()) == "Timed out"
    assert describe_error(RuntimeError()) == "RuntimeError"
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_private_spec.py -q`
Expected: FAIL (module not found).

- [ ] **Step 3: Write `spec.py`**

Create `apps/ai_agent/src/private_extensions/spec.py`:

```python
"""One private extension as ember_api sends it with a turn, validated.

ember_api validates too; this is the last check before the process connects
somewhere, so it does not trust the sender. Header values are secrets:
`describe_error` is the only way an error leaves this package, and it hides
them.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from src.private_extensions.guard import BlockedAddress, RedirectRefused

SLUG = re.compile(r"[a-z0-9]+(?:_[a-z0-9]+)*")
MAX_SLUG = 40
MAX_LABEL = 60
MAX_URL = 1000
MAX_HEADERS = 20
MAX_VALUE = 2000
MAX_ERROR = 200
_HEADER_NAME = re.compile(r"[A-Za-z0-9-]{1,64}")
_FORBIDDEN_HEADERS = frozenset(
    {"host", "content-length", "transfer-encoding", "connection", "upgrade", "te", "trailer", "proxy-authorization", "cookie"}
)


class InvalidSpec(ValueError):
    """A private extension that cannot be used. The message is safe to show."""


def _headers(raw: Any) -> tuple[tuple[str, str], ...]:
    if raw is None:
        return ()
    if not isinstance(raw, Mapping):
        raise InvalidSpec("Headers must be a set of names and values")
    if len(raw) > MAX_HEADERS:
        raise InvalidSpec(f"At most {MAX_HEADERS} headers are allowed")
    pairs: list[tuple[str, str]] = []
    for name, value in raw.items():
        if not isinstance(name, str) or not _HEADER_NAME.fullmatch(name):
            raise InvalidSpec("A header name may only use letters, digits and hyphens (64 at most)")
        if name.lower() in _FORBIDDEN_HEADERS:
            raise InvalidSpec(f"The header {name} can't be set")
        if not isinstance(value, str) or not 1 <= len(value) <= MAX_VALUE:
            raise InvalidSpec(f"The value of {name} must be 1 to {MAX_VALUE} characters")
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
            raise InvalidSpec(f"The value of {name} has a control character")
        pairs.append((name, value))
    return tuple(sorted(pairs))


def _url(raw: Any) -> str:
    if not isinstance(raw, str) or not raw or len(raw) > MAX_URL:
        raise InvalidSpec("Enter an http or https address")
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise InvalidSpec("Enter an http or https address")
    if parts.username is not None or parts.password is not None:
        raise InvalidSpec("Put credentials in a header, not in the address")
    return raw


@dataclass(frozen=True)
class PrivateSpec:
    slug: str
    label: str
    url: str
    headers: tuple[tuple[str, str], ...] = ()

    @property
    def header_map(self) -> dict[str, str]:
        return dict(self.headers)

    @property
    def host(self) -> str:
        return urlsplit(self.url).hostname or ""

    @property
    def secrets(self) -> tuple[str, ...]:
        return tuple(value for _name, value in self.headers)

    def key(self) -> str:
        """Same url and headers, same key (header order does not matter)."""
        return hashlib.sha256(json.dumps([self.url, list(self.headers)]).encode("utf-8")).hexdigest()

    @classmethod
    def parse(cls, raw: Any) -> PrivateSpec:
        if not isinstance(raw, Mapping):
            raise InvalidSpec("A private extension must be an object")
        slug = raw.get("id")
        if not isinstance(slug, str) or len(slug) > MAX_SLUG or not SLUG.fullmatch(slug):
            raise InvalidSpec("The extension id is not valid")
        label = raw.get("label")
        label = label.strip()[:MAX_LABEL] if isinstance(label, str) and label.strip() else slug
        return cls(slug=slug, label=label, url=_url(raw.get("url")), headers=_headers(raw.get("headers")))

    @classmethod
    def from_probe(cls, url: str, headers: Mapping[str, str] | None) -> PrivateSpec:
        return cls(slug="probe", label="probe", url=_url(url), headers=_headers(headers))


def describe_error(error: BaseException, secrets: Iterable[str] = ()) -> str:
    """One short line about `error`, safe to show: the guard's own messages as
    they are, anything else cut to its first line, with every secret hidden."""
    while isinstance(error, BaseExceptionGroup) and error.exceptions:
        error = error.exceptions[0]
    if isinstance(error, (BlockedAddress, RedirectRefused)):
        return str(error)
    if isinstance(error, (TimeoutError, httpx.TimeoutException)):
        return "Timed out"
    text = (str(error).strip().splitlines() or [""])[0].strip() or type(error).__name__
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        text = text.replace(secret, "***")
    return text[:MAX_ERROR]
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_private_spec.py tests/test_private_guard.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/ai_agent/src/private_extensions/spec.py apps/ai_agent/tests/test_private_spec.py
git commit -m "feat(ai_agent): validated private extension spec and safe error text"
```

---

### Task 3: The session pool

**Files:**
- Create: `apps/ai_agent/src/private_extensions/pool.py`
- Test: `apps/ai_agent/tests/test_private_pool.py`

**Interfaces:**
- Consumes: `PrivateSpec` (Task 2), `guarded_client_factory` (Task 1).
- Produces: `async open_private_session(stack, spec, factory, timeout_seconds) -> ClientSession`; `PrivateSessionPool(*, factory=None, opener=open_private_session, clock=time.monotonic, idle_seconds=300.0, per_account=5, total=50, connect_timeout=10.0, call_timeout=120.0)` with `async session(account, spec)`, `async tools(account, spec) -> list[types.Tool]`, `async call(account, spec, tool, arguments) -> types.CallToolResult`, `async probe(spec) -> list[types.Tool]`, `async drop(account, spec)`, `async aclose()`.

- [ ] **Step 1: Write the failing tests**

Create `apps/ai_agent/tests/test_private_pool.py`:

```python
"""pool.py: sessions are reused per account and spec, capped, expired when idle,
and a dead one is replaced once."""

from __future__ import annotations

import asyncio

import pytest
from mcp import types

from src.private_extensions.pool import PrivateSessionPool
from src.private_extensions.spec import PrivateSpec


def spec(slug="notes", **headers) -> PrivateSpec:
    return PrivateSpec.parse({"id": slug, "url": f"https://{slug}.example.com/mcp", "headers": headers})


class FakeSession:
    def __init__(self, slug: str):
        self.slug = slug
        self.calls: list[tuple] = []
        self.fail_once: Exception | None = None

    async def list_tools(self):
        return types.ListToolsResult(tools=[types.Tool(name="echo", inputSchema={"type": "object", "properties": {}})])

    async def call_tool(self, name, arguments, read_timeout_seconds=None):
        if self.fail_once is not None:
            error, self.fail_once = self.fail_once, None
            raise error
        self.calls.append((name, arguments))
        return types.CallToolResult(content=[types.TextContent(type="text", text="ok")])


class Harness:
    def __init__(self, **options):
        self.now = 1000.0
        self.opened: list[PrivateSpec] = []
        self.closed: list[str] = []
        self.sessions: list[FakeSession] = []
        self.fail_open = 0
        self.pool = PrivateSessionPool(factory=object(), opener=self.opener, clock=lambda: self.now, **options)

    async def opener(self, stack, spec, factory, timeout):
        if self.fail_open:
            self.fail_open -= 1
            raise ConnectionError("down")
        session = FakeSession(spec.slug)
        self.sessions.append(session)
        self.opened.append(spec)

        async def closed(slug):
            self.closed.append(slug)

        stack.push_async_callback(closed, spec.slug)
        return session


def run(coro):
    return asyncio.run(coro)


def test_the_same_account_and_spec_share_one_session():
    h = Harness()

    async def go():
        await h.pool.call("a@x", spec(), "echo", {})
        await h.pool.call("a@x", spec(), "echo", {})

    run(go())
    assert len(h.opened) == 1
    assert h.sessions[0].calls == [("echo", {}), ("echo", {})]


def test_another_account_or_other_headers_get_their_own_session():
    h = Harness()

    async def go():
        await h.pool.session("a@x", spec())
        await h.pool.session("b@x", spec())
        await h.pool.session("a@x", spec(**{"X-Key": "1"}))
        await h.pool.session("a@x", spec(**{"X-Key": "2"}))

    run(go())
    assert len(h.opened) == 4


def test_an_idle_session_is_closed_and_replaced_on_next_use():
    h = Harness(idle_seconds=300)

    async def go():
        await h.pool.session("a@x", spec())
        h.now += 301
        await h.pool.session("a@x", spec())

    run(go())
    assert len(h.opened) == 2
    assert h.closed == ["notes"]


def test_a_session_used_within_the_idle_time_is_kept():
    h = Harness(idle_seconds=300)

    async def go():
        await h.pool.session("a@x", spec())
        h.now += 200
        await h.pool.session("a@x", spec())
        h.now += 200
        await h.pool.session("a@x", spec())

    run(go())
    assert len(h.opened) == 1


def test_the_per_account_cap_closes_that_accounts_oldest():
    h = Harness(per_account=2)

    async def go():
        await h.pool.session("a@x", spec("one"))
        h.now += 1
        await h.pool.session("a@x", spec("two"))
        h.now += 1
        await h.pool.session("a@x", spec("three"))

    run(go())
    assert h.closed == ["one"]


def test_the_total_cap_closes_the_oldest_overall():
    h = Harness(total=2, per_account=5)

    async def go():
        await h.pool.session("a@x", spec("one"))
        h.now += 1
        await h.pool.session("b@x", spec("two"))
        h.now += 1
        await h.pool.session("c@x", spec("three"))

    run(go())
    assert h.closed == ["one"]


def test_a_failed_open_leaves_nothing_behind_and_the_next_try_works():
    h = Harness()
    h.fail_open = 1

    async def go():
        with pytest.raises(ConnectionError):
            await h.pool.session("a@x", spec())
        return await h.pool.session("a@x", spec())

    assert isinstance(run(go()), FakeSession)
    assert len(h.opened) == 1


def test_a_terminated_session_is_replaced_and_the_call_retried_once():
    h = Harness()

    async def go():
        await h.pool.call("a@x", spec(), "echo", {})
        h.sessions[0].fail_once = RuntimeError("Session terminated")
        return await h.pool.call("a@x", spec(), "echo", {"n": 1})

    result = run(go())
    assert result.content[0].text == "ok"
    assert len(h.opened) == 2
    assert h.closed == ["notes"]
    assert h.sessions[1].calls == [("echo", {"n": 1})]


def test_any_other_error_is_not_retried():
    h = Harness()

    async def go():
        await h.pool.call("a@x", spec(), "echo", {})
        h.sessions[0].fail_once = RuntimeError("boom")
        await h.pool.call("a@x", spec(), "echo", {})

    with pytest.raises(RuntimeError, match="boom"):
        run(go())
    assert len(h.opened) == 1


def test_tools_lists_what_the_server_offers():
    h = Harness()

    tools = run(h.pool.tools("a@x", spec()))

    assert [t.name for t in tools] == ["echo"]


def test_probe_opens_lists_and_closes_without_keeping_anything():
    h = Harness()

    async def go():
        tools = await h.pool.probe(spec())
        await h.pool.session("a@x", spec())  # not served from a probe
        return tools

    assert [t.name for t in run(go())] == ["echo"]
    assert h.closed == ["notes"]
    assert len(h.opened) == 2


def test_aclose_closes_everything():
    h = Harness()

    async def go():
        await h.pool.session("a@x", spec("one"))
        await h.pool.session("b@x", spec("two"))
        await h.pool.aclose()

    run(go())
    assert sorted(h.closed) == ["one", "two"]


def test_drop_closes_one_session():
    h = Harness()

    async def go():
        await h.pool.session("a@x", spec("one"))
        await h.pool.drop("a@x", spec("one"))
        await h.pool.drop("a@x", spec("one"))  # nothing left: fine

    run(go())
    assert h.closed == ["one"]
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_private_pool.py -q`
Expected: FAIL (module not found).

- [ ] **Step 3: Write `pool.py`**

Create `apps/ai_agent/src/private_extensions/pool.py`:

```python
"""Sessions to private extensions, kept per account and spec.

Everything here runs on the connection loop owned by `SyncMcpClient` (see
mcp_upstream.py); the callers on other loops reach it through
`SyncMcpClient.submit`. A session is reused while it is used at least every
`idle_seconds`; a stale one is closed the next time the pool is used.

Opening a session is split in two for the reason documented in mcp_server's
extensions.py: a failure inside the SDK's own task group (a refused handshake)
corrupts the loop's cancel scopes. So one plain `initialize` POST goes through
the same guarded client first and raises an ordinary error on a bad status.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import httpx
from mcp import types
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from src.private_extensions.guard import guarded_client_factory
from src.private_extensions.spec import PrivateSpec

CONNECT_TIMEOUT_SECONDS = 10.0
CALL_TIMEOUT_SECONDS = 120.0
IDLE_SECONDS = 300.0
MAX_PER_ACCOUNT = 5
MAX_TOTAL = 50

Opener = Callable[[AsyncExitStack, PrivateSpec, Any, float], Awaitable[ClientSession]]


async def _preflight_handshake(spec: PrivateSpec, factory: Any, timeout_seconds: float) -> None:
    payload = {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": types.LATEST_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "ai_agent-preflight", "version": "0"},
        },
    }
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json", **spec.header_map}
    async with factory(None, httpx.Timeout(timeout_seconds)) as client:
        async with client.stream("POST", spec.url, json=payload, headers=headers) as response:
            if response.status_code >= 400:
                hint = " (check the extension's headers)" if response.status_code in (401, 403) else ""
                raise ConnectionError(f"The server rejected the MCP handshake: HTTP {response.status_code}{hint}")


async def open_private_session(
    stack: AsyncExitStack, spec: PrivateSpec, factory: Any, timeout_seconds: float
) -> ClientSession:
    """Open and initialize a session for `spec`, registering what it opens on `stack`."""
    await _preflight_handshake(spec, factory, timeout_seconds)
    read_stream, write_stream, _session_id = await stack.enter_async_context(
        streamablehttp_client(spec.url, headers=spec.header_map or None, httpx_client_factory=factory)
    )
    session = await stack.enter_async_context(
        ClientSession(read_stream, write_stream, read_timeout_seconds=timedelta(seconds=timeout_seconds))
    )
    await session.initialize()
    return session


@dataclass
class _Entry:
    account: str
    stack: AsyncExitStack
    session: ClientSession
    last_used: float


async def _close_quietly(stack: AsyncExitStack) -> None:
    try:
        await stack.aclose()
    except Exception:  # noqa: BLE001 - a messy close must not break the caller
        pass


class PrivateSessionPool:
    def __init__(
        self,
        *,
        factory: Any = None,
        opener: Opener = open_private_session,
        clock: Callable[[], float] = time.monotonic,
        idle_seconds: float = IDLE_SECONDS,
        per_account: int = MAX_PER_ACCOUNT,
        total: int = MAX_TOTAL,
        connect_timeout: float = CONNECT_TIMEOUT_SECONDS,
        call_timeout: float = CALL_TIMEOUT_SECONDS,
    ) -> None:
        self._factory = factory if factory is not None else guarded_client_factory()
        self._opener = opener
        self._clock = clock
        self._idle = idle_seconds
        self._per_account = per_account
        self._total = total
        self._connect_timeout = connect_timeout
        self._call_timeout = call_timeout
        self._entries: dict[tuple[str, str], _Entry] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    async def session(self, account: str, spec: PrivateSpec) -> ClientSession:
        key = (account, spec.key())
        async with self._locks.setdefault(key, asyncio.Lock()):
            entry = self._entries.get(key)
            if entry is not None and self._clock() - entry.last_used <= self._idle:
                entry.last_used = self._clock()
                return entry.session
            if entry is not None:
                await self._close(key)
            await self._make_room(account)
            stack = AsyncExitStack()
            try:
                session = await self._opener(stack, spec, self._factory, self._connect_timeout)
            except Exception:
                await _close_quietly(stack)
                raise
            self._entries[key] = _Entry(account, stack.pop_all(), session, self._clock())
            return session

    async def _make_room(self, account: str) -> None:
        now = self._clock()
        for key, entry in list(self._entries.items()):
            if now - entry.last_used > self._idle:
                await self._close(key)
        mine = sorted((k for k, e in self._entries.items() if e.account == account), key=lambda k: self._entries[k].last_used)
        while len(mine) >= self._per_account:
            await self._close(mine.pop(0))
        while len(self._entries) >= self._total:
            await self._close(min(self._entries, key=lambda k: self._entries[k].last_used))

    async def _close(self, key: tuple[str, str]) -> None:
        entry = self._entries.pop(key, None)
        if entry is not None:
            await _close_quietly(entry.stack)

    async def drop(self, account: str, spec: PrivateSpec) -> None:
        await self._close((account, spec.key()))

    async def _use(self, account: str, spec: PrivateSpec, action: Callable[[ClientSession], Awaitable[Any]]) -> Any:
        try:
            return await action(await self.session(account, spec))
        except RuntimeError as error:
            if str(error) != "Session terminated":
                raise
        # The server dropped the session: one fresh one, one retry.
        await self.drop(account, spec)
        return await action(await self.session(account, spec))

    async def tools(self, account: str, spec: PrivateSpec) -> list[types.Tool]:
        listed = await self._use(account, spec, lambda session: session.list_tools())
        return list(listed.tools)

    async def call(self, account: str, spec: PrivateSpec, tool: str, arguments: dict[str, Any]) -> types.CallToolResult:
        timeout = timedelta(seconds=self._call_timeout)
        return await self._use(account, spec, lambda session: session.call_tool(tool, arguments, read_timeout_seconds=timeout))

    async def probe(self, spec: PrivateSpec) -> list[types.Tool]:
        """Connect once, list the tools, close. Nothing is kept."""
        stack = AsyncExitStack()
        try:
            session = await self._opener(stack, spec, self._factory, self._connect_timeout)
            return list((await session.list_tools()).tools)
        finally:
            await _close_quietly(stack)

    async def aclose(self) -> None:
        for key in list(self._entries):
            await self._close(key)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_private_pool.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/ai_agent/src/private_extensions/pool.py apps/ai_agent/tests/test_private_pool.py
git commit -m "feat(ai_agent): session pool and guarded handshake for private extensions"
```

---

### Task 4: The per-turn catalog

**Files:**
- Create: `apps/ai_agent/src/private_extensions/turn.py`
- Test: `apps/ai_agent/tests/test_private_turn.py`

**Interfaces:**
- Consumes: `PrivateSpec`, `InvalidSpec`, `describe_error` (Task 2); a pool with `async tools(account, spec)` (Task 3); `inline_refs` from `src.mcp_client.schema`.
- Produces: `TOOL_PREFIX = "u_"`, `MAX_TOOLS = 100`, `MAX_NAME = 64`; `PrivateTurn(account)` with `PrivateTurn.from_raw(raw: list | None, account: str) -> PrivateTurn`, `.specs: dict[str, PrivateSpec]`, `.errors: list[dict[str, str]]` (keys `id`, `label`, `error`), `async prefetch(pool, submit)`, `.tools() -> list[types.Tool]`, `.route(name) -> tuple[PrivateSpec, str] | None`, `__bool__` (true when it has specs); `bind(turn) -> Token`, `reset(token)`, `current() -> PrivateTurn | None`.

- [ ] **Step 1: Write the failing tests**

Create `apps/ai_agent/tests/test_private_turn.py`:

```python
"""turn.py: one turn's private extensions - validated, their tools fetched and
namespaced, and bound for the providers."""

from __future__ import annotations

import asyncio

from mcp import types

from src.private_extensions import turn as private_turn
from src.private_extensions.turn import MAX_TOOLS, PrivateTurn

RAW = [
    {"id": "notes", "label": "Notes", "url": "https://notes.example.com/mcp", "headers": {"X-Key": "s3cret"}},
    {"id": "wiki", "label": "Wiki", "url": "https://wiki.example.com/mcp"},
]


def tool(name: str, description: str = "does a thing") -> types.Tool:
    return types.Tool(
        name=name, description=description,
        inputSchema={"type": "object", "properties": {"q": {"type": "string"}}},
    )


class FakePool:
    def __init__(self, tools=None, fail=()):
        self.tools_by_slug = tools or {}
        self.fail = set(fail)

    async def tools(self, account, spec):
        if spec.slug in self.fail:
            raise ConnectionError(f"down with {spec.header_map.get('X-Key', '')}")
        return self.tools_by_slug.get(spec.slug, [])


async def submit(coro):
    return await coro


def loaded(raw=RAW, pool=None, account="a@x") -> PrivateTurn:
    turn = PrivateTurn.from_raw(raw, account)
    asyncio.run(turn.prefetch(pool or FakePool(), submit))
    return turn


def test_valid_specs_are_kept_and_invalid_ones_become_errors():
    turn = PrivateTurn.from_raw([*RAW, {"id": "Bad Id", "url": "https://x.example.com"}, "junk"], "a@x")

    assert sorted(turn.specs) == ["notes", "wiki"]
    assert len(turn.errors) == 2
    assert all(set(e) == {"id", "label", "error"} for e in turn.errors)
    assert bool(turn) is True


def test_a_duplicate_id_is_refused():
    turn = PrivateTurn.from_raw([RAW[0], {**RAW[0], "url": "https://other.example.com/mcp"}], "a@x")

    assert list(turn.specs) == ["notes"]
    assert len(turn.errors) == 1


def test_nothing_is_kept_without_an_account():
    turn = PrivateTurn.from_raw(RAW, "")

    assert turn.specs == {}
    assert bool(turn) is False
    assert [e["id"] for e in turn.errors] == ["notes", "wiki"]


def test_no_specs_is_an_empty_turn():
    turn = PrivateTurn.from_raw(None, "a@x")

    assert bool(turn) is False
    assert turn.errors == []


def test_tools_are_namespaced_and_routed_back():
    turn = loaded(pool=FakePool({"notes": [tool("search")], "wiki": [tool("find")]}))

    assert sorted(t.name for t in turn.tools()) == ["u_notes__search", "u_wiki__find"]
    spec, upstream = turn.route("u_notes__search")
    assert (spec.slug, upstream) == ("notes", "search")
    assert turn.route("u_notes__other") is None
    assert turn.route("main__ping") is None
    assert turn.errors == []


def test_a_namespaced_tool_keeps_its_schema_and_says_where_it_is_from():
    turn = loaded(pool=FakePool({"notes": [tool("search", "Find notes.")]}))
    only = next(t for t in turn.tools() if t.name == "u_notes__search")

    assert only.inputSchema["properties"]["q"] == {"type": "string"}
    assert only.description.startswith("Find notes.")
    assert "Notes" in only.description


def test_names_that_are_too_long_or_not_allowed_are_left_out_with_a_note():
    long_name = "x" * 60  # u_notes__ + 60 characters is over 64
    turn = loaded(pool=FakePool({"notes": [tool("ok"), tool(long_name), tool("has space"), tool("bad.dot")]}))

    assert [t.name for t in turn.tools()] == ["u_notes__ok"]
    assert len(turn.errors) == 1
    assert turn.errors[0]["id"] == "notes"
    assert "3 tools" in turn.errors[0]["error"]


def test_at_most_max_tools_per_extension():
    many = [tool(f"t{i}") for i in range(MAX_TOOLS + 5)]
    turn = loaded(raw=[RAW[0]], pool=FakePool({"notes": many}))

    assert len(turn.tools()) == MAX_TOOLS
    assert "5 tools" in turn.errors[0]["error"]


def test_a_down_extension_is_an_error_and_the_others_still_load():
    turn = loaded(pool=FakePool({"wiki": [tool("find")]}, fail=["notes"]))

    assert [t.name for t in turn.tools()] == ["u_wiki__find"]
    assert len(turn.errors) == 1
    assert turn.errors[0]["id"] == "notes"
    assert turn.errors[0]["label"] == "Notes"
    assert "s3cret" not in turn.errors[0]["error"]


def test_every_private_name_starts_with_the_prefix():
    turn = loaded(pool=FakePool({"notes": [tool("main__ping")], "wiki": [tool("find")]}))

    assert all(t.name.startswith(private_turn.TOOL_PREFIX) for t in turn.tools())


def test_bind_current_reset():
    assert private_turn.current() is None
    turn = PrivateTurn.from_raw(RAW, "a@x")

    token = private_turn.bind(turn)
    try:
        assert private_turn.current() is turn
    finally:
        private_turn.reset(token)
    assert private_turn.current() is None
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_private_turn.py -q`
Expected: FAIL (module not found).

- [ ] **Step 3: Write `turn.py`**

Create `apps/ai_agent/src/private_extensions/turn.py`:

```python
"""One turn's private extensions.

`ask()` builds a `PrivateTurn` from what ember_api sent, `agent_config.run_chat`
binds it for the turn (a ContextVar, like tool_filter.py and approvals.py, so
the worker threads that run tools see it) and calls `prefetch` before the
provider starts. The providers' blocking `list_tools()` then reads the cache
(`tools()`) and `call_tool` routes a `u_<slug>__<tool>` name back to its
extension (`route()`).
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any

from mcp import types

from src.mcp_client.schema import inline_refs
from src.private_extensions.spec import InvalidSpec, PrivateSpec, describe_error

TOOL_PREFIX = "u_"
MAX_TOOLS = 100
MAX_NAME = 64
_TOOL_NAME = re.compile(r"[A-Za-z0-9_-]+")

Submit = Callable[[Awaitable[Any]], Awaitable[Any]]


def _namespace(spec: PrivateSpec, tools: list[types.Tool]) -> tuple[list[tuple[types.Tool, str]], int]:
    """The tools that can be offered, as (namespaced tool, upstream name), and how many were left out."""
    kept: list[tuple[types.Tool, str]] = []
    skipped = 0
    for tool in tools:
        name = f"{TOOL_PREFIX}{spec.slug}__{tool.name}"
        if len(kept) >= MAX_TOOLS or len(name) > MAX_NAME or not _TOOL_NAME.fullmatch(name):
            skipped += 1
            continue
        description = (tool.description or "").strip()
        note = f"(Private extension: {spec.label})"
        kept.append(
            (
                types.Tool(
                    name=name,
                    description=f"{description}\n\n{note}" if description else note,
                    inputSchema=inline_refs(tool.inputSchema),
                    outputSchema=tool.outputSchema,
                    _meta=tool.meta,
                    annotations=tool.annotations,
                    icons=tool.icons,
                ),
                tool.name,
            )
        )
    return kept, skipped


@dataclass
class PrivateTurn:
    account: str
    specs: dict[str, PrivateSpec] = field(default_factory=dict)
    errors: list[dict[str, str]] = field(default_factory=list)
    _tools: dict[str, types.Tool] = field(default_factory=dict)
    _routes: dict[str, tuple[PrivateSpec, str]] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.specs)

    @classmethod
    def from_raw(cls, raw: list[Any] | None, account: str) -> PrivateTurn:
        turn = cls(account)
        for item in raw or []:
            ident = str(item.get("id", ""))[:40] if isinstance(item, dict) else ""
            label = str(item.get("label", ident))[:60] if isinstance(item, dict) else ""
            try:
                spec = PrivateSpec.parse(item)
            except InvalidSpec as error:
                turn.errors.append({"id": ident, "label": label, "error": str(error)})
                continue
            if not account:
                turn.errors.append({"id": spec.slug, "label": spec.label, "error": "This turn has no signed-in account"})
            elif spec.slug in turn.specs:
                turn.errors.append({"id": spec.slug, "label": spec.label, "error": "Two extensions have the same id"})
            else:
                turn.specs[spec.slug] = spec
        return turn

    async def prefetch(self, pool: Any, submit: Submit) -> None:
        """Connect to every extension at once and list its tools. `submit`
        runs a coroutine of `pool` on the connection loop and awaits it here."""
        await asyncio.gather(*(self._load(pool, submit, spec) for spec in self.specs.values()))

    async def _load(self, pool: Any, submit: Submit, spec: PrivateSpec) -> None:
        try:
            listed = await submit(pool.tools(self.account, spec))
        except Exception as error:  # noqa: BLE001 - one bad extension must not fail the turn
            self.errors.append({"id": spec.slug, "label": spec.label, "error": describe_error(error, spec.secrets)})
            return
        kept, skipped = _namespace(spec, listed)
        for tool, upstream in kept:
            self._tools[tool.name] = tool
            self._routes[tool.name] = (spec, upstream)
        if skipped:
            self.errors.append(
                {
                    "id": spec.slug,
                    "label": spec.label,
                    "error": f"{skipped} tools were left out: their names are too long or not allowed, or there are more than {MAX_TOOLS}",
                }
            )

    def tools(self) -> list[types.Tool]:
        return list(self._tools.values())

    def route(self, name: str) -> tuple[PrivateSpec, str] | None:
        return self._routes.get(name)


_current: ContextVar[PrivateTurn | None] = ContextVar("private_turn", default=None)


def bind(turn: PrivateTurn) -> Token:
    return _current.set(turn)


def reset(token: Token) -> None:
    _current.reset(token)


def current() -> PrivateTurn | None:
    return _current.get()
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_private_turn.py tests/test_private_pool.py tests/test_private_spec.py tests/test_private_guard.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/ai_agent/src/private_extensions/turn.py apps/ai_agent/tests/test_private_turn.py
git commit -m "feat(ai_agent): per-turn catalog of private extension tools"
```

---

### Task 5: Merge private tools into `mcp_upstream`

**Files:**
- Modify: `apps/ai_agent/src/mcp_client/sync_wrapper.py` (add `submit`, `run_coroutine`)
- Modify: `apps/ai_agent/src/mcp_client/mcp_upstream.py`
- Test: `apps/ai_agent/tests/test_private_upstream.py`

**Interfaces:**
- Consumes: `private_turn.current()`, `PrivateTurn.tools()/route()` (Task 4); `PrivateSessionPool` (Task 3); `PrivateSpec.from_probe`, `describe_error` (Task 2).
- Produces: `SyncMcpClient.submit(coro) -> concurrent.futures.Future`; `SyncMcpClient.run_coroutine(coro)`; in `mcp_upstream`: `private_pool` (a `PrivateSessionPool`), `async prefetch_private(turn) -> None`, `async probe_private(url, headers) -> dict` (never raises; `{status: "connected"|"error", error: str|None, tools: list[str]}`); `list_tools()` also returns the bound turn's tools (filtered by the agent's tool scope); `call_tool("u_...")` routes to the pool; `close()` also closes the pool.

- [ ] **Step 1: Write the failing tests**

Create `apps/ai_agent/tests/test_private_upstream.py`:

```python
"""mcp_upstream.py with private extensions: the bound turn's tools join the
catalog, calls are routed to the pool, and nothing leaks across turns."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from mcp import types

from src.mcp_client import mcp_upstream
from src.mcp_client.sync_wrapper import SyncMcpClient
from src.private_extensions import turn as private_turn
from src.private_extensions.spec import PrivateSpec
from src.private_extensions.turn import PrivateTurn

RAW = [{"id": "notes", "label": "Notes", "url": "https://notes.example.com/mcp", "headers": {"X-Key": "s3cret"}}]


class FakePool:
    def __init__(self):
        self.calls = []
        self.error: Exception | None = None
        self.probed = []

    async def tools(self, account, spec):
        return [types.Tool(name="search", description="Find.", inputSchema={"type": "object"})]

    async def call(self, account, spec, tool, arguments):
        if self.error:
            raise self.error
        self.calls.append((account, spec.slug, tool, arguments))
        return types.CallToolResult(content=[types.TextContent(type="text", text="found 3")])

    async def probe(self, spec):
        self.probed.append(spec)
        if spec.url.endswith("/down"):
            raise ConnectionError(f"refused for {spec.header_map.get('X-Key', '')}")
        return [types.Tool(name="search", inputSchema={"type": "object"}), types.Tool(name="add", inputSchema={"type": "object"})]

    async def aclose(self):
        pass


@pytest.fixture
def pool(monkeypatch):
    fake = FakePool()
    monkeypatch.setattr(mcp_upstream, "private_pool", fake)
    return fake


@pytest.fixture
def bound(pool):
    turn = PrivateTurn.from_raw(RAW, "a@x")

    async def go():
        await turn.prefetch(pool, lambda coro: coro)

    asyncio.run(go())
    token = private_turn.bind(turn)
    yield turn
    private_turn.reset(token)


def test_the_bound_turns_tools_join_the_catalog(bound):
    names = [t.name for t in mcp_upstream.list_tools([])]

    assert names == ["u_notes__search"]


def test_no_bound_turn_means_no_private_tools(pool):
    assert mcp_upstream.list_tools([]) == []


def test_the_agents_tool_scope_applies_to_private_tools(bound):
    scope = MagicMock()
    scope.tools.allows.side_effect = lambda name: not name.startswith("u_")
    with patch.object(mcp_upstream.agent_spec, "current", return_value=scope):
        assert mcp_upstream.list_tools([]) == []


def test_a_private_call_goes_to_the_pool_with_the_turns_account(bound, pool):
    out = mcp_upstream.call_tool("u_notes__search", {"q": "milk"})

    assert out == "found 3"
    assert pool.calls == [("a@x", "notes", "search", {"q": "milk"})]


def test_an_unknown_or_unbound_private_name_is_refused(bound, pool):
    with pytest.raises(PermissionError):
        mcp_upstream.call_tool("u_notes__delete", {})
    with pytest.raises(PermissionError):
        mcp_upstream.call_tool("u_other__search", {})
    assert pool.calls == []


def test_a_private_name_is_refused_outside_a_turn_that_bound_it(pool):
    with pytest.raises(PermissionError):
        mcp_upstream.call_tool("u_notes__search", {})


def test_a_private_call_is_refused_when_the_agents_scope_forbids_it(bound, pool):
    scope = MagicMock()
    scope.tools.allows.return_value = False
    with patch.object(mcp_upstream.agent_spec, "current", return_value=scope):
        with pytest.raises(PermissionError):
            mcp_upstream.call_tool("u_notes__search", {})


def test_a_failing_private_call_never_shows_a_header_value(bound, pool):
    pool.error = RuntimeError("401 for X-Key s3cret")

    with pytest.raises(RuntimeError) as caught:
        mcp_upstream.call_tool("u_notes__search", {})

    assert "s3cret" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_a_built_in_call_is_unchanged(pool):
    with patch.object(mcp_upstream.client, "call_tool", return_value=types.CallToolResult(
        content=[types.TextContent(type="text", text="pong")]
    )) as call:
        assert mcp_upstream.call_tool("main__ping", {}) == "pong"
    call.assert_called_once()


def test_prefetch_private_fills_the_turn_through_the_connection_loop(pool):
    turn = PrivateTurn.from_raw(RAW, "a@x")

    asyncio.run(mcp_upstream.prefetch_private(turn))

    assert [t.name for t in turn.tools()] == ["u_notes__search"]


def test_probe_lists_tool_names_and_never_raises(pool):
    ok = asyncio.run(mcp_upstream.probe_private("https://notes.example.com/mcp", {"X-Key": "s3cret"}))
    down = asyncio.run(mcp_upstream.probe_private("https://notes.example.com/down", {"X-Key": "s3cret"}))
    bad = asyncio.run(mcp_upstream.probe_private("file:///etc/passwd", {}))

    assert ok == {"status": "connected", "error": None, "tools": ["add", "search"]}
    assert down["status"] == "error" and down["tools"] == [] and "s3cret" not in down["error"]
    assert bad["status"] == "error" and bad["tools"] == []


def test_sync_client_can_submit_and_run_a_coroutine():
    client = SyncMcpClient()
    try:
        async def value():
            return 7

        assert client.submit(value()).result(timeout=5) == 7
        assert client.run_coroutine(value()) == 7
    finally:
        client.close()
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_private_upstream.py -q`
Expected: FAIL (`submit`, `private_pool` and the rest do not exist).

- [ ] **Step 3: Extend `SyncMcpClient`**

In `apps/ai_agent/src/mcp_client/sync_wrapper.py` add `import concurrent.futures` next to the other imports and these two methods after `_run`:

```python
    def submit(self, coro: Any) -> concurrent.futures.Future:
        """Start `coro` on the connection loop; the caller awaits or waits on the future."""
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def run_coroutine(self, coro: Any) -> Any:
        """Run `coro` on the connection loop and block until it is done."""
        return self._run(coro)
```

- [ ] **Step 4: Change `mcp_upstream.py`**

Add imports (below the existing `from src.mcp_client.sync_wrapper import SyncMcpClient`):

```python
import asyncio

from src.private_extensions import turn as private_turn
from src.private_extensions.pool import PrivateSessionPool
from src.private_extensions.spec import InvalidSpec, PrivateSpec, describe_error
```

Directly after `client = SyncMcpClient()` add:

```python
# Sessions to the users' own MCP servers (see src/private_extensions/); they
# live on the same connection loop as `client`.
private_pool = PrivateSessionPool()
```

At the end of `list_tools`, replace `return result` with:

```python
    turn = private_turn.current()
    if turn:
        # Fetched before the provider started (prefetch_private), so this never waits on a network.
        result.extend(tool for tool in turn.tools() if scope.allows(tool.name))
    return result
```

In `call_tool`, as its first statement add:

```python
    if name.startswith(private_turn.TOOL_PREFIX):
        return _call_private(name, arguments)
```

Add after `call_tool`:

```python
def _call_private(name: str, arguments: dict[str, Any]) -> str:
    turn = private_turn.current()
    route = turn.route(name) if turn else None
    if turn is None or route is None or not agent_spec.current().tools.allows(name):
        # The model only sees this turn's tools, but may still name another.
        raise PermissionError(f"tool {name!r} is not available to this agent")
    spec, upstream = route
    try:
        # No identity is sent: the user's own server is not mcp_server.
        result = client.run_coroutine(private_pool.call(turn.account, spec, upstream, arguments))
    except Exception as error:  # noqa: BLE001 - say what happened without a header value or a traceback
        raise RuntimeError(describe_error(error, spec.secrets)) from None
    parts = [getattr(block, "text", str(block)) for block in result.content]
    return "\n".join(parts) if parts else "(no output)"


async def prefetch_private(turn: "private_turn.PrivateTurn") -> None:
    """Connect to the turn's private extensions and list their tools, without
    blocking the caller's event loop."""
    await turn.prefetch(private_pool, lambda coro: asyncio.wrap_future(client.submit(coro)))


async def probe_private(url: str, headers: dict[str, str] | None) -> dict[str, Any]:
    """Connect once to `url` and report what it offers. Never raises."""
    try:
        spec = PrivateSpec.from_probe(url, headers)
    except InvalidSpec as error:
        return {"status": "error", "error": str(error), "tools": []}
    try:
        tools = await asyncio.wrap_future(client.submit(private_pool.probe(spec)))
    except Exception as error:  # noqa: BLE001 - any failure is one "error" outcome
        return {"status": "error", "error": describe_error(error, spec.secrets), "tools": []}
    return {"status": "connected", "error": None, "tools": sorted(tool.name for tool in tools)[: private_turn.MAX_TOOLS]}
```

Replace `close()` with:

```python
def close() -> None:
    client.run_coroutine(private_pool.aclose())
    client.close()
```

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest tests/test_private_upstream.py tests/test_mcp_upstream_description.py tests/test_tool_scope.py -q`
Expected: PASS. If `test_a_built_in_call_is_unchanged` fails because `call_tool` uses `agent_spec` first, read `call_tool` again: the built-in path is untouched, so the patch of `mcp_upstream.client.call_tool` must match its real signature (`client.call_tool(name, arguments, **extra)`).

- [ ] **Step 6: Commit**

```bash
git add apps/ai_agent/src/mcp_client apps/ai_agent/tests/test_private_upstream.py
git commit -m "feat(ai_agent): offer and route private extension tools through mcp_upstream"
```

---

### Task 6: Approval for private tools

**Files:**
- Modify: `apps/ai_agent/src/core/approvals.py` (`ApprovalPolicy`)
- Test: `apps/ai_agent/tests/test_private_approvals.py`

**Interfaces:**
- Produces: `ApprovalPolicy(mode, allowed_tools, ask_prefixes=())`; `needs_approval(tool)` is true when `tool not in allowed_tools` and (`mode != "off"` or `tool.startswith(ask_prefixes)`).

- [ ] **Step 1: Write the failing tests**

Create `apps/ai_agent/tests/test_private_approvals.py`:

```python
"""approvals.py with ask_prefixes: a private tool asks even when approvals are off."""

from __future__ import annotations

import asyncio

import pytest

from src.core import approvals

REQUEST = "req-priv"


@pytest.fixture(autouse=True)
def short_broker(monkeypatch):
    monkeypatch.setattr(approvals, "BROKER", approvals.ApprovalBroker(timeout=3.0, poll=0.05))


def policy(mode="off", allowed=(), prefixes=("u_",)):
    return approvals.ApprovalPolicy(mode, set(allowed), ask_prefixes=prefixes)


def test_needs_approval_rules():
    assert policy().needs_approval("u_notes__search") is True
    assert policy().needs_approval("main__ping") is False
    assert policy(allowed=["u_notes__search"]).needs_approval("u_notes__search") is False
    assert policy(mode="ask").needs_approval("main__ping") is True
    assert policy(prefixes=()).needs_approval("u_notes__search") is False
    assert approvals.ApprovalPolicy().needs_approval("u_notes__search") is False


def review(pol, tool, decision=None):
    events: list[dict] = []

    async def on_event(event):
        events.append(event)

    async def answer():
        for _ in range(200):
            await asyncio.sleep(0.01)
            if approvals.BROKER.decide(REQUEST, "s1", decision):
                return

    async def go():
        token = approvals.bind(pol)
        try:
            task = asyncio.create_task(answer()) if decision else None
            outcome = await approvals.review(REQUEST, "s1", tool, None, {}, on_event)
            if task:
                await task
            return outcome
        finally:
            approvals.reset(token)

    return asyncio.run(go()), events


def test_a_private_tool_asks_under_mode_off_and_runs_after_allow():
    outcome, events = review(policy(), "u_notes__search", "allow")

    assert outcome is None
    assert [e["type"] for e in events] == ["approval_request", "approval_resolved"]


def test_a_private_tool_is_declined_when_the_user_says_no():
    outcome, _events = review(policy(), "u_notes__search", "deny")

    assert outcome == approvals.DECLINED


def test_always_allows_the_tool_for_the_rest_of_the_turn():
    pol = policy()
    outcome, _ = review(pol, "u_notes__search", "always")

    assert outcome is None
    assert "u_notes__search" in pol.allowed_tools
    assert pol.needs_approval("u_notes__search") is False


def test_a_tool_already_allowed_for_the_chat_does_not_ask():
    outcome, events = review(policy(allowed=["u_notes__search"]), "u_notes__search")

    assert outcome is None
    assert events == []


def test_a_built_in_tool_still_does_not_ask_under_mode_off():
    outcome, events = review(policy(), "main__ping")

    assert outcome is None
    assert events == []


def test_a_delegated_agent_cannot_ask_so_a_private_tool_is_refused():
    outcome, events = review(policy(mode="deny"), "u_notes__search")

    assert outcome == approvals.DELEGATED
    assert events == []
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_private_approvals.py -q`
Expected: FAIL (`ApprovalPolicy` has no `ask_prefixes`).

- [ ] **Step 3: Change `ApprovalPolicy`**

In `apps/ai_agent/src/core/approvals.py` replace the `ApprovalPolicy` dataclass body with:

```python
@dataclass
class ApprovalPolicy:
    mode: str = "off"
    # Tools the user already allowed for this chat, and any they allow with
    # "always" during this turn.
    allowed_tools: set[str] = field(default_factory=set)
    # Tools whose name starts with one of these always need approval, even in
    # mode "off" (the user's own MCP servers - see private_extensions/turn.py).
    ask_prefixes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.mode not in APPROVAL_MODES:
            raise ValueError(f"approval_mode must be one of {', '.join(APPROVAL_MODES)}, not {self.mode!r}")

    def needs_approval(self, tool: str) -> bool:
        return tool not in self.allowed_tools and (self.mode != "off" or tool.startswith(self.ask_prefixes))
```

Also extend the module docstring's list of modes with: "A tool named in the policy's `ask_prefixes` asks even when the mode is ``off`` (and is refused under ``deny``)." `review()` needs no change: it already refuses under `deny` and asks otherwise.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_private_approvals.py tests/test_approvals.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/ai_agent/src/core/approvals.py apps/ai_agent/tests/test_private_approvals.py
git commit -m "feat(ai_agent): private extension tools always ask before running"
```

---

### Task 7: `ask()`, `run_chat`, `status()` and `probe_extension`

**Files:**
- Modify: `apps/ai_agent/src/llm/base_provider.py` (`ChatResult`)
- Modify: `apps/ai_agent/src/agents/agent_config.py` (`run_chat`)
- Modify: `apps/ai_agent/src/server.py` (`ask`, `status`, new `probe_extension`)
- Modify: `apps/ai_agent/tests/test_server.py` (status expectation)
- Test: `apps/ai_agent/tests/test_private_server.py`

**Interfaces:**
- Consumes: `private_turn.PrivateTurn`, `bind`, `reset`, `TOOL_PREFIX` (Task 4); `mcp_upstream.prefetch_private`, `probe_private` (Task 5); `ApprovalPolicy(ask_prefixes=...)` (Task 6); `internal_auth.current_requester()`.
- Produces: `ChatResult.private_extension_errors: list[dict[str, str]]` (default empty); `agent_config.run_chat(..., private_extensions=None)`; `server.ask(..., private_extensions=None)` whose reply carries `private_extension_errors` only when non-empty; `status()` includes `private_extensions` (true unless the provider is `laya`); MCP tool `probe_extension(url, headers=None) -> {status, error, tools}`.

- [ ] **Step 1: Write the failing tests**

Create `apps/ai_agent/tests/test_private_server.py`:

```python
"""ask(), run_chat, status() and probe_extension with private extensions."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from mcp import types

from src import server
from src.agents import agent_config, delegation
from src.core import approvals, internal_auth
from src.llm.base_provider import ChatResult
from src.private_extensions import turn as private_turn

RAW = [{"id": "notes", "label": "Notes", "url": "https://notes.example.com/mcp", "headers": {"X-Key": "s3cret"}}]


def run(coro):
    return asyncio.run(coro)


def test_ask_passes_private_extensions_only_when_given():
    seen = []

    async def fake_run_chat(question, history, enabled_extensions, request_id, depth, on_event=None, caveman=False,
                            approval_mode="off", allowed_tools=None, disabled_tools=None, **more):
        seen.append(more)
        return ChatResult(response="done")

    async def go():
        with patch("src.server.agent_config.run_chat", new=fake_run_chat), \
             patch("src.server.agent_config.status", return_value={"model": "m", "context_window": 1}):
            await server.ask("q")
            await server.ask("q", private_extensions=RAW)

    run(go())
    assert seen == [{}, {"private_extensions": RAW}]


def test_the_reply_carries_private_extension_errors_only_when_there_are_some():
    async def go(errors):
        async def fake_run_chat(*args, **kwargs):
            return ChatResult(response="done", private_extension_errors=errors)

        with patch("src.server.agent_config.run_chat", new=fake_run_chat), \
             patch("src.server.agent_config.status", return_value={"model": "m", "context_window": 1}):
            return await server.ask("q")

    assert "private_extension_errors" not in run(go([]))
    errors = [{"id": "notes", "label": "Notes", "error": "Timed out"}]
    assert run(go(errors))["private_extension_errors"] == errors


def test_status_reports_private_extension_support():
    fake = {"provider_id": "anthropic", "model": "m", "available": True, "reason": None, "cooldown_seconds_remaining": 0}
    with patch("src.server.agent_config.status", return_value=fake), patch.object(agent_config, "PROVIDER_ID", "anthropic"):
        assert server.status()["private_extensions"] is True
    with patch("src.server.agent_config.status", return_value=fake), patch.object(agent_config, "PROVIDER_ID", "laya"):
        assert server.status()["private_extensions"] is False


def run_with_provider(raw, *, account="a@x", prefetch=None, approval_mode="off"):
    seen = {}

    async def fake_provider(question, history, model, enabled_extensions, request_id, depth, on_event=None, caveman=False):
        seen["turn"] = private_turn.current()
        seen["prefixes"] = approvals.current().ask_prefixes
        seen["mode"] = approvals.current().mode
        return ChatResult(response="ok")

    async def fake_prefetch(turn):
        seen["prefetched"] = sorted(turn.specs)
        if prefetch:
            prefetch(turn)

    async def go():
        token = internal_auth.bind_requester(internal_auth.Requester(email=account))
        try:
            with patch.object(agent_config, "_PROVIDER_MODULE", SimpleNamespace(run_chat=fake_provider)), \
                 patch("src.mcp_client.mcp_upstream.prefetch_private", new=fake_prefetch):
                return await agent_config.run_chat("q", [], [], approval_mode=approval_mode, private_extensions=raw)
        finally:
            internal_auth.reset_requester(token)

    result = run(go())
    return result, seen


def test_run_chat_binds_the_turn_prefetches_and_makes_private_tools_ask():
    result, seen = run_with_provider(RAW)

    assert seen["prefetched"] == ["notes"]
    assert seen["turn"].account == "a@x"
    assert seen["prefixes"] == ("u_",)
    assert seen["mode"] == "off"
    assert result.private_extension_errors == []
    assert private_turn.current() is None
    assert approvals.current().ask_prefixes == ()


def test_run_chat_without_private_extensions_is_unchanged():
    result, seen = run_with_provider(None)

    assert "prefetched" not in seen
    assert seen["turn"] is None
    assert seen["prefixes"] == ()


def test_run_chat_hands_back_what_could_not_connect():
    def fail(turn):
        turn.errors.append({"id": "notes", "label": "Notes", "error": "Timed out"})

    result, _seen = run_with_provider(RAW, prefetch=fail)

    assert result.private_extension_errors == [{"id": "notes", "label": "Notes", "error": "Timed out"}]


def test_run_chat_without_an_account_drops_the_extensions_with_an_error():
    result, seen = run_with_provider(RAW, account="")

    assert "prefetched" not in seen
    assert [e["id"] for e in result.private_extension_errors] == ["notes"]
    assert seen["prefixes"] == ()


def test_a_delegate_is_never_given_private_extensions():
    captured = {}

    async def fake_call_tool(url, name, arguments, **kwargs):
        captured["arguments"] = arguments
        return {"response": "the answer"}

    turn = private_turn.PrivateTurn.from_raw(RAW, "a@x")
    token = private_turn.bind(turn)
    try:
        with patch("src.agents.delegation._call_tool", side_effect=fake_call_tool), \
             patch("src.agents.delegation.agent_registry") as registry:
            registry.get_agent.return_value = {"url": "http://127.0.0.1:9101/mcp", "label": "Sub"}
            delegation.call("openai-agent", "sub-question", depth=0)
    finally:
        private_turn.reset(token)

    assert "private_extensions" not in captured["arguments"]


def test_probe_extension_returns_what_mcp_upstream_found():
    answer = {"status": "connected", "error": None, "tools": ["add", "search"]}
    received = []

    async def fake_probe(url, headers):
        received.append((url, headers))
        return answer

    with patch("src.server.mcp_upstream.probe_private", new=fake_probe):
        assert run(server.probe_extension("https://notes.example.com/mcp", {"X-Key": "s3cret"})) == answer
        assert run(server.probe_extension("https://notes.example.com/mcp")) == answer

    assert received == [
        ("https://notes.example.com/mcp", {"X-Key": "s3cret"}),
        ("https://notes.example.com/mcp", None),
    ]
```

Also in `apps/ai_agent/tests/test_server.py` change the status test's expected dict from `{**fake_status, "tool_approval": True, "tool_filter": True}` to `{**fake_status, "tool_approval": True, "tool_filter": True, "private_extensions": True}`, and make it patch `agent_config.PROVIDER_ID` to `"anthropic"` the same way as above.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_private_server.py -q`
Expected: FAIL (`ChatResult` has no `private_extension_errors`, `ask` has no `private_extensions`).

- [ ] **Step 3: `ChatResult`**

In `apps/ai_agent/src/llm/base_provider.py`, at the end of the `ChatResult` dataclass (after `effort_note`) add:

```python
    # Private extensions that could not be used this turn (see private_extensions/turn.py):
    # [{"id", "label", "error"}]. The turn went on without their tools.
    private_extension_errors: list[dict[str, str]] = field(default_factory=list)
```

- [ ] **Step 4: `agent_config.run_chat`**

In `apps/ai_agent/src/agents/agent_config.py`:

- Add to the imports: `from src.core import approvals, internal_auth, tool_filter` (extend the existing line) and `from src.private_extensions import turn as private_turn`.
- Add the parameter `private_extensions: list[dict[str, Any]] | None = None,` to `run_chat`, right after `disabled_tools`, and a docstring paragraph: "private_extensions: the user's own MCP servers for this turn, as ember_api sent them (see private_extensions/turn.py). Their tools are offered after the user approves each one; a server that cannot be reached is reported in `result.private_extension_errors` and the turn goes on without it."
- Replace the line `policy = approvals.ApprovalPolicy(approval_mode, set(allowed_tools or ()))` and the lines through `effort = ...` so the turn is built before the policy:

```python
    requester = internal_auth.current_requester()
    private = private_turn.PrivateTurn.from_raw(private_extensions, requester.email or requester.username)
    # Validated before anything is registered: a bad mode must not start a turn.
    policy = approvals.ApprovalPolicy(
        approval_mode, set(allowed_tools or ()), ask_prefixes=(private_turn.TOOL_PREFIX,) if private else ()
    )
```

- After `filter_token = tool_filter.bind(disabled_tools or ())` add `private_token = private_turn.bind(private)`.
- Inside the `try:`, directly after the `if cancellation.is_cancelled(request_id): raise ChatCancelled()` check, add:

```python
        if private:
            # Imported here: laya agents never load mcp_upstream.
            from src.mcp_client import mcp_upstream

            await mcp_upstream.prefetch_private(private)
```

- After `result.effort_note = effort.note` add `result.private_extension_errors = list(private.errors)`.
- In `finally:`, before `tool_filter.reset(filter_token)` add `private_turn.reset(private_token)`.

Note `private_turn.bind(private)` binds an empty `PrivateTurn` when none were sent. `mcp_upstream.list_tools` only reads `turn.tools()`, which is empty, and `bool(turn)` is false, so nothing else changes.

- [ ] **Step 5: `server.py`**

In `apps/ai_agent/src/server.py`:

- `ask(...)`: add the parameter `private_extensions: list[dict[str, Any]] | None = None,` after `disabled_tools`, a docstring paragraph ("private_extensions: the user's own MCP servers for this turn, `[{id, label, url, headers}]`; see src/private_extensions/."), and build the extra arguments next to `tier_args`:

```python
        private_args = {"private_extensions": private_extensions} if private_extensions else {}
```

  then pass `**private_args` in the `agent_config.run_chat(...)` call (next to `**tier_args`).
- After the `if result.effort_note:` block add:

```python
    errors = getattr(result, "private_extension_errors", None)
    if errors:
        reply["private_extension_errors"] = errors
```

- `status()`: replace the return with:

```python
    return {
        **agent_config.status(),
        "tool_approval": True,
        "tool_filter": True,
        # laya keeps its own tool shortlist and never lists tools through mcp_upstream.
        "private_extensions": agent_config.PROVIDER_ID != "laya",
    }
```

  and add a sentence to the docstring: "`private_extensions` says ask() understands private_extensions."
- Add the tool after `status`:

```python
@mcp.tool()
async def probe_extension(url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    """Connect once to the MCP server at `url` (with `headers`, which may carry
    a secret) and report `{status, error, tools}`. Used by ember_api when a user
    adds or edits a private extension. Never raises; the error is short and
    never contains a header value."""
    return await mcp_upstream.probe_private(url, headers)
```

- [ ] **Step 6: Run to verify it passes**

Run: `python -m pytest tests/test_private_server.py tests/test_server.py tests/test_tool_filter.py tests/test_approvals.py tests/test_delegation.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/ai_agent/src apps/ai_agent/tests
git commit -m "feat(ai_agent): ask() accepts private extensions; status flag; probe_extension"
```

---

### Task 8: Docs and the full suite

**Files:**
- Modify: `apps/ai_agent/README.md`

- [ ] **Step 1: Document**

In `apps/ai_agent/README.md` find the section that documents `ask()`'s arguments (search for `disabled_tools`) and add `private_extensions` there. Then add a section "Private extensions" covering, in this order: what it is (a user's own MCP server, passed per turn by ember_api, never to delegated agents); the argument shape `[{id, label, url, headers}]` and the validation limits from this plan's Global Constraints; the address policy and why (the guard checks every connection and redirect and pins the connection to the checked IP; same-origin redirects only); that the tools are named `u_<id>__<tool>`, always ask before running, and honor the agent file's `tools` scope; `private_extension_errors` in the reply; the `probe_extension` tool; the `private_extensions` flag in `status()`; and that laya agents do not support it.

- [ ] **Step 2: Run the whole ai_agent suite**

Run: `python -m pytest -q`
Expected: PASS. A failure in an unrelated old test most likely means a fake `run_chat` or `ChatResult` stand-in that now needs `**kwargs` or the new attribute; fix the test fake, not the production code, and say so in the commit message.

- [ ] **Step 3: Commit**

```bash
git add apps/ai_agent/README.md
git commit -m "docs(ai_agent): private extensions"
```

---

## Self-review (done while writing)

- **Spec coverage (ai_agent section):** guard with resolve-check-pin, same-origin redirects, handshake preflight (Tasks 1, 3); pool with keys, caps, idle expiry, retry (Task 3); catalog namespacing, 100-tool cap, name rules, no shadowing (Task 4); `ask()` argument and `run_chat` binding (Task 7); routing, scope, no identity forwarded (Task 5); `status()` flag and the laya exception (Task 7); `probe_extension` that never raises or echoes headers (Tasks 5, 7); approval via `ask_prefixes` (Task 6); not forwarded to delegates (Task 7 test); error text without secrets (Tasks 2, 4, 5). Parts 2 and 3 of the spec are out of this plan.
- **Placeholder scan:** none.
- **Type consistency:** `PrivateSpec` (`slug`, `label`, `url`, `headers`, `header_map`, `host`, `secrets`, `key()`) is used identically in Tasks 3, 4 and 5; `PrivateTurn` (`from_raw`, `prefetch(pool, submit)`, `tools()`, `route()`, `errors`, `specs`, `account`) in Tasks 4, 5 and 7; the pool's `tools/call/probe/session/drop/aclose` signatures in Tasks 3, 4 and 5; `ApprovalPolicy.ask_prefixes` in Tasks 6 and 7; `TOOL_PREFIX = "u_"` throughout.
