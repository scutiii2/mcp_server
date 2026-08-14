"""Tests for the OTP capability's domain logic.

Two properties carry the whole capability, and both are the kind that
still "work" when broken: the code must reach the inbox and nothing else,
and a code may only be sent to an address the operator already listed.
The SQLite store is real (``tmp_path``); ``send_email`` is patched, so
nothing touches the network and the message that would have been sent is
inspectable.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest

from mcp_server.capabilities.otp import domain
from mcp_server.infra import otp
from mcp_server.infra.app_config import EmailConfig


EMAIL = EmailConfig(
    smtp_server="smtp.example.com",
    smtp_port=587,
    from_address="notifications@example.com",
    password="pw",
    to=["team@example.com"],
    approver_emails=["boss@example.com"],
)


def _request(tmp_path: Path, recipient: str | None = None, config: EmailConfig = EMAIL, **kwargs):
    with patch("mcp_server.capabilities.otp.domain.send_email") as mock_send:
        result = domain.request_otp(
            config, db_path=tmp_path / "otp.db", recipient=recipient, **kwargs
        )
    return result, mock_send


def _code_from(mock_send) -> str:
    """The code exists only in the email body - which is the point, and
    also the only way a test can get at it."""
    body = mock_send.call_args.kwargs["body_html"]
    match = re.search(r"\b\d{6}\b", body)
    assert match, f"no six-digit code in the email body: {body!r}"
    return match.group(0)


# --- the code must not come back ----------------------------------------


def test_request_result_does_not_contain_the_code(tmp_path: Path):
    """The entire security property. A passcode emailed to someone proves
    they can read that inbox only if the model that asked for it cannot
    read the code - otherwise it can verify itself, or be talked into
    reciting the code to whoever is asking."""
    result, mock_send = _request(tmp_path)
    code = _code_from(mock_send)

    serialized = result.model_dump_json()

    assert code not in serialized
    assert "code" not in result.model_dump()


def test_the_emailed_code_is_the_one_that_verifies(tmp_path: Path):
    """The flip side: the code must actually reach the inbox. A result
    that leaks nothing is easy to achieve by sending nothing usable."""
    result, mock_send = _request(tmp_path)

    verified = domain.verify_otp(tmp_path / "otp.db", result.otp_id, _code_from(mock_send))

    assert verified.verified is True


def test_the_message_tells_the_caller_what_to_do_without_the_code(tmp_path: Path):
    result, mock_send = _request(tmp_path)

    assert result.otp_id in result.message
    assert "boss@example.com" in result.message
    assert _code_from(mock_send) not in result.message


# --- recipient allowlist ------------------------------------------------


def test_an_unconfigured_address_is_refused(tmp_path: Path):
    """Without this the tool is a mail-sending primitive pointed anywhere
    - a prompt-injected model could send attacker-written text from the
    deployment's own account. Reaching that needs no bug, only
    persuasion."""
    with pytest.raises(ValueError, match="not a configured recipient"):
        _request(tmp_path, recipient="attacker@evil.example")


def test_the_refusal_lists_the_permitted_addresses(tmp_path: Path):
    """The caller is usually a model that guessed. Naming what it could
    have said is the difference between a retry and a loop."""
    with pytest.raises(ValueError) as error:
        _request(tmp_path, recipient="attacker@evil.example")

    assert "boss@example.com" in str(error.value)
    assert "team@example.com" in str(error.value)


def test_a_refused_recipient_sends_nothing_and_stores_nothing(tmp_path: Path):
    """The check has to come before the side effects, or the refusal is
    only cosmetic."""
    with patch("mcp_server.capabilities.otp.domain.send_email") as mock_send:
        with pytest.raises(ValueError):
            domain.request_otp(
                EMAIL, db_path=tmp_path / "otp.db", recipient="attacker@evil.example"
            )

    assert mock_send.call_count == 0
    assert not (tmp_path / "otp.db").exists()


def test_an_address_from_the_general_to_list_is_allowed(tmp_path: Path):
    """Both lists are addresses the operator wrote down on purpose, which
    is the only property the allowlist cares about."""
    result, mock_send = _request(tmp_path, recipient="team@example.com")

    assert result.sent_to == "team@example.com"
    assert mock_send.call_args.kwargs["to"] == ["team@example.com"]


def test_matching_ignores_case_and_surrounding_space(tmp_path: Path):
    """Mail domains are case-insensitive, so rejecting "Boss@" would be a
    refusal no user could explain. The configured spelling is what gets
    sent to."""
    result, _ = _request(tmp_path, recipient="  BOSS@Example.com ")

    assert result.sent_to == "boss@example.com"


def test_no_recipient_defaults_to_the_first_approver(tmp_path: Path):
    result, mock_send = _request(tmp_path)

    assert result.sent_to == "boss@example.com"
    assert mock_send.call_args.kwargs["to"] == ["boss@example.com"]


def test_no_configured_recipients_at_all_is_a_key_error(tmp_path: Path):
    """Absent, not malformed - the codebase's KeyError/ValueError split."""
    empty = EmailConfig(
        smtp_server="smtp.example.com",
        smtp_port=587,
        from_address="notifications@example.com",
        to=[],
        approver_emails=[],
    )

    with pytest.raises(KeyError, match="No email recipients are configured"):
        _request(tmp_path, config=empty)


