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
"""

from __future__ import annotations

import logging
import secrets

logger = logging.getLogger("chat_app")


def report(exc: Exception, *, context: str) -> str:
    """Log ``exc`` with a fresh reference id and return a message safe to display."""
    reference = secrets.token_hex(4)
    logger.exception("[%s] %s", reference, context, exc_info=exc)
    return (
        f"Something went wrong while {context}. "
        f"The details are in the server log under reference {reference}."
    )
