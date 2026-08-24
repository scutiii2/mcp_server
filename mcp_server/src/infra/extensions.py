"""Connect OUT to other MCP servers as a client, and re-expose their tools
as our own, namespaced tools.

This is step one of a bigger "toggleable extensions" feature. chat_app
only ever talks to this one server and picks up new tools automatically
via the ``list_tools()`` it already calls - so making an external
server's tools show up here, under a namespaced name, is enough for
chat_app to gain them with no changes on that side. This module owns the
whole mechanism: connecting out, keeping the connection alive, and
merging what it finds into this server's own tool surface.

Why this lives in mcp_server rather than chat_app: mcp_server is already
a long-lived process, while chat_app's MCP client opens a fresh
connection and event loop per HTTP request - a bad fit for holding
persistent upstream subprocess connections open. Proxying here also means
/capabilities and infra/approvals.py's approval gate extend to proxied
tools for free, just by virtue of the tools showing up in list_tools().

Registering a tool whose name/schema/handler are only known at runtime
(after connecting to an upstream server) is not what FastMCP's
``@mcp.tool()``/``add_tool()`` were built for - both derive a tool's JSON
schema by introspecting a Python function's type-hinted signature
(``mcp.server.fastmcp.tools.base.Tool.from_function`` ->
``func_metadata()``), which has no way to accept an arbitrary pre-built
JSON schema. An upstream tool's schema is exactly that: arbitrary JSON we
received over the wire, not a Python signature we wrote.

So this hooks the low-level server directly, which is the documented
fallback and turned out to be the only approach that actually fits.
Verified against the installed mcp==1.28.0 source
(mcp/server/fastmcp/server.py):

    def _setup_handlers(self) -> None:
        self._mcp_server.list_tools()(self.list_tools)
        self._mcp_server.call_tool(validate_input=False)(self.call_tool)

``self._mcp_server`` (confirmed: that is FastMCP's real attribute name,
not a guess) is the low-level ``mcp.server.lowlevel.server.Server``.
``FastMCP.list_tools()``/``.call_tool()`` are themselves nothing special -
plain async methods, registered as request handlers the same way any
handler is: ``Server.list_tools()``/``.call_tool()`` are decorators that
store whatever callable you hand them in ``self.request_handlers[...]``,
overwriting any previous registration. So re-invoking those decorators
with our own merged functions - one that lists FastMCP's own tools plus
our proxied ones, one that routes by namespace prefix to either FastMCP's
normal dispatch or an upstream ``call_tool()`` - is the exact mechanism
FastMCP itself used to wire itself up in the first place. The one thing
that is not a public API is reaching through `_mcp_server` at all - but
FastMCP exposes no other way to add a tool whose schema isn't derived
from a Python function signature, and everything reached through it
(`list_tools()`/`call_tool()` as decorators) is used exactly the way
FastMCP's own `_setup_handlers` uses it above.

Concurrency: tool calls can arrive concurrently once the server is
running, so it matters whether ``ClientSession.call_tool()`` is safe to
call from multiple asyncio tasks at once on the same session. Verified in
mcp/shared/session.py: ``BaseSession.send_request`` assigns each
request's id synchronously, with no ``await`` between reading and
incrementing ``self._request_id`` - so under asyncio's single-threaded
cooperative scheduling, two concurrent calls can't land on the same id -
and each request gets its own response stream, keyed by that id, so
responses can't cross wires either. The one shared resource, the
transport's write stream, is an ``anyio.streams.memory.MemoryObjectSendStream``
(mcp/client/stdio/__init__.py's ``stdio_client``), whose ``send()`` is
explicitly built to support multiple concurrent sender tasks (an internal
FIFO queue of waiting senders - see anyio/streams/memory.py). A single
dedicated ``stdin_writer`` task then drains that queue onto the actual
pipe one message at a time, so writes can't interleave at the OS level
either. Conclusion: concurrent ``call_tool()`` on one session is safe as
built, so no extra per-extension lock was added - one would only add
complexity without buying anything real.
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from mcp import types
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.fastmcp import FastMCP

from src.infra.app_config import (
    ExtensionConfig,
    delete_extension_config,
    load_extensions_config,
    save_extension_config,
)
from src.infra.tool_suggestions import apply_suggestions

# "__" rather than "_": a tool name registered elsewhere in this codebase
# (e.g. get_host_health_tool) already uses single underscores as ordinary
# word separators, so a single underscore here couldn't be told apart
# from part of the extension id or the upstream tool's own name. Double
# underscore is reserved specifically to mark this namespace boundary.
NAMESPACE_SEPARATOR = "__"

# How long connecting to one extension (spawn + initialize + list_tools)
# may take before that extension is recorded as failed. Bounded so one
# hung or slow-starting upstream process can't stall this server's own
# startup indefinitely - see ExtensionRegistry._connect_one.
CONNECT_TIMEOUT_SECONDS = 10.0


async def _check_tcp_reachable(url: str) -> None:
    """Raise a plain, ordinary exception if `url`'s host:port won't accept
    a TCP connection - without ever calling streamablehttp_client. See
    ExtensionRegistry._open_and_list's docstring for the full story; the
    short version is that a real connect failure (bad DNS, refused
    connection) reaching streamablehttp_client crashes this whole server,
    across three different attempts to bound/catch it from our side, so
    the fix that actually holds is to never let a host we already know is
    unreachable reach that code path at all.

    asyncio.open_connection()/wait_for(), not anyio: this performs a raw
    socket connect through plain asyncio, which creates no anyio task
    group and therefore has no cancel-scope tree for a failure here to
    corrupt - unlike everything inside streamablehttp_client. Immediately
    closes the probe socket either way; this only ever answers "is anyone
    listening," the real connection is opened separately right after this
    returns.
    """
    parsed = urlsplit(url)
    if parsed.hostname is None:
        raise ValueError(f"Extension URL has no host: {url!r}")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    _reader, writer = await asyncio.wait_for(
        asyncio.open_connection(parsed.hostname, port), timeout=CONNECT_TIMEOUT_SECONDS
    )
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:  # noqa: BLE001 - this was only ever a reachability probe
        pass


@dataclass
class ExtensionStatus:
    """What GET /extensions (and the startup banner) report for one
    configured extension. Field names and `status` values ("connected" |
    "error") match the HTTP contract in extension_routes.py exactly -
    another agent is building chat_app's sidebar against that shape
    concurrently, so this is not a place to improvise."""

    id: str
    label: str
    description: str
    status: str
    error: str | None = None
    tools: list[str] = field(default_factory=list)


@dataclass
class _ProxiedTool:
    """One upstream tool, registered here under its namespaced name."""

    extension_id: str
    upstream_name: str
    definition: types.Tool  # already carries the *namespaced* name


class ExtensionRegistry:
    """Owns every live upstream connection, for the life of the process.

    A class rather than bare module globals (contrast infra/approvals.py's
    module-level ``_REGISTRY``): that registry is a static list of
    handlers registered once at import time and never torn down, while
    this one holds open subprocesses and network-shaped resources that a
    test needs to spin up and tear down repeatedly without leaking into
    other tests. The real server still only ever has one instance, held
    by ``install_extensions`` below.
    """

    def __init__(self) -> None:
        # One AsyncExitStack *per* extension, not one shared stack.
        # A shared AsyncExitStack only supports closing everything it
        # holds, in LIFO order - there's no way to pop one entry out of
        # the middle. That was fine when every extension connected once
        # at startup and stayed connected for the server's whole life,
        # but `remove()` needs to close exactly one extension's
        # connection without touching any other's, so each gets its own
        # stack, closed independently.
        self._extension_stacks: dict[str, AsyncExitStack] = {}
        self._sessions: dict[str, ClientSession] = {}  # extension id -> session
        self._proxied: dict[str, _ProxiedTool] = {}  # namespaced name -> tool
        self._statuses: list[ExtensionStatus] = []
        self._mcp: FastMCP | None = None
        # Guards add()/remove() (and the module-level add_extension()/
        # remove_extension() wrappers, which hold it across the registry
        # mutation *and* the config.json write together) against two
        # concurrent HTTP requests racing on the shared dicts/lists below.
        # connect_all() doesn't need it: nothing else runs concurrently
        # with startup.
        self._mutation_lock = asyncio.Lock()

    def statuses(self) -> list[ExtensionStatus]:
        """One entry per *configured* extension, connected or not - in
        config order, so the banner and /extensions read the same way
        the operator wrote config.json."""
        return list(self._statuses)

    def proxied_tool_definitions(self) -> list[types.Tool]:
        return [proxied.definition for proxied in self._proxied.values()]

    def is_proxied(self, name: str) -> bool:
        return name in self._proxied

    async def connect_all(self, config_path: Path) -> None:
        """Connect to every extension in config.json's "extensions"
        section. Each is isolated (see _connect_one): a bad command,
        a refused connection, or a timeout on one extension is recorded
        as that extension's status and never raised out of here, so it
        can't stop a sibling extension - or this server's own tools -
        from starting.
        """
        for extension_id, extension_config in load_extensions_config(config_path).items():
            await self._connect_one(extension_id, extension_config)

    async def _connect_one(self, extension_id: str, config: ExtensionConfig) -> ExtensionStatus:
        """Connect one extension, append its ExtensionStatus, and return
        it. Isolated by design: an exception here is caught and recorded
        as that extension's status, never raised out - see connect_all()
        and add() below, both of which rely on that to keep one bad
        extension from affecting anything else. Not locked itself -
        connect_all() calls this in a plain loop at startup with nothing
        else running concurrently; add() below is what locks, around
        this same call, for the runtime case.
        """
        # A *local* stack, not this extension's entry in
        # self._extension_stacks, until we know this connection actually
        # worked. Registering half-open resources there would keep a
        # broken extension's subprocess alive (and its fds open) for this
        # server's entire run, on the off chance shutdown eventually
        # reaps it - closing it the moment we know it failed is cheap and
        # immediate instead.
        local_stack = AsyncExitStack()
        try:
            # No external timeout wrapper (neither asyncio.wait_for nor
            # anyio.fail_after) around this call - see _open_and_list's
            # docstring for why both were tried and both corrupted anyio's
            # cancel-scope tree for this server's one long-lived task.
            # CONNECT_TIMEOUT_SECONDS is instead threaded into
            # ClientSession itself, whose own request-handling code bounds
            # each request with a *correctly* scoped anyio.fail_after -
            # one that only wraps waiting for that request's response,
            # never the transport's task-group-owning connect step.
            session, listed = await self._open_and_list(local_stack, config)
        except Exception as error:  # noqa: BLE001 - one bad extension must not block the others
            try:
                await local_stack.aclose()
            except Exception:  # noqa: BLE001 - a messy close must not escape a failed connect
                pass
            status = ExtensionStatus(
                id=extension_id,
                label=config.label,
                description=config.description,
                status="error",
                error=str(error) or type(error).__name__,
            )
            self._statuses.append(status)
            return status

        # Success: hand the local stack's resources over to this
        # extension's own long-lived stack so they close when the server
        # shuts down (or this one extension is removed), not when this
        # function returns.
        opened = local_stack.pop_all()
        self._extension_stacks[extension_id] = opened

        tool_names: list[str] = []
        for tool in listed.tools:
            namespaced = f"{extension_id}{NAMESPACE_SEPARATOR}{tool.name}"
            self._proxied[namespaced] = _ProxiedTool(
                extension_id=extension_id,
                upstream_name=tool.name,
                definition=types.Tool(
                    name=namespaced,
                    description=tool.description,
                    inputSchema=tool.inputSchema,
                    outputSchema=tool.outputSchema,
                    # mcp.types.Tool aliases its "meta" field to "_meta" on
                    # the wire without populate_by_name, and the model's
                    # extra="allow" config means a keyword of meta= here
                    # would silently create a stray extra attribute instead
                    # of setting the real field - verified live against the
                    # installed mcp==1.28.0. Don't "normalize" this back to
                    # meta= - it would silently reintroduce that bug.
                    _meta=tool.meta,
                    annotations=tool.annotations,
                    icons=tool.icons,
                ),
            )
            tool_names.append(namespaced)

        self._sessions[extension_id] = session
        status = ExtensionStatus(
            id=extension_id,
            label=config.label,
            description=config.description,
            status="connected",
            error=None,
            tools=tool_names,
        )
        self._statuses.append(status)
        return status

    async def _remove_one(self, extension_id: str) -> bool:
        """The unlocked core of remove() - see remove() for the public,
        locked entry point, and add_extension()/remove_extension() below
        for why this is split out from remove() the same way _connect_one
        is split out from add(): the module-level functions need to hold
        the lock across the registry mutation *and* the config.json
        write, which means they can't go through the already-locked
        public methods without deadlocking on this registry's own lock.
        """
        if extension_id not in {status.id for status in self._statuses}:
            return False

        stack = self._extension_stacks.pop(extension_id, None)
        if stack is not None:
            # Only present for an extension that actually connected - one
            # recorded as "error" never got a session or a stack, just a
            # status entry, which the filter below removes on its own.
            try:
                await stack.aclose()
            except Exception:  # noqa: BLE001 - a messy close must not stop removal
                pass

        self._sessions.pop(extension_id, None)
        for name in [n for n, proxied in self._proxied.items() if proxied.extension_id == extension_id]:
            del self._proxied[name]
        self._statuses = [status for status in self._statuses if status.id != extension_id]
        return True

    async def add(self, extension_id: str, config: ExtensionConfig) -> ExtensionStatus:
        """Connect a new extension at runtime, the same way connect_all()
        connects the ones from config.json at startup - same failure
        isolation, a connect error is recorded as an "error" status and
        returned, not raised. Locked so two concurrent add()/remove()
        calls can't interleave their dict/list mutations.
        """
        async with self._mutation_lock:
            return await self._connect_one(extension_id, config)

    async def remove(self, extension_id: str) -> bool:
        """Disconnect a runtime extension: close its connection (if it
        had one - an "error" status never did) and drop every trace of
        it from this registry. False for an unknown id. Locked, same
        reasoning as add().
        """
        async with self._mutation_lock:
            return await self._remove_one(extension_id)

    @staticmethod
    async def _open_and_list(
        local_stack: AsyncExitStack, config: ExtensionConfig
    ) -> tuple[ClientSession, types.ListToolsResult]:
        """Open the upstream connection - spawning a subprocess (stdio) or
        connecting to a URL (http), depending on `config.transport` - then
        complete the MCP handshake and ask what it offers. Split out from
        _connect_one so the connect sequence and the try/except/cleanup
        logic around it don't tangle together.

        No caller-side timeout wrapper around this whole function (neither
        asyncio.wait_for nor anyio.fail_after - both were tried and both
        corrupted anyio's cancel-scope tree for this server's single
        long-lived task, because streamablehttp_client/stdio_client open an
        anyio task group here that's meant to outlive this function -
        local_stack's ownership is handed to the registry's long-lived
        per-extension stack (see _connect_one) so the connection stays
        usable for the extension's whole life, not just for this call.
        Wrapping "connect AND keep the task group open past this function
        returning" in any scope that itself gets exited here - by
        asyncio.wait_for's cross-task cancellation, or by anyio.fail_after
        exiting its `with` block - while a task group opened *inside* it is
        still alive is a scope-nesting violation anyio doesn't recover from
        cleanly. Confirmed live, twice.

        A THIRD attempt - dropping the wrapper entirely and passing
        CONNECT_TIMEOUT_SECONDS as ClientSession's own read_timeout_seconds
        instead, so the SDK's own correctly-scoped anyio.fail_after inside
        send_request() would bound initialize()/list_tools() - still
        crashed the same way, which showed the wrapper was never actually
        the root cause. Read mcp/client/streamable_http.py directly:
        streamable_http_client's `async with anyio.create_task_group() as
        tg:` spawns the request-writing coroutine (`post_writer`) as tg's
        OWN child task via `tg.start_soon(...)`, separate from whatever
        task is awaiting a response through ClientSession. A real connect
        failure there (bad DNS, refused connection - not a timeout) makes
        post_writer's task raise, which cancels tg from a task other than
        the one that entered it, and unwinding that through the suspended
        `@asynccontextmanager` generator (forcing it via athrow() to run
        its `finally`) hits the exact same cross-task cancel-scope bug -
        confirmed unrelated to anything in this file, since by this third
        attempt nothing here was wrapping the call at all anymore.

        The fix that actually holds: never let a host we already know is
        down reach streamablehttp_client in the first place. See
        _check_tcp_reachable - a plain asyncio TCP probe with no anyio
        task group of its own, so it can't trigger this bug, run before
        streamablehttp_client for the http branch below. CONNECT_TIMEOUT_
        SECONDS still bounds initialize()/list_tools() via
        read_timeout_seconds for whatever this probe can't catch (TCP
        accepts, but the MCP handshake itself hangs or is refused).
        """
        if config.transport == "http":
            assert config.url is not None  # guaranteed by _build_extension/the POST route
            await _check_tcp_reachable(config.url)
            read_stream, write_stream, _get_session_id = await local_stack.enter_async_context(
                streamablehttp_client(config.url)
            )
        else:
            params = StdioServerParameters(command=config.command, args=config.args)
            read_stream, write_stream = await local_stack.enter_async_context(stdio_client(params))
        session = await local_stack.enter_async_context(
            ClientSession(read_stream, write_stream, read_timeout_seconds=timedelta(seconds=CONNECT_TIMEOUT_SECONDS))
        )
        await session.initialize()
        listed = await session.list_tools()
        return session, listed

    async def call(self, name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        """Forward a call to whichever upstream session owns `name`.

        Callers are expected to have checked ``is_proxied(name)`` first
        (that's what routes dispatch on) - a name that slips through
        anyway is a programming error in the caller, not a normal
        "unknown tool" outcome a model should be told to retry, so this
        raises rather than returning a synthetic error result.
        """
        proxied = self._proxied.get(name)
        if proxied is None:
            raise KeyError(f"No proxied tool named {name!r}")
        session = self._sessions[proxied.extension_id]
        return await session.call_tool(proxied.upstream_name, arguments)

    async def merged_list_tools(self) -> list[types.Tool]:
        """FastMCP's own tools plus every connected extension's, in that
        order. This is registered as the low-level ListToolsRequest
        handler by install(); it's also directly callable, which is what
        makes it testable without going through the low-level protocol
        plumbing.

        apply_suggestions() runs only on our own tools, not the proxied
        ones - infra/tool_suggestions.py's registry is keyed by our own
        tools' names, which a proxied (namespaced) tool can never match.
        """
        assert self._mcp is not None, "install() must run before merged_list_tools()"
        own_tools = await self._mcp.list_tools()
        apply_suggestions(own_tools)
        return [*own_tools, *self.proxied_tool_definitions()]

    async def merged_call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Route by namespace prefix: a proxied name goes upstream,
        anything else goes through FastMCP's normal dispatch - the same
        split /capabilities and infra/approvals.py rely on, since neither
        of those needed to change to cover proxied tools; they just see
        more entries in list_tools().

        Return type is `Any`, not `types.CallToolResult`: a proxied call
        returns the upstream CallToolResult verbatim, but FastMCP's own
        call_tool() (the non-proxied branch) returns its own looser shape
        - Sequence[ContentBlock] | dict[str, Any] - which the low-level
        call_tool() decorator normalizes either way.
        """
        assert self._mcp is not None, "install() must run before merged_call_tool()"
        if self.is_proxied(name):
            return await self.call(name, arguments)
        return await self._mcp.call_tool(name, arguments)

    def install(self, mcp: FastMCP) -> None:
        """Wire this registry's tools into `mcp`'s list_tools/call_tool.

        Re-invoking Server.list_tools()/.call_tool() overwrites the
        handler FastMCP's own __init__ registered
        (self.request_handlers[ListToolsRequest] = ...), the same
        overwrite-by-re-registering FastMCP itself relies on - see this
        module's docstring for the verified source. validate_input=False
        is carried over from FastMCP's own registration on purpose: it's
        there because FastMCP does its own ad hoc input coercion before
        validating, and dropping it here would silently start validating
        against a raw JSON Schema for tools that were never expecting
        that fastmcp-agnostic behaviour.
        """
        self._mcp = mcp
        mcp._mcp_server.list_tools()(self.merged_list_tools)
        mcp._mcp_server.call_tool(validate_input=False)(self.merged_call_tool)

    async def aclose(self) -> None:
        """Close every open upstream connection, in no particular order
        across extensions (each has its own independent stack now - see
        __init__). One extension failing to close cleanly must not stop
        the others from closing, same failure-isolation reasoning as
        _connect_one's try/except around connecting in the first place.
        """
        for stack in self._extension_stacks.values():
            try:
                await stack.aclose()
            except Exception:  # noqa: BLE001 - a messy shutdown must not block the rest
                pass
        self._extension_stacks.clear()


_registry: ExtensionRegistry | None = None


async def install_extensions(mcp: FastMCP, config_path: Path) -> list[ExtensionStatus]:
    """Connect every configured extension and merge their tools into
    `mcp`. Called once at startup, before the tool-count banner line, so
    proxied tools are counted like any other (see run.py). Always
    installs the merged handlers, even with zero extensions configured,
    so /extensions and the dispatch path behave identically whether or
    not any are in use - one code path instead of two.
    """
    global _registry
    registry = ExtensionRegistry()
    await registry.connect_all(config_path)
    registry.install(mcp)
    _registry = registry
    return registry.statuses()


async def merged_list_tools() -> list[types.Tool]:
    """The full tool list as an MCP client would see it right now - our
    own tools plus every connected extension's. A module-level
    convenience over ``ExtensionRegistry.merged_list_tools`` so a caller
    that only has the module (run.py's startup banner) doesn't need to
    thread the registry object through. Empty before install_extensions()
    has run, same reasoning as current_statuses() below."""
    if _registry is None:
        return []
    return await _registry.merged_list_tools()


def current_statuses() -> list[ExtensionStatus]:
    """Read by extension_routes.py's GET /extensions. Empty before
    install_extensions() has run (e.g. import time), same as an empty
    "extensions" section - both mean "nothing to report" rather than an
    error, since asking this before startup finishes is a legitimate
    thing for a health check to do."""
    if _registry is None:
        return []
    return _registry.statuses()


async def shutdown_extensions() -> None:
    """Close every open upstream connection. The mirror of
    install_extensions() at the other end of the server's life - see
    run.py, which calls this from a `finally` around serving so a
    subprocess doesn't outlive the server that spawned it, however the
    server stops."""
    global _registry
    if _registry is not None:
        await _registry.aclose()
        _registry = None


async def add_extension(config: ExtensionConfig, config_path: Path) -> ExtensionStatus | None:
    """Connect a new extension at runtime and persist it to config.json,
    as one operation. Called by extension_routes.py's POST /extensions.

    None only if called before install_extensions() has run - shouldn't
    happen once the server is actually serving requests, since the POST
    route only exists on an app built after that point.

    Persist-then-connect, not the other way around. `_connect_one` is
    built to never raise - a connect failure (unreachable URL, bad
    command) is caught and recorded as an "error" status, not propagated
    - so persisting first and connecting second can never leave a config
    entry this process doesn't also know about. The reverse order can:
    `save_extension_config` writes to disk and *can* raise (the file got
    deleted out from under a running process, a permissions error, a full
    disk), and connect-then-persist would leave a freshly connected,
    fully live extension in memory - proxied tools and all - while the
    caller was told the request failed with a 500 and nothing happened.
    Persist first so a write failure leaves the registry untouched,
    matching the error the caller actually sees.

    Holds `_registry._mutation_lock` across *both* the config.json write
    and the registry mutation, not just the latter - two concurrent POST
    requests must not interleave their file writes any more than their
    dict mutations, and save_extension_config itself takes no lock of its
    own (see its docstring). Calling `_registry.add()` here instead would
    reacquire the same (non-reentrant) lock and deadlock, which is why
    this goes straight to the unlocked `_connect_one` under one lock
    acquisition that spans the write too.
    """
    if _registry is None:
        return None
    async with _registry._mutation_lock:
        save_extension_config(config_path, config)
        status = await _registry._connect_one(config.id, config)
    return status


async def remove_extension(extension_id: str, config_path: Path) -> bool:
    """Disconnect a runtime extension and remove it from config.json, as
    one operation. Called by extension_routes.py's DELETE
    /extensions/{id}. False for an unknown id.

    Delete-then-disconnect, same reasoning as add_extension's
    persist-then-connect: `delete_extension_config` is idempotent (a no-op
    if the id was never in config.json) and can raise on a write failure,
    while `_remove_one` is built to never raise. Deleting from config
    first means a write failure leaves the live registry untouched -
    still connected, still reachable, exactly as config.json (unchanged)
    says it should be - rather than tearing down a real connection and
    then failing to record that on disk. Whether the id is actually known
    is decided by `_remove_one`'s return value, not by anything here, so
    calling delete first for an id `_remove_one` will end up saying is
    unknown costs nothing - deleting an absent entry is a no-op.

    See add_extension's docstring for why this holds the lock itself and
    calls the unlocked `_remove_one` rather than going through
    `_registry.remove()`.
    """
    if _registry is None:
        return False
    async with _registry._mutation_lock:
        delete_extension_config(config_path, extension_id)
        removed = await _registry._remove_one(extension_id)
    return removed