# --- the email itself ---------------------------------------------------


def test_email_body_escapes_what_it_interpolates(tmp_path: Path):
    """Escaping is a property of the template, not of today's alphabet.
    "The code is always digits" is a fact about one function that a
    template two files away must not depend on."""
    body = domain.build_otp_email("<script>x</script>", expires_in_minutes=10)

    assert "<script>" not in body
    assert "&lt;script&gt;" in body


def test_email_states_the_expiry(tmp_path: Path):
    _, mock_send = _request(tmp_path, ttl_minutes=7)

    assert "7 minutes" in mock_send.call_args.kwargs["body_html"]


# --- verification messages ----------------------------------------------


def test_each_failure_reason_gets_its_own_message(tmp_path: Path):
    """A single "invalid code" would force a model to guess the remedy,
    and the remedies genuinely differ: retype it, request a new one, or
    give up on this one entirely."""
    db = tmp_path / "otp.db"
    issued = otp.create(db, "boss@example.com", max_attempts=2)
    wrong = domain.verify_otp(db, issued.otp_id, "000000")
    burned = domain.verify_otp(db, issued.otp_id, "000000")
    unknown = domain.verify_otp(db, "no-such-id", issued.code)
    expired = domain.verify_otp(
        db, otp.create(db, "boss@example.com", ttl_minutes=-1).otp_id, "000000"
    )

    outcomes = {wrong.outcome, burned.outcome, unknown.outcome, expired.outcome}
    messages = {wrong.message, burned.message, unknown.message, expired.message}

    assert outcomes == {"wrong_code", "too_many_attempts", "unknown_id", "expired"}
    assert len(messages) == 4
    assert all(result.verified is False for result in (wrong, burned, unknown, expired))


def test_wrong_code_message_says_how_many_attempts_are_left(tmp_path: Path):
    db = tmp_path / "otp.db"
    issued = otp.create(db, "boss@example.com")

    result = domain.verify_otp(db, issued.otp_id, "000000")

    assert result.attempts_remaining == otp.DEFAULT_MAX_ATTEMPTS - 1
    assert f"{otp.DEFAULT_MAX_ATTEMPTS - 1} attempt" in result.message


def test_a_pasted_code_with_stray_whitespace_still_verifies(tmp_path: Path):
    """People copy the code out of an email and pick up a space with it.
    Rejecting that spends one of five attempts on a code that was right."""
    result, mock_send = _request(tmp_path)

    verified = domain.verify_otp(tmp_path / "otp.db", result.otp_id, f" {_code_from(mock_send)} ")

    assert verified.verified is True
