"""The @mcp.tool() wrappers - thin on purpose.

Load config, call the domain function, return its result. Both the
recipient allowlist and the never-return-the-code rule live in
``domain.py``, not here, so nothing depends on this file staying honest.

Not gated behind ``infra/approvals.py``, unlike an irreversible action.
Sending a code to an address the operator already configured is
reversible by ignoring the email, and an approval step would defeat the
purpose - the whole flow exists so a human can confirm something without
one person having to hand-approve every attempt.
"""

from __future__ import annotations

from src.capabilities.otp import domain
from src.capabilities.otp.contract import RequestOtpResult, VerifyOtpResult
from src.commands import command
from src.config import settings
from src.infra.app_config import load_email_config
from src.server import mcp
from src.tool_response import respond


@command(name="get_otp", description="generate otp")
@mcp.tool()
def request_otp_tool(recipient: str | None = None) -> RequestOtpResult:
    """Email a one-time passcode to a configured address, to confirm someone's identity.

    Use this when you need proof that the person you are talking to can
    read a particular inbox. The code is sent by email and is NOT
    returned to you - ask the recipient to read it back, then check it
    with `verify_otp_tool`.

    `recipient` must be an address this server's email configuration
    permits: one of the addresses listed there, or - if the deployment
    allows any recipient domains - any address at one of those domains.
    Anything else is refused, and the refusal names what would have been
    accepted. Omit it to use the first configured approver.
    """
    email_config = load_email_config(settings.email_config_path)
    return respond(domain.request_otp(email_config, db_path=settings.otp_path, recipient=recipient))


@command(name="verify_otp", description="verify otp")
@mcp.tool()
def verify_otp_tool(otp_id: str, code: str) -> VerifyOtpResult:
    """Check a one-time passcode someone read back to you.

    `otp_id` is the handle returned by `request_otp_tool`; `code` is what
    the person supplied. Each code works once, expires within minutes,
    and locks after a few wrong attempts - the `outcome` field says which
    of those happened so you can tell someone whether to retry or ask for
    a new code.
    """
    return respond(domain.verify_otp(settings.otp_path, otp_id, code))
