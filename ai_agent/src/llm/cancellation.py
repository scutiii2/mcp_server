"""Cooperative cancellation registry for in-flight chat turns, local to
this ai_agent process.

A turn runs synchronously inside this process's ask() tool call - there's
no way to reach into it and abort a network call already in flight. What
run_chat's tool-calling loop DOES already do is check something between
rounds, so a cheap process-wide flag checked at each of those points lets
a turn stop before its NEXT round rather than mid-call - bounded by one
round's latency, not instant, but far better than running the full loop
(up to 6 billed calls) to completion after chat_app's caller has already
given up on it.

Keyed by a client-generated request_id (originating in chat_app's
script.js), not by chat_id or user - request_id is unique per turn
regardless of how chat_app manages its own in-flight state. Each ai_agent
instance only ever tracks the turns it itself is serving.
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_cancelled: set[str] = set()


def register(request_id: str | None) -> None:
    """Marks the start of a new turn - clears any stale entry a reused id
    might carry (ids are client-generated random strings, so a collision
    would only happen if the client reused one itself)."""
    if not request_id:
        return
    with _lock:
        _cancelled.discard(request_id)


def cancel(request_id: str | None) -> bool:
    """Requests cancellation of the given turn. Returns False for a
    missing/empty id so the caller can tell "nothing to cancel" apart
    from "cancelled" without a separate lookup."""
    if not request_id:
        return False
    with _lock:
        _cancelled.add(request_id)
    return True


def is_cancelled(request_id: str | None) -> bool:
    if not request_id:
        return False
    with _lock:
        return request_id in _cancelled


def clear(request_id: str | None) -> None:
    """Removes a finished turn's entry so the set doesn't grow unbounded
    over the process lifetime. Safe to call whether or not the turn was
    ever actually cancelled."""
    if not request_id:
        return
    with _lock:
        _cancelled.discard(request_id)
