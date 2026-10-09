"""The email capability's shared application entry point, for tools and local producers."""

from __future__ import annotations

import logging
from pathlib import Path

from src.config import settings
from src.services import capability_registry, email_audit, identity_context
from src.services.app_config import load_email_config
from src.services.email import send_email
from src.utils.catalog import catalog

logger = logging.getLogger(__name__)


class EmailUnavailable(RuntimeError):
    """Delivery is disabled or its configuration is unavailable."""


class EmailDeliveryError(RuntimeError):
    """Delivery failed; the message must not be retried automatically."""


@catalog
def deliver_email(
    to: list[str], subject: str, body_text: str | None,
    *, body_html: str | None = None, capability_alias: str = "email",
    prefix_subject: bool = True, in_reply_to: str | None = None,
    references: list[str] | None = None, config_path: Path | None = None,
    owner: str | None = None,
) -> str:
    """Honor the capability switch, load MCP SMTP config, deliver once, and audit metadata."""
    caller = identity_context.current_username() if owner is None else owner

    def audit(outcome: str, message_id: str = "") -> None:
        try:
            email_audit.record_delivery(settings.email_audit_path, caller, outcome, len(to), message_id)
        except Exception:
            # SMTP acceptance cannot be undone, and audit errors must not prompt duplicate sends.
            logger.warning("Email delivery audit could not be written.")

    try:
        enabled = capability_registry.is_enabled("email")
    except KeyError:
        enabled = False
    if not enabled:
        audit("skipped")
        raise EmailUnavailable("email capability is disabled; enable Email in capability controls")
    path = config_path if config_path is not None else settings.email_config_path
    if not path.is_file():
        audit("skipped")
        raise EmailUnavailable("email is not configured; configure MCP configs/config_email.json")
    try:
        config = load_email_config(path)
    except Exception:
        audit("skipped")
        raise EmailUnavailable("email config is invalid; check MCP configs/config_email.json") from None
    try:
        message_id = send_email(config, capability_alias, subject, body_html, to=to,
                               body_text=body_text, in_reply_to=in_reply_to,
                               references=references, prefix_subject=prefix_subject)
    except ValueError:
        audit("failed")
        raise ValueError("Invalid email body, recipient or header values.") from None
    except Exception:
        audit("failed")
        raise EmailDeliveryError("Email delivery failed or was incomplete; check MCP email configuration and delivery status before retrying.") from None
    audit("sent", message_id)
    return message_id
