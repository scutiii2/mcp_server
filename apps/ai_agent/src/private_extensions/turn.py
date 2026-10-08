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
