"""Marks a function or class as part of the cross-project reuse catalog.

This decorator is a no-op at runtime - it exists only so decorated source
imports cleanly when chat_app runs. The standalone catalog_service (see
docs/superpowers/plans/2026-09-13-catalog-service.md) finds decorated
functions/classes by statically parsing this file's source with Python's
`ast` module; it never imports this module or calls this function. Any
name=/description= passed here is read out of the decorator's own source
text by that static scan, not by executing this code.

This file is deliberately duplicated identically into mcp_server and
ai_agent rather than shared - see the plan's Global Constraints for why
(this repo has no shared package across the three apps).
"""

from __future__ import annotations

from typing import Callable, TypeVar

T = TypeVar("T")


def catalog(
    _obj: T | None = None, *, name: str | None = None, description: str | None = None
) -> T | Callable[[T], T]:
    def decorator(obj: T) -> T:
        return obj

    if _obj is not None:
        return decorator(_obj)
    return decorator
