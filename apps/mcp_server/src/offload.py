"""Runs a synchronous tool function off the asyncio event loop.

FastMCP calls a registered tool directly on the event loop when it's a
plain ``def``, not ``async def`` - confirmed by reading the installed
``mcp`` SDK itself
(``mcp/server/fastmcp/utilities/func_metadata.py``'s
``call_fn_with_arg_validation``)::

    if fn_is_async:
        return await fn(**arguments_parsed_dict)
    else:
        return fn(**arguments_parsed_dict)   # <- called inline, no thread

There is no thread/executor offload anywhere in that path. Every tool in
this codebase can do blocking I/O (Docker calls, SSH via paramiko,
HTTP) - so a plain sync tool function freezes the *entire server*
for its full duration, not just that one request.

A blocked event loop makes concurrent calls queue behind one another
until the client's own transport gives up and resets the connection.

``@offload`` turns a sync tool function into an async one that runs the
original in a worker thread via ``asyncio.to_thread``, so FastMCP's own
``inspect.iscoroutinefunction`` check sees an async function and awaits
it properly instead of calling it inline. ``functools.wraps`` preserves
the original signature (including ``Annotated[..., Field(...)]``
parameter types) via ``__wrapped__`` - ``inspect.signature()`` follows
that by default, which is what FastMCP's own schema-building
(``func_metadata()`` in the same file, ``inspect.signature(func,
eval_str=True)``) relies on, so the tool's JSON schema is unaffected;
only *dispatch* changes.

Apply as the innermost decorator - directly above ``def``, below
``@mcp.tool(...)`` - since decorators apply bottom-up and ``@mcp.tool()``
must see the already-async wrapper this produces, not the original sync
function::

    @command(name="list", description="...")
    @mcp.tool(meta={...})
    @offload
    def tool_srv_listApps(...) -> AppListResult:
        ...

``@command`` doesn't care either way - it only records registry
metadata and returns its argument unchanged (see ``commands.py``), so
its position relative to ``@offload`` doesn't matter; convention here
keeps it outermost since it's least related to *how* the function runs.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import typing
from typing import Any, Callable, TypeVar

from mcp.server.fastmcp import Context

from src.services import progress

F = TypeVar("F", bound=Callable[..., Any])


def offload(fn: F) -> F:
    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        return await asyncio.to_thread(fn, *args, **kwargs)

    return wrapper  # type: ignore[return-value]


def offload_with_progress(fn: F) -> F:
    """``offload`` plus live progress: whatever the worker thread passes to
    ``services.progress.report()`` reaches the MCP client as a
    ``notifications/progress`` while the call is still running.

    The wrapper adds an optional ``ctx: Context`` parameter to the signature
    FastMCP sees (that is how FastMCP knows to inject it) but never passes it
    on - the wrapped function keeps its plain signature and needs no MCP
    import. Same decorator position as ``offload``."""
    # Resolve string annotations (a tool module using ``from __future__ import
    # annotations``) now, in fn's own namespace: the signature below is
    # evaluated by FastMCP without it, so a name like ``SystemLabel`` would
    # otherwise fail to resolve from this module.
    hints = typing.get_type_hints(fn, include_extras=True)
    signature = inspect.signature(fn)
    signature = signature.replace(
        parameters=[p.replace(annotation=hints.get(p.name, p.annotation)) for p in signature.parameters.values()],
        return_annotation=hints.get("return", signature.return_annotation),
    )

    @functools.wraps(fn)
    async def wrapper(*args: Any, ctx: Context | None = None, **kwargs: Any) -> Any:
        loop = asyncio.get_running_loop()
        pending: list[Any] = []
        counter = 0

        def sink(message: str) -> None:
            nonlocal counter
            if ctx is None:
                return
            counter += 1
            pending.append(asyncio.run_coroutine_threadsafe(ctx.report_progress(counter, None, message), loop))

        token = progress.bind(sink)
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        finally:
            progress.reset(token)
            # Deliver every queued notification before the result goes out.
            await asyncio.gather(*(asyncio.wrap_future(f) for f in pending), return_exceptions=True)

    wrapper.__signature__ = signature.replace(  # type: ignore[attr-defined]
        parameters=[
            *signature.parameters.values(),
            inspect.Parameter("ctx", inspect.Parameter.KEYWORD_ONLY, default=None, annotation=Context),
        ]
    )
    wrapper.__annotations__ = {**hints, "ctx": Context}
    return wrapper  # type: ignore[return-value]
