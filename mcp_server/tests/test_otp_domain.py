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


# --- recipient domain allowlist -----------------------------------------
# The opt-in widening: a caller may name its own address, provided that
# address is at a domain the operator listed. Everything here is about
# the boundary of that permission, because a domain allowlist that is one
# character too generous is a mail relay pointed at an attacker's domain.


DOMAIN_EMAIL = EmailConfig(
    smtp_server="smtp.example.com",
    smtp_port=587,
    from_address="notifications@example.com",
    password="pw",
    to=["team@example.com"],
    approver_emails=["boss@example.com"],
    allowed_recipient_domains=["staff.example"],
)


def test_an_address_at_an_allowed_domain_is_accepted(tmp_path: Path):
    """The whole feature: a person who was never listed individually can
    still receive a code, because their domain says who they are."""
    result, mock_send = _request(tmp_path, recipient="alice@staff.example", config=DOMAIN_EMAIL)

    assert result.sent_to == "alice@staff.example"
    assert mock_send.call_args.kwargs["to"] == ["alice@staff.example"]


def test_configured_addresses_still_work_when_domains_are_listed(tmp_path: Path):
    """Adding domains widens the allowlist, it doesn't replace it -
    'boss@example.com' is at no listed domain and must still be reachable,
    or every existing deployment breaks on upgrade."""
    result, _ = _request(tmp_path, recipient="boss@example.com", config=DOMAIN_EMAIL)

    assert result.sent_to == "boss@example.com"


def test_no_domains_configured_allows_nothing_extra(tmp_path: Path):
    """The inversion that would matter most: an empty domain list must mean
    "no domains", not "any domain". Read as a wildcard, this tool becomes a
    way to mail attacker-written text from the deployment's own account,
    and every other test in this file still passes."""
    with pytest.raises(ValueError, match="not a configured recipient"):
        _request(tmp_path, recipient="alice@staff.example", config=EMAIL)


def test_a_lookalike_domain_is_refused(tmp_path: Path):
    """'evil-staff.example' ends with 'staff.example'. Matching domains
    with endswith() accepts it, reads correctly to a reviewer, and hands
    delivery to a domain anyone can register this afternoon."""
    with pytest.raises(ValueError, match="not a configured recipient"):
        _request(tmp_path, recipient="alice@evil-staff.example", config=DOMAIN_EMAIL)


def test_a_subdomain_is_refused(tmp_path: Path):
    """Exact match only. Subdomains are frequently delegated to somebody
    else, so 'staff.example' is not a statement about 'mail.staff.example'
    - an operator who means that can list it on its own line."""
    with pytest.raises(ValueError, match="not a configured recipient"):
        _request(tmp_path, recipient="alice@mail.staff.example", config=DOMAIN_EMAIL)


def test_a_parent_domain_is_refused(tmp_path: Path):
    """The other direction of the same rule."""
    with pytest.raises(ValueError, match="not a configured recipient"):
        _request(tmp_path, recipient="alice@example", config=DOMAIN_EMAIL)


def test_a_second_at_sign_cannot_smuggle_in_a_domain(tmp_path: Path):
    """'alice@staff.example@evil.example' is one address whose domain is
    'evil.example'. Naive splitting reads the allowed domain out of the
    middle of it and delivers to the attacker's server - so the address is
    refused before anything is split off it."""
    with pytest.raises(ValueError, match="not a usable email address"):
        _request(tmp_path, recipient="alice@staff.example@evil.example", config=DOMAIN_EMAIL)


def test_an_address_with_no_local_part_or_no_domain_is_refused(tmp_path: Path):
    """Both halves have to exist. '@staff.example' has a permitted domain
    and no mailbox, which is not an address anyone can receive at."""
    for malformed in ("@staff.example", "alice@", "alice", "@"):
        with pytest.raises(ValueError, match="not a usable email address"):
            _request(tmp_path, recipient=malformed, config=DOMAIN_EMAIL)


