"""The one email a watcher sends, to its owner only.

Returns an outcome string instead of raising, because a watcher thread must
keep going whether or not mail works: "sent", "skipped: <reason>" or
"failed: <reason>". The outcome is stored in the watcher's detail so the
Watchers page shows what happened.

The email config file is checked for existence before it is loaded:
`app_config.load_config` copies the `.example` file into place when the real
one is missing, and a watcher must not do that as a side effect.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from src.capabilities.watchers.utils.spec import WatchSpec
from src.config import settings
from src.services.app_config import load_email_config
from src.services.email import send_email
from src.services.email_render import render_email_template


def send_watcher_email(
    spec: WatchSpec,
    key: str,
    event: str,
    checks: int,
    *,
    config_path: Path | None = None,
    loader=load_email_config,
    sender=send_email,
) -> str:
    """Emails `spec.email` that the watcher's condition was met ("met") or that it gave up ("timed_out")."""
    if not spec.email:
        return "skipped: no email address is known for the requester"
    path = config_path if config_path is not None else settings.email_config_path
    if not path.exists():
        return "skipped: email is not configured"
    try:
        config = loader(path)
    except Exception as error:  # noqa: BLE001 - a bad config must not stop the watcher
        return f"skipped: email config is invalid ({error})"[:300]

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
        sender(config, "watch", subject, body, to=[spec.email])
    except Exception as error:  # noqa: BLE001 - mail trouble is reported, never raised
        return f"failed: {type(error).__name__}: {error}"[:300]
    return "sent"
