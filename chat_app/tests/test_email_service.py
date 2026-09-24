from datetime import datetime, timedelta, timezone

import pytest
from flask import Flask

from src.services.email_service import (
    EmailDeliveryError,
    init_mail,
    mail,
    send_email_verification,
    send_invite_email,
)


def _build_mail_test_app(tmp_path, secrets_dir):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["MAIL_SUPPRESS_SEND"] = True
    init_mail(app, secrets_dir)
    return app


def test_init_mail_uses_configured_smtp_settings(tmp_path):
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "secret_smtp.env").write_text(
        "SMTP_HOST=smtp.example.com\n"
        "SMTP_PORT=2525\n"
        "SMTP_USERNAME=bot\n"
        "SMTP_PASSWORD=hunter2\n"
        "SMTP_USE_TLS=false\n"
        "MAIL_FROM_ADDRESS=noreply@example.com\n"
    )

    app = _build_mail_test_app(tmp_path, secrets_dir)

    assert app.config["MAIL_SERVER"] == "smtp.example.com"
    assert app.config["MAIL_PORT"] == 2525
    assert app.config["MAIL_USERNAME"] == "bot"
    assert app.config["MAIL_USE_TLS"] is False
    assert app.config["MAIL_DEFAULT_SENDER"] == "noreply@example.com"


def test_init_mail_falls_back_to_defaults_when_secrets_missing(tmp_path):
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()

    app = _build_mail_test_app(tmp_path, secrets_dir)

    assert app.config["MAIL_SERVER"] == "localhost"
    assert app.config["MAIL_USE_TLS"] is True


def test_send_invite_email_sends_message_with_code(tmp_path):
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    app = _build_mail_test_app(tmp_path, secrets_dir)

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)

    with app.app_context():
        with mail.record_messages() as outbox:
            send_invite_email("invitee@example.com", "abc123code", expires_at)

        assert len(outbox) == 1
        sent = outbox[0]
        assert sent.recipients == ["invitee@example.com"]
        assert "abc123code" in sent.body


@pytest.mark.parametrize("send", [send_invite_email, send_email_verification])
def test_send_wraps_smtp_connection_failure(tmp_path, monkeypatch, send):
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    app = _build_mail_test_app(tmp_path, secrets_dir)

    def refuse(message):
        raise ConnectionRefusedError(10061, "actively refused")

    monkeypatch.setattr(mail, "send", refuse)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)

    with app.app_context(), pytest.raises(EmailDeliveryError):
        send("someone@example.com", "abc123code", expires_at)
