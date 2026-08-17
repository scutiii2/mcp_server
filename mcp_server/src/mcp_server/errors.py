"""Turning an unexpected exception into something safe to show.

Mirrors chat_app/src/chat_app/errors.py - see that module's docstring
for the full reasoning. Short version: ``str(exc)`` is written for a
traceback reader, not for whoever ends up looking at a page built from
it, and routinely contains filesystem paths, hostnames, or credentials.
Here that matters for approval_routes.py's failure page in particular -
reachable by clicking a link in an email, so not necessarily read by
whoever wrote the code that raised.

Two places hold the detail: the combined server.log (via the logger
below, once logging_setup.configure_logging() has wired it to disk) and
a standalone file per reference under log_dir/errors/.
"""

from __future__ import annotations

import logging
import secrets
import traceback

from mcp_server.config import settings

logger = logging.getLogger("mcp_server")


def report(exc: Exception, *, context: str) -> str:
    """Log ``exc`` with a fresh reference id and return a message safe to display."""
    reference = secrets.token_hex(4)
    logger.exception("[%s] %s", reference, context, exc_info=exc)
    _write_error_file(exc, reference=reference, context=context)
    return (
        f"Something went wrong while {context}. "
        f"The details are in the server log under reference {reference}."
    )


def _write_error_file(exc: Exception, *, reference: str, context: str) -> None:
    errors_dir = settings.log_dir / "errors"
    errors_dir.mkdir(parents=True, exist_ok=True)
    trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    (errors_dir / f"{reference}.log").write_text(
        f"reference: {reference}\ncontext: {context}\n\n{trace}", encoding="utf-8"
    )
