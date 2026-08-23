from pathlib import Path

from flask import Flask
from flask_mail import Mail, Message

from src.utils.config_loader import load_env_secrets

mail = Mail()


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
    mail.send(message)
