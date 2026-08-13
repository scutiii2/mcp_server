"""Email notifications via smtplib.

Stdlib only (``smtplib`` + ``email.mime``) - no extra pip dependency, on
the same "reach for stdlib first" principle as
``infra/pending_requests.py``'s use of ``sqlite3``.

SMTP settings come from the ``"email"`` section of the JSON config file
(see ``infra/app_config.py`` and ``config.json.example``), not from env
vars, since they're structured and include a password.

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

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from mcp_server.infra.app_config import EmailConfig


def send_email(config: EmailConfig, subject: str, body_html: str, *, to: list[str] | None = None) -> None:
    """Send one HTML email.

    ``to`` defaults to ``config.to``, the standing recipient list. Pass it
    explicitly to target a different audience - an approver, or one
    specific person the message is about - without needing a second
    ``EmailConfig``/SMTP setup for each.
    """
    recipients = to if to is not None else config.to
    if not recipients:
        raise ValueError("No recipients: pass to=[...] or set a non-empty 'to' list in config.json")

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = config.from_address
    message["To"] = ", ".join(recipients)
    message.attach(MIMEText(body_html, "html"))

    with smtplib.SMTP(config.smtp_server, config.smtp_port, timeout=15) as server:
        server.starttls()
        server.login(config.from_address, config.password)
        server.sendmail(config.from_address, recipients, message.as_string())
