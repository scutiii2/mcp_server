"""Outgoing email for invite and verification codes.

Routes depend on the EmailSender protocol; the app wires SmtpEmailSender
(SMTP_* in .env), tests wire a fake.
"""

from __future__ import annotations

import asyncio
import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from string import Template
from typing import Protocol

from src.utils.config_loader import load_env_secrets


TEMPLATE_DIR = Path(__file__).parent / "email_templates"

# Appended to every message so a recipient never mistakes it for a mailbox
# somebody reads.
AUTO_GENERATED_NOTICE = "This is an auto-generated message. Do not reply."


def render_template(name: str, **values: str) -> str:
    """Fill ``email_templates/<name>.txt``. ``KeyError`` on a missing value."""
    source = (TEMPLATE_DIR / f"{name}.txt").read_text(encoding="utf-8")
    return Template(source).substitute(values).strip()


class EmailDeliveryError(RuntimeError):
    """Sending failed (SMTP not configured, unreachable, auth rejected, ...)."""


class EmailSender(Protocol):
    async def send_invite(self, to: str, code: str, expires_at: datetime) -> None: ...

    async def send_email_verification(self, to: str, code: str, expires_at: datetime) -> None: ...


class SmtpEmailSender:
    """smtplib is blocking, so each send runs on a worker thread. Settings
    are re-read per send: fixing .env takes effect without a
    restart."""

    def __init__(self, env_path: Path) -> None:
        self._env_path = env_path

    async def send_invite(self, to: str, code: str, expires_at: datetime) -> None:
        await self._send(
            to,
            "Your Ember invite code",
            render_template("invite", code=code, expires_at=f"{expires_at:%Y-%m-%d %H:%M}"),
        )

    async def send_email_verification(self, to: str, code: str, expires_at: datetime) -> None:
        await self._send(
            to,
            "Verify your Ember email",
            render_template("email_verification", code=code, expires_at=f"{expires_at:%Y-%m-%d %H:%M}"),
        )

    async def _send(self, to: str, subject: str, body: str) -> None:
        config = load_env_secrets(self._env_path)
        host = config.get("SMTP_HOST")
        sender = config.get("MAIL_FROM_ADDRESS") or config.get("SMTP_USERNAME")
        if not host or not sender:
            raise EmailDeliveryError("Email is not configured. Set SMTP_HOST and MAIL_FROM_ADDRESS in .env.")

        message = EmailMessage()
        message["From"] = sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(f"{body}\n\n--\n{AUTO_GENERATED_NOTICE}")

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
            "Email could not be sent. Check the SMTP settings in .env."
        ) from error
