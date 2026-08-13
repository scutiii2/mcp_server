"""Tests for infra/email.py.

``smtplib.SMTP`` is mocked - these assert on what would be sent and to
whom, not on real SMTP behavior. Note the mock stands in for the context
manager, so the assertions read off ``__enter__``'s return value.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from mcp_server.infra.app_config import EmailConfig
from mcp_server.infra.email import send_email


CONFIG = EmailConfig(
    smtp_server="smtp.example.com",
    smtp_port=587,
    from_address="notifications@example.com",
    password="changeme",
    to=["team@example.com"],
)


def _smtp_mock():
    """Returns (patcher_target_mock, the server object callers interact with)."""
    smtp = MagicMock()
    server = smtp.return_value.__enter__.return_value
    return smtp, server


def test_send_email_uses_the_configured_recipients_by_default():
    smtp, server = _smtp_mock()

    with patch("smtplib.SMTP", smtp):
        send_email(CONFIG, "Subject", "<p>Body</p>")

    smtp.assert_called_once_with("smtp.example.com", 587, timeout=15)
    server.starttls.assert_called_once()
    server.login.assert_called_once_with("notifications@example.com", "changeme")
    sender, recipients, _body = server.sendmail.call_args.args
    assert sender == "notifications@example.com"
    assert recipients == ["team@example.com"]


def test_to_override_replaces_rather_than_extends_the_config_list():
    """An override targets a different audience entirely - an approver, or
    the one person a message is about. Appending to the standing list
    instead would quietly CC everyone on it."""
    smtp, server = _smtp_mock()

    with patch("smtplib.SMTP", smtp):
        send_email(CONFIG, "Subject", "<p>Body</p>", to=["approver@example.com"])

    _sender, recipients, _body = server.sendmail.call_args.args
    assert recipients == ["approver@example.com"]


def test_subject_and_html_body_reach_the_message():
    smtp, server = _smtp_mock()

    with patch("smtplib.SMTP", smtp):
        send_email(CONFIG, "Deploy finished", "<h1>Done</h1>")

    _sender, _recipients, body = server.sendmail.call_args.args
    assert "Subject: Deploy finished" in body
    assert "<h1>Done</h1>" in body


def test_empty_recipient_list_raises_instead_of_silently_sending_nothing():
    smtp, _server = _smtp_mock()
    config = EmailConfig(**{**CONFIG.__dict__, "to": []})

    with patch("smtplib.SMTP", smtp):
        with pytest.raises(ValueError, match="No recipients"):
            send_email(config, "Subject", "<p>Body</p>")

    smtp.assert_not_called()
