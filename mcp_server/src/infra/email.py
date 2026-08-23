"""Email notifications via smtplib.

Stdlib only (``smtplib`` + ``email.mime``) - no extra pip dependency, on
the same "reach for stdlib first" principle as
``infra/pending_requests.py``'s use of ``sqlite3``.

SMTP settings come from the ``"email"`` section of the JSON config file
(see ``infra/app_config.py`` and ``config.json.example``), not from env
vars, since they're structured and include a password.

Three transports are supported, because the sending account is usually a
mainstream consumer provider and they don't agree: implicit TLS on 465
(``"ssl"``), STARTTLS on 587 (``"starttls"``), and no TLS at all
(``"none"``) for a relay on the local network. ``"none"`` exists for LAN
relays and nothing else - it puts the credentials and the message on the
wire in the clear, so it's only defensible on a link you already trust.

This module raises on a failed send rather than swallowing the error, so
callers can tell "sent" from "failed to send". Whether a failure should
abort the surrounding operation is a call-site decision: a long-running
job usually wants to log the failure and carry on, which is easy to do
with a ``try``/``except`` there and impossible to undo if this module
silently succeeded instead.

Message bodies are the caller's business - build the HTML in the
capability that knows what it's announcing, and pass it in.
"""

from __future__ import annotations

import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from html import unescape

from src.infra.app_config import EmailConfig


# Anything inside these is code, not prose, and would otherwise land in the
# plain-text part as a wall of CSS.
_SCRIPT_OR_STYLE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)

# Links are pulled out as "text (url)" because the one thing these messages
# exist to carry is an approval URL, and a tag stripper that only kept the
# anchor text would produce a plain-text part telling the reader to click
# something that isn't there.
_ANCHOR = re.compile(r'<a\b[^>]*?href="([^"]*)"[^>]*>(.*?)</a>', re.DOTALL | re.IGNORECASE)

# Tags that end a visual line. Without this the whole document collapses
# onto one line, since HTML's own newlines are just source formatting.
_BLOCK_BREAK = re.compile(r"<br\s*/?>|</(?:p|div|h[1-6]|li|tr|table|blockquote)\s*>", re.IGNORECASE)

_ANY_TAG = re.compile(r"<[^>]+>")

# Stands in for a line break between the tag stripping and the whitespace
# flattening below. A real "\n" can't do the job: the source's own
# newlines are indentation of the HTML file, not of the text, and by the
# time the tags are gone the two are indistinguishable.
_LINE_BREAK = "\x00"


def _html_to_text(body_html: str) -> str:
    """Best-effort plain-text rendering of an HTML body.

    Deliberately a regex stripper rather than a parser: the bodies this
    handles are small templates written inside this project, so the
    failure modes of regex-on-HTML (comments containing tags, unquoted
    attributes, ``<`` in text that isn't markup) aren't reachable from the
    call sites, and the alternative - ``html.parser`` plus a subclass, or a
    dependency - is a lot of machinery for a fallback part.

    Known limits: no layout at all, so tables and lists come out as flat
    lines, and only ``href="..."`` in double quotes is recovered. Pass
    ``body_text`` explicitly when the wording of the text part matters.
    """
    # Dropped so the sentinel below can't be forged by the body itself.
    text = body_html.replace(_LINE_BREAK, "")
    text = _SCRIPT_OR_STYLE.sub("", text)
    text = _ANCHOR.sub(r"\2 (\1)", text)
    text = _BLOCK_BREAK.sub(_LINE_BREAK, text)
    text = _ANY_TAG.sub("", text)
    text = unescape(text)
    # One line per block, with runs of whitespace inside it collapsed -
    # otherwise a paragraph wrapped across three source lines arrives as
    # three lines with ragged indentation.
    lines = [" ".join(line.split()) for line in text.split(_LINE_BREAK)]
    return "\n".join(line for line in lines if line)


def send_email(
    config: EmailConfig,
    subject: str,
    body_html: str,
    *,
    to: list[str] | None = None,
    body_text: str | None = None,
) -> None:
    """Send one message as multipart/alternative (plain text + HTML).

    ``to`` defaults to ``config.to``, the standing recipient list. Pass it
    explicitly to target a different audience - an approver, or one
    specific person the message is about - without needing a second
    ``EmailConfig``/SMTP setup for each.

    ``body_text`` is optional and derived from the HTML when omitted. The
    derivation is what makes the text part worth having: an HTML-only body
    is a spam signal at Gmail and Yahoo, and a part that only appears when
    a caller remembers to write one would be missing from exactly the
    messages that must not be filtered. The parameter stays as an override
    for a caller that can phrase its own content better than a stripper
    can infer it.
    """
    recipients = to if to is not None else config.to
    if not recipients:
        raise ValueError("No recipients: pass to=[...] or set a non-empty 'to' list in config.json")

    if config.security not in ("ssl", "starttls", "none"):
        # Checked before opening a socket: a config that can't say how to
        # protect the connection must not get as far as offering a password
        # to a server.
        raise ValueError(
            f"Unknown email security mode {config.security!r}; expected one of ssl, starttls, none."
        )

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = config.from_address
    message["To"] = ", ".join(recipients)
    # Some receivers reject or penalize a message with no Date or
    # Message-ID, and threading in the reader's client depends on the
    # latter. smtplib adds neither.
    message["Date"] = formatdate(localtime=True)
    # make_msgid() defaults to the sending machine's hostname, which on a
    # home server is something like "desktop.lan": it leaks internal naming
    # and doesn't match the From domain, which is itself a spam heuristic.
    message["Message-ID"] = make_msgid(domain=config.from_address.rpartition("@")[2] or None)

    # Order is the protocol, not a preference: RFC 2046 says the last part
    # of a multipart/alternative is the one the client should prefer, so
    # plain text must come first for the HTML to win.
    message.attach(MIMEText(body_text if body_text is not None else _html_to_text(body_html), "plain"))
    message.attach(MIMEText(body_html, "html"))

    # smtplib exposes implicit TLS as a separate class rather than a flag,
    # because the socket is wrapped before the greeting - there is no plain
    # session on which starttls() could be called.
    if config.security == "ssl":
        client = smtplib.SMTP_SSL(config.smtp_server, config.smtp_port, timeout=15)
    else:
        client = smtplib.SMTP(config.smtp_server, config.smtp_port, timeout=15)

    with client as server:
        if config.security == "starttls":
            server.starttls()
        if config.password:
            # An empty password means the relay doesn't want AUTH at all.
            # Offering it anyway is not harmless: a server with no AUTH
            # extension answers with an error and the send fails.
            server.login(config.from_address, config.password)
        server.sendmail(config.from_address, recipients, message.as_string())
