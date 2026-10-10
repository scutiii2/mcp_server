"""The one kind of email a ServerWatcher sends, to its owner only.

Returns an outcome string instead of raising, because a watcher thread must keep
going whether or not mail works: "sent", "skipped: <reason>" or "failed: <reason>".
The shared Email capability owns the enabled check, configuration and SMTP delivery.
"""

from __future__ import annotations

from pathlib import Path

from src.services.email_delivery import EmailUnavailable, deliver_email
from src.services.email_render import render_email_template


def send_owner_email(
    owner: str,
    email: str,
    subject: str,
    message: str,
    details_html: str,
    *,
    config_path: Path | None = None,
    sender=deliver_email,
) -> str:
    """Emails `email` (the requester's own address) with the `notification` template."""
    if not email:
        return "skipped: no email address is known for the requester"
    body = render_email_template("notification", title=subject, message=message, details_html=details_html)
    try:
        sender([email], subject, None, body_html=body, capability_alias="server",
               config_path=config_path, owner=owner)
    except EmailUnavailable as error:
        return f"skipped: {error}"[:300]
    except Exception:  # mail trouble is reported without raw exception contents
        return "failed: email delivery failed; check MCP email configuration and delivery status"
    return "sent"
