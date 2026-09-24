import logging
import smtplib
from pathlib import Path

from flask import Flask
from flask_mail import Mail, Message

from src.utils.config_loader import load_env_secrets

logger = logging.getLogger(__name__)

mail = Mail()


class EmailDeliveryError(RuntimeError):
    """SMTP send failed (server unreachable, auth rejected, etc.)."""


def _deliver(message: Message) -> None:
    try:
        mail.send(message)
    except (smtplib.SMTPException, OSError) as error:
        logger.warning("Email to %s failed: %s", message.recipients, error)
        raise EmailDeliveryError(
            "Email could not be sent. Check the SMTP settings in secrets/secret_smtp.env."
        ) from error


def init_mail(app: Flask, secrets_dir: Path) -> None:
    smtp_secrets = load_env_secrets(Path(secrets_dir) / "secret_smtp.env")

    app.config["MAIL_SERVER"] = smtp_secrets.get("SMTP_HOST") or "localhost"
    app.config["MAIL_PORT"] = int(smtp_secrets.get("SMTP_PORT") or 587)
    app.config["MAIL_USERNAME"] = smtp_secrets.get("SMTP_USERNAME") or None
    app.config["MAIL_PASSWORD"] = smtp_secrets.get("SMTP_PASSWORD") or None
    app.config["MAIL_USE_TLS"] = (smtp_secrets.get("SMTP_USE_TLS") or "true").lower() == "true"
    app.config["MAIL_DEFAULT_SENDER"] = smtp_secrets.get("MAIL_FROM_ADDRESS") or "no-reply@example.com"

    mail.init_app(app)


def send_invite_email(invitee_email: str, code: str, expires_at) -> None:
    message = Message(
        subject="You're invited",
        recipients=[invitee_email],
        body=(
            "You've been invited to register.\n\n"
            f"Invite code: {code}\n"
            f"This code expires at {expires_at.isoformat()} and can only be used once.\n"
        ),
    )
    _deliver(message)


def send_email_verification(email: str, code: str, expires_at) -> None:
    message = Message(
        subject="Verify your email",
        recipients=[email],
        body=(
            "Enter this code to verify your email address:\n\n"
            f"Verification code: {code}\n"
            f"This code expires at {expires_at.isoformat()} and can only be used once.\n"
        ),
    )
    _deliver(message)
