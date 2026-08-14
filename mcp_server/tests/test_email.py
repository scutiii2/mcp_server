"""Tests for infra/email.py.

``smtplib.SMTP`` is mocked - these assert on what would be sent and to
whom, not on real SMTP behavior. Note the mock stands in for the context
manager, so the assertions read off ``__enter__``'s return value.
"""

from __future__ import annotations

from email import message_from_string
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


def _sent_message(server):
    """The message as the receiving end would parse it, not as a raw string."""
    _sender, _recipients, body = server.sendmail.call_args.args
    return message_from_string(body)


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


# --- transport ---------------------------------------------------------
# The sending account is usually a consumer provider, and they disagree
# about how the connection is protected. Each mode has to reach a
# different smtplib entry point, and picking the wrong one doesn't
# degrade - it fails to connect or, worse, sends the password in clear.


def test_starttls_mode_upgrades_a_plain_connection():
    smtp, server = _smtp_mock()
    config = EmailConfig(**{**CONFIG.__dict__, "security": "starttls"})

    with patch("smtplib.SMTP", smtp), patch("smtplib.SMTP_SSL") as smtp_ssl:
        send_email(config, "Subject", "<p>Body</p>")

    smtp.assert_called_once_with("smtp.example.com", 587, timeout=15)
    smtp_ssl.assert_not_called()
    server.starttls.assert_called_once()


def test_ssl_mode_uses_smtp_ssl_and_never_calls_starttls():
    """SMTP_SSL wraps the socket before the greeting, so starttls() on it
    is an error rather than a redundant no-op - the two modes are separate
    code paths, not a flag."""
    smtp_ssl, server = _smtp_mock()
    config = EmailConfig(**{**CONFIG.__dict__, "smtp_port": 465, "security": "ssl"})

    with patch("smtplib.SMTP_SSL", smtp_ssl), patch("smtplib.SMTP") as plain:
        send_email(config, "Subject", "<p>Body</p>")

    smtp_ssl.assert_called_once_with("smtp.example.com", 465, timeout=15)
    plain.assert_not_called()
    server.starttls.assert_not_called()
    server.sendmail.assert_called_once()


def test_none_mode_sends_without_any_tls():
    """For a relay on your own network that offers no TLS at all. Calling
    starttls() there aborts the send, which is why this can't just be
    starttls-and-hope."""
    smtp, server = _smtp_mock()
    config = EmailConfig(**{**CONFIG.__dict__, "security": "none", "password": ""})

    with patch("smtplib.SMTP", smtp), patch("smtplib.SMTP_SSL") as smtp_ssl:
        send_email(config, "Subject", "<p>Body</p>")

    smtp_ssl.assert_not_called()
    server.starttls.assert_not_called()
    server.sendmail.assert_called_once()


def test_empty_password_skips_authentication_entirely():
    """A relay that authorizes by source address has no AUTH extension,
    and offering credentials to it is an error response, not a harmless
    extra step - so an absent password must mean 'do not log in'."""
    smtp, server = _smtp_mock()
    config = EmailConfig(**{**CONFIG.__dict__, "password": ""})

    with patch("smtplib.SMTP", smtp):
        send_email(config, "Subject", "<p>Body</p>")

    server.login.assert_not_called()
    server.sendmail.assert_called_once()


def test_unknown_security_mode_raises_before_opening_a_connection():
    """No permissive fallback: an unrecognized mode must not become a
    plaintext session that then offers the password to a server."""
    smtp, _server = _smtp_mock()
    config = EmailConfig(**{**CONFIG.__dict__, "security": "tls"})

    with patch("smtplib.SMTP", smtp), patch("smtplib.SMTP_SSL") as smtp_ssl:
        with pytest.raises(ValueError, match="security mode"):
            send_email(config, "Subject", "<p>Body</p>")

    smtp.assert_not_called()
    smtp_ssl.assert_not_called()


# --- message shape -----------------------------------------------------


def test_plain_text_part_comes_before_the_html_part():
    """RFC 2046 makes the LAST part of a multipart/alternative the
    preferred one, so this order is what makes clients still render the
    HTML while the text part exists for the ones that can't."""
    smtp, server = _smtp_mock()

    with patch("smtplib.SMTP", smtp):
        send_email(CONFIG, "Subject", "<p>Body</p>")

    message = _sent_message(server)
    assert message.get_content_subtype() == "alternative"
    assert [part.get_content_type() for part in message.get_payload()] == ["text/plain", "text/html"]


def test_plain_text_is_derived_from_the_html_without_the_caller_asking():
    """Existing call sites pass HTML only, and an HTML-only body is a spam
    signal at the providers these approval links are sent to - so the text
    part cannot depend on callers remembering to supply one."""
    smtp, server = _smtp_mock()

    with patch("smtplib.SMTP", smtp):
        send_email(CONFIG, "Subject", "<h2>Approval needed</h2><p>Restart <b>db</b>?</p>")

    text = _sent_message(server).get_payload()[0].get_payload()
    assert "Approval needed" in text
    assert "Restart db?" in text
    assert "<" not in text


def test_derived_text_keeps_link_targets():
    """The whole point of these messages is a URL that lives in an href.
    A stripper that kept only the anchor text would produce a plain part
    telling the reader to click something that isn't there."""
    smtp, server = _smtp_mock()
    html = '<p><a href="https://example.com/approvals/tok3n">Review this request</a></p>'

    with patch("smtplib.SMTP", smtp):
        send_email(CONFIG, "Subject", html)

    text = _sent_message(server).get_payload()[0].get_payload()
    assert "https://example.com/approvals/tok3n" in text


def test_body_text_overrides_the_derived_version():
    smtp, server = _smtp_mock()

    with patch("smtplib.SMTP", smtp):
        send_email(CONFIG, "Subject", "<p>Body</p>", body_text="Handwritten")

    parts = _sent_message(server).get_payload()
    assert parts[0].get_payload().strip() == "Handwritten"
    assert "<p>Body</p>" in parts[1].get_payload()


def test_date_and_message_id_headers_are_set():
    """smtplib adds neither, and receivers penalize or reject a message
    without them - which for an approval link means the action silently
    never gets approved."""
    smtp, server = _smtp_mock()

    with patch("smtplib.SMTP", smtp):
        send_email(CONFIG, "Subject", "<p>Body</p>")

    message = _sent_message(server)
    assert message["Date"]
    # The domain must match From: make_msgid()'s default is the local
    # hostname, which leaks internal naming and reads as forged.
    assert message["Message-ID"].endswith("@example.com>")
