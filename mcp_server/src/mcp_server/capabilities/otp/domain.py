"""Sending and checking one-time passcodes - the part worth testing.

Two rules live here rather than in ``tool.py``, because a rule enforced
in the thin wrapper is a rule that a second caller silently doesn't get:

**The code never comes back.** ``request_otp`` holds the plaintext code
for exactly as long as it takes to build an email body, and returns a
result type with no field for it. That's the entire value of the
mechanism - answering the code proves you can read the inbox only if the
thing that asked can't read the code.

**The recipient must already be configured.** Otherwise this is a tool
that sends attacker-chosen text to an attacker-chosen address, from the
deployment's own mail account. That is a spam relay and a phishing
primitive, and reaching it needs no bug at all: it just needs the model
to be persuaded, which is the threat this codebase assumes throughout
(see ``infra/approvals.py``). Restricting delivery to the addresses
already in ``config.json`` costs nothing real - the only reason to send a
code somewhere is to check someone's identity against an inbox you
already trust - and it makes the tool useless to anyone who talks the
model into calling it.
"""

from __future__ import annotations

import html
from pathlib import Path

from mcp_server.capabilities.otp.contract import RequestOtpResult, VerifyOtpResult
from mcp_server.infra import otp
from mcp_server.infra.app_config import EmailConfig
from mcp_server.infra.email import send_email


_MESSAGES = {
    otp.Outcome.VERIFIED: (
        "Code verified. It has now been used and will not work a second time."
    ),
    otp.Outcome.WRONG_CODE: "That code is not correct.",
    otp.Outcome.EXPIRED: (
        "That code has expired. Request a new one - codes are only valid for a few minutes."
    ),
    otp.Outcome.TOO_MANY_ATTEMPTS: (
        "Too many incorrect attempts. This code is now locked and will be refused even if "
        "the right digits are entered. Request a new one."
    ),
    otp.Outcome.ALREADY_USED: (
        "That code has already been used. Request a new one if you need to verify again."
    ),
    otp.Outcome.UNKNOWN_ID: (
        "No passcode exists with that id. Check the otp_id returned when the code was "
        "requested, or request a new code."
    ),
}


def permitted_recipients(email_config: EmailConfig) -> list[str]:
    """Every address a code may be sent to, in the order they're offered.

    Both lists count. ``to`` is where this deployment already sends
    notifications and ``approver_emails`` is who it already trusts to
    authorize things - an address in either is one the operator has
    written down on purpose, which is the only property that matters
    here. Order is preserved and duplicates dropped so the default
    (see ``resolve_recipient``) is stable and the error message reads
    like the config file.
    """
    ordered: list[str] = []
    for address in [*email_config.approver_emails, *email_config.to]:
        if address not in ordered:
            ordered.append(address)
    return ordered


def resolve_recipient(email_config: EmailConfig, requested: str | None) -> str:
    """Map a requested address onto a configured one, or refuse.

    Comparison is case-insensitive and whitespace-trimmed: mail domains
    are case-insensitive by definition and no real mailbox distinguishes
    ``Alice@`` from ``alice@``, so matching exactly would reject the
    right address for a reason no user could see. The *configured*
    spelling is what's returned and sent to, so the allowlist decides the
    address rather than the caller's rendering of it.
    """
    allowed = permitted_recipients(email_config)
    if not allowed:
        # A missing required thing, not a malformed one.
        raise KeyError(
            "No email recipients are configured, so there is nowhere to send a passcode. "
            "Add 'email.to' (and optionally 'email.approver_emails') to config.json."
        )

    if requested is None or not requested.strip():
        # First approver: approver_emails is the list of people this
        # deployment already trusts to authorize actions, and it falls
        # back to `to` in the config loader, so this is never empty when
        # `allowed` isn't.
        return allowed[0]

    wanted = requested.strip().lower()
    for address in allowed:
        if address.strip().lower() == wanted:
            return address

    raise ValueError(
        f"Refusing to send a passcode to {requested!r}: it is not a configured recipient. "
        f"Codes can only go to addresses already listed in config.json: {', '.join(allowed)}."
    )


def build_otp_email(code: str, *, expires_in_minutes: int) -> str:
    """Everything interpolated is escaped, on the same reasoning as
    ``approvals.build_approval_email``: these values are cheap to escape
    and expensive to get wrong, and "the code is only ever digits" is a
    fact about today's ``generate_code``, not a guarantee the template
    should depend on.

    The code is spaced out and large because the reader's next act is to
    retype it, often from a phone, and a run of six identical-looking
    digits in body text is the easiest thing in an email to mistranscribe.
    """
    return f"""
    <html><body style="font-family: sans-serif; line-height: 1.5;">
      <h2>Your verification code</h2>
      <p style="font-size:32px;letter-spacing:6px;font-weight:bold;font-family:monospace;">
        {html.escape(code)}
      </p>
      <p>Enter this code to confirm it was you. It expires in {expires_in_minutes} minutes
         and can only be used once.</p>
      <p style="color:#888;font-size:12px;">
        If you did not ask for this code, you can ignore this message - nothing happens
        unless the code is entered. Do not forward it to anyone.
      </p>
    </body></html>
    """


def request_otp(
    email_config: EmailConfig,
    *,
    db_path: Path,
    recipient: str | None = None,
    ttl_minutes: int = otp.DEFAULT_TTL_MINUTES,
) -> RequestOtpResult:
    """Mint a code, email it, and return everything except the code.

    The order matters: the record is stored before the send. A stored
    code whose email failed is a dead record that expires in ten minutes;
    a sent code with no record is a person staring at digits that can
    never verify. The send raising (``infra/email.py`` deliberately
    doesn't swallow failures) propagates, so the caller learns the mail
    didn't go rather than being told to check an inbox that has nothing
    in it.
    """
    address = resolve_recipient(email_config, recipient)

    issued = otp.create(db_path, address, ttl_minutes=ttl_minutes)
    send_email(
        email_config,
        subject="Your verification code",
        body_html=build_otp_email(issued.code, expires_in_minutes=ttl_minutes),
        to=[address],
    )

    return RequestOtpResult(
        otp_id=issued.otp_id,
        sent_to=address,
        expires_in_minutes=ttl_minutes,
        # Says where to look and what to do next, and - deliberately -
        # contains no digits of the code. Anything phrased here is
        # readable by whatever asked for the code.
        message=(
            f"A one-time code has been emailed to {address}. Ask the person who received it "
            f"to read it back, then check it with verify_otp_tool using otp_id {issued.otp_id!r}. "
            f"The code is not visible here by design. It expires in {ttl_minutes} minutes and "
            f"locks after {otp.DEFAULT_MAX_ATTEMPTS} wrong attempts."
        ),
    )


def verify_otp(db_path: Path, otp_id: str, code: str) -> VerifyOtpResult:
    """Check a code and say precisely why it failed.

    A distinct message per outcome rather than one "invalid code": the
    remedies genuinely differ (retype it / request a new one / this one is
    dead), and a model relaying a single generic failure will invent the
    remedy it thinks is likeliest. The trade is that this tells whoever
    is guessing that an id exists and is live - which is why the attempt
    limit, not obscurity, is what stops the guessing.
    """
    result = otp.verify(db_path, otp_id, code.strip())
    message = _MESSAGES[result.outcome]
    if result.outcome is otp.Outcome.WRONG_CODE and result.attempts_remaining is not None:
        message = f"{message} {result.attempts_remaining} attempt(s) left before it locks."

    return VerifyOtpResult(
        verified=result.verified,
        outcome=result.outcome.value,
        attempts_remaining=result.attempts_remaining,
        message=message,
    )
