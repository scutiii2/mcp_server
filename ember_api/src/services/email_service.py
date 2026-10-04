"""Outgoing email for invite and verification codes.

Routes depend on the EmailSender protocol; the app wires SmtpEmailSender
(secrets/secret_smtp.env), tests wire a fake.
"""

from __future__ import annotations

import asyncio
import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Protocol

from src.utils.config_loader import load_env_secrets


class EmailDeliveryError(RuntimeError):
    """Sending failed (SMTP not configured, unreachable, auth rejected, ...)."""


class EmailSender(Protocol):
    async def send_invite(self, to: str, code: str, expires_at: datetime) -> None: ...

    async def send_email_verification(self, to: str, code: str, expires_at: datetime) -> None: ...


class SmtpEmailSender:
    """smtplib is blocking, so each send runs on a worker thread. Settings
    are re-read per send: fixing secret_smtp.env takes effect without a
    restart."""

    def __init__(self, secrets_dir: Path) -> None:
        self._secrets_path = secrets_dir / "secret_smtp.env"

    async def send_invite(self, to: str, code: str, expires_at: datetime) -> None:
        await self._send(
            to,
            "Your Ember invite code",
            f"You've been invited to Ember.\n\nInvite code: {code}\n\n"
            f"It works once and expires at {expires_at:%Y-%m-%d %H:%M} UTC.",
        )

    async def send_email_verification(self, to: str, code: str, expires_at: datetime) -> None:
        await self._send(
            to,
            "Verify your Ember email",
            f"Your verification code: {code}\n\nIt expires at {expires_at:%Y-%m-%d %H:%M} UTC.",
        )

    async def _send(self, to: str, subject: str, body: str) -> None:
        config = load_env_secrets(self._secrets_path)
        host = config.get("SMTP_HOST")
        sender = config.get("MAIL_FROM_ADDRESS") or config.get("SMTP_USERNAME")
        if not host or not sender:
            raise EmailDeliveryError("Email is not configured. Set SMTP_HOST and MAIL_FROM_ADDRESS in secrets/secret_smtp.env.")

        message = EmailMessage()
        message["From"] = sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)

        await asyncio.to_thread(
            _deliver,
            message,
            host,
            int(config.get("SMTP_PORT") or 587),
            config.get("SMTP_USERNAME") or None,
            config.get("SMTP_PASSWORD") or None,
            (config.get("SMTP_USE_TLS") or "true").lower() == "true",
        )


def _deliver(
    message: EmailMessage, host: str, port: int, username: str | None, password: str | None, use_tls: bool
) -> None:
    try:
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            if use_tls:
                smtp.starttls()
            if username and password:
                smtp.login(username, password)
            smtp.send_message(message)
    except (smtplib.SMTPException, OSError) as error:
        raise EmailDeliveryError(
            "Email could not be sent. Check the SMTP settings in secrets/secret_smtp.env."
        ) from error
