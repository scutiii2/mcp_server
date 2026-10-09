"""The one email a watcher sends, to its owner only.

Returns an outcome string instead of raising, because a watcher thread must
keep going whether or not mail works: "sent", "skipped: <reason>" or
"failed: <reason>". The outcome is stored in the watcher's detail so the
Watchers page shows what happened.

The shared Email capability owns the enabled check, configuration and SMTP
delivery. Missing configuration is never copied from an example as a side effect.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from src.capabilities.watchers.utils.spec import WatchSpec
from src.services.email_delivery import deliver_email, EmailUnavailable
from src.services.email_render import render_email_template


def send_watcher_email(
    spec: WatchSpec,
    key: str,
    event: str,
    checks: int,
    *,
    config_path: Path | None = None,
    sender=deliver_email,
) -> str:
    """Emails `spec.email` that the watcher's condition was met ("met") or that it gave up ("timed_out")."""
    if not spec.email:
        return "skipped: no email address is known for the requester"
    title = spec.title()
    if event == "met":
        subject = f"{title} is {spec.expect}"
        message = f"The condition you asked me to watch for happened: {spec.condition_text()}."
    else:
        subject = f"Gave up watching {title}"
        message = f"I stopped watching after 24 hours without seeing: {spec.condition_text()}."
    details = (
        f"<p>Watcher <code>{escape(key)}</code>: {escape(spec.condition_text())}.<br>"
        f"Checks made: {checks}.</p>"
    )
    body = render_email_template("notification", title=subject, message=message, details_html=details)
    try:
        sender([spec.email], subject, None, body_html=body, capability_alias="watch",
               config_path=config_path, owner=spec.owner)
    except EmailUnavailable as error:
        return f"skipped: {error}"[:300]
    except Exception:  # mail trouble is reported without raw exception contents
        return "failed: email delivery failed; check MCP email configuration and delivery status"
    return "sent"
