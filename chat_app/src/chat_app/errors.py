"""Turning an unexpected exception into something safe to show.

``str(exc)`` is written for whoever is reading the traceback, not for
whoever is on the other end of the HTTP request. It routinely contains
absolute filesystem paths, internal hostnames, ports, and occasionally a
connection string with credentials in it.

For the chat endpoint that's worse than usual, because its output is not
only shown to a person - it becomes part of a conversation transcript,
and tool-failure text is fed back to the model. Anything in there is
liable to be quoted, summarized, and repeated somewhere else.

So: log the full detail server-side, hand back a short reference the
operator can grep for. This applies to *unexpected* exceptions only.
Errors that were deliberately written for a human ("Claude is not
configured (missing API key)") are already safe and far more useful than
a reference number, so they're passed through untouched at the call site.

Two places hold the detail: the combined server.log (via the logger
below, once logging_setup.configure_logging() has wired it to disk) and
a standalone file per reference under log_dir/errors/. The standalone
file exists so the detail can be found - and shared, e.g. pasted into a
bug report - without grepping a log that may have rotated the entry away
or interleaved it with unrelated lines.
"""

from __future__ import annotations

import logging
import secrets
import traceback

from chat_app.config import settings

logger = logging.getLogger("chat_app")


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
