"""Tools one user switched off for their own chats.

ember_web lets each account turn a built-in capability off for itself; ember_api
passes the tool names of those capabilities to `ask()` as `disabled_tools`.
This is the other half of `agents/<id>.json`'s `tools` scope: that one is the
agent's own, fixed in its file, while this one belongs to the turn.

The set travels in a ContextVar, like approvals.py's policy, so the providers'
signatures stay as they are and the worker thread behind `delegate_to_agent`
(which copies the context) sees it too. A delegated agent runs in another
process, so delegation.py passes the set on explicitly.
"""

from __future__ import annotations

from collections.abc import Iterable
from contextvars import ContextVar, Token

_blocked: ContextVar[frozenset[str]] = ContextVar("blocked_tools", default=frozenset())


def bind(names: Iterable[str]) -> Token:
    """Blocks `names` (mcp_server tool names, without the "main__" prefix) for this turn."""
    return _blocked.set(frozenset(names))


def reset(token: Token) -> None:
    _blocked.reset(token)


def blocked() -> frozenset[str]:
    return _blocked.get()


def is_blocked(name: str) -> bool:
    return name in _blocked.get()
