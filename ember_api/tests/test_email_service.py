"""SmtpEmailSender: template bodies and the auto-generated footer."""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import patch

import pytest

from src.services.email_service import AUTO_GENERATED_NOTICE, SmtpEmailSender, render_template

EXPIRES = datetime(2026, 10, 5, 12, 30)


def _sent(tmp_path, send):
    env = tmp_path / ".env"
    env.write_text("SMTP_HOST=smtp.example.com\nMAIL_FROM_ADDRESS=ember@example.com\n", encoding="utf-8")
    with patch("src.services.email_service._deliver") as deliver:
        asyncio.run(send(SmtpEmailSender(env)))
    return deliver.call_args.args[0]


def test_invite_uses_template_and_ends_with_footer(tmp_path) -> None:
    message = _sent(tmp_path, lambda s: s.send_invite("a@x.com", "ABC123", EXPIRES))

    body = message.get_content().strip()
    assert "Invite code: ABC123" in body
    assert "2026-10-05 12:30 UTC" in body
    assert body.endswith(AUTO_GENERATED_NOTICE)


def test_verification_ends_with_footer(tmp_path) -> None:
    message = _sent(tmp_path, lambda s: s.send_email_verification("a@x.com", "999", EXPIRES))

    assert "Your verification code: 999" in message.get_content()
    assert message.get_content().strip().endswith(AUTO_GENERATED_NOTICE)


def test_missing_placeholder_raises() -> None:
    with pytest.raises(KeyError):
        render_template("invite", code="x")