def test_an_address_containing_a_newline_is_refused(tmp_path: Path):
    """The recipient is joined into the message's To header. A newline in
    it is header injection - extra recipients, a forged subject - and this
    string only became caller-controlled when domains were allowed."""
    with pytest.raises(ValueError, match="not a usable email address"):
        _request(
            tmp_path,
            recipient="alice@staff.example\nBcc: everyone@evil.example",
            config=DOMAIN_EMAIL,
        )


def test_a_refused_domain_sends_nothing_and_stores_nothing(tmp_path: Path):
    """Same property as the address allowlist: the check is worthless if it
    happens after the mail goes out."""
    with patch("mcp_server.capabilities.otp.domain.send_email") as mock_send:
        with pytest.raises(ValueError):
            domain.request_otp(
                DOMAIN_EMAIL, db_path=tmp_path / "otp.db", recipient="alice@evil.example"
            )

    assert mock_send.call_count == 0
    assert not (tmp_path / "otp.db").exists()


def test_domain_matching_ignores_case_and_surrounding_space(tmp_path: Path):
    """Mail domains are case-insensitive, and the caller's rendering of one
    is not a reason to refuse a person their code."""
    result, _ = _request(tmp_path, recipient="  Alice@STAFF.Example  ", config=DOMAIN_EMAIL)

    assert result.sent_to == "Alice@STAFF.Example"


def test_a_configured_domain_written_with_an_at_or_dot_still_matches(tmp_path: Path):
    """Operators write "@example.com" and ".example.com" when asked for a
    domain. Both are unmistakable, and an EmailConfig can be built without
    passing through the config loader that normalizes them."""
    written_loosely = EmailConfig(
        smtp_server="smtp.example.com",
        smtp_port=587,
        from_address="notifications@example.com",
        to=["team@example.com"],
        approver_emails=["boss@example.com"],
        allowed_recipient_domains=["@Staff.Example ", ".other.example"],
    )

    assert domain.resolve_recipient(written_loosely, "a@staff.example") == "a@staff.example"
    assert domain.resolve_recipient(written_loosely, "b@other.example") == "b@other.example"


def test_the_refusal_names_the_allowed_domains_as_well_as_the_addresses(tmp_path: Path):
    """The caller is usually a model that guessed an address. Telling it
    only that the guess was wrong makes it guess again; telling it the
    domain it may use makes the next attempt the right one."""
    with pytest.raises(ValueError) as error:
        _request(tmp_path, recipient="alice@evil.example", config=DOMAIN_EMAIL)

    message = str(error.value)
    assert "boss@example.com" in message
    assert "team@example.com" in message
    assert "staff.example" in message


# --- rate limiting ------------------------------------------------------


def _rate_limited() -> otp.RateLimited:
    return otp.RateLimited(
        "Too many codes requested.", retry_after_seconds=42, limit="per_recipient"
    )


def test_a_rate_limited_request_says_how_long_to_wait(tmp_path: Path):
    """infra/otp.py refuses to mint a code when a limit is hit. Reporting
    that as a RequestOtpResult would be a success object saying a code is
    in an inbox when none was sent, so it has to raise - and the wait has
    to be stated in the message, or the caller (a model, with no clock)
    retries straight into the same refusal."""
    with patch("mcp_server.infra.otp.create", side_effect=_rate_limited()):
        with pytest.raises(RuntimeError, match="42 seconds"):
            _request(tmp_path)


def test_a_rate_limited_request_sends_no_email(tmp_path: Path):
    """A limit that still sends mail limits nothing that matters."""
    with patch("mcp_server.infra.otp.create", side_effect=_rate_limited()):
        with patch("mcp_server.capabilities.otp.domain.send_email") as mock_send:
            with pytest.raises(RuntimeError):
                domain.request_otp(EMAIL, db_path=tmp_path / "otp.db")

    assert mock_send.call_count == 0


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
