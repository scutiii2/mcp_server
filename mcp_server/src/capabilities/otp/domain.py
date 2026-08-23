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

``email.allowed_recipient_domains`` widens that second rule, on purpose
and only as far as the operator writes down: a deployment that verifies
its own staff needs to send a code to a person who wasn't listed
individually, and the domain is the thing that actually distinguishes
"someone at the company" from "the attacker's mailbox". It is opt-in and
exact-match, and an absent key leaves the strict address-only behavior in
place - a spam relay that switches itself on when a config key is missing
would be worse than no allowlist at all, because it would look configured.
"""

from __future__ import annotations

import html
from pathlib import Path

from src.capabilities.otp.contract import RequestOtpResult, VerifyOtpResult
from src.infra import otp
from src.infra.app_config import EmailConfig, normalize_recipient_domain
from src.infra.email import send_email


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


def permitted_domains(email_config: EmailConfig) -> list[str]:
    """Domains any address may be at, in comparison form.

    Normalized here as well as in the config loader because an
    ``EmailConfig`` reaches this function from tests and hand-built setups
    that never touched the loader, and an allowlist that silently fails to
    match ``"Example.COM "`` is worse than one that refuses it - the
    operator sees a working config and a tool that refuses everyone.
    Duplicates are dropped so the refusal message reads like the config
    file rather than like a bug.
    """
    ordered: list[str] = []
    for entry in email_config.allowed_recipient_domains:
        domain = normalize_recipient_domain(entry)
        if domain and domain not in ordered:
            ordered.append(domain)
    return ordered


def _domain_of(address: str) -> str | None:
    """The domain half of ``address``, or None if it isn't an address.

    Returns None rather than raising because the caller is the only place
    that can phrase a refusal naming what *was* permitted, and a refusal
    that doesn't is a caller (usually a model) retrying the same guess.

    Exactly one ``@`` is demanded before anything is split off, and that
    order is the point. ``victim@allowed.example@evil.example`` is a
    single string that two reasonable one-liners disagree about:
    ``rpartition("@")`` reads its domain as ``evil.example`` and
    ``partition("@")`` as ``allowed.example@evil.example``. One of those
    hands an attacker delivery at a domain nobody allowed, and which one
    you got depends on a character nobody reviewing the line would look
    twice at. Counting first means the ambiguous address is refused
    outright and never reaches a split at all.

    Whitespace and control characters are refused for a different reason:
    this string is joined into the message's ``To`` header by
    ``infra/email.py``, and a header value containing a newline is header
    injection - extra recipients, a forged subject - which was
    unreachable while every recipient came from config.json and is not
    once the caller supplies one.
    """
    if any(character.isspace() or ord(character) < 32 for character in address):
        return None
    if address.count("@") != 1:
        return None
    local_part, _, domain = address.partition("@")
    if not local_part or not domain:
        return None
    # Only the domain is lowercased. The local part is left exactly as
    # given: it is the receiving server's to interpret, and RFC 5321 lets
    # it be case-sensitive even though essentially no real mailbox is.
    return domain.lower()


def _permitted_summary(allowed: list[str], domains: list[str]) -> str:
    """What a refused caller could have said instead."""
    if not domains:
        return f"Codes can only go to addresses already listed in config.json: {', '.join(allowed)}."
    return (
        f"Codes can only go to addresses already listed in config.json "
        f"({', '.join(allowed)}), or to any address at these domains: {', '.join(domains)}."
    )


def resolve_recipient(email_config: EmailConfig, requested: str | None) -> str:
    """Map a requested address onto a permitted one, or refuse.

    Two ways in, checked in this order. An exact match against a
    configured address wins first and returns the *configured* spelling,
    so a deployment that lists no domains behaves exactly as it did before
    this function knew about domains. Failing that, the address is allowed
    if its domain is one the operator listed, and then the caller's own
    spelling is what gets sent to - there is no configured spelling to
    prefer, which is the entire point of the domain form.

    Comparison is case-insensitive and whitespace-trimmed: mail domains
    are case-insensitive by definition and no real mailbox distinguishes
    ``Alice@`` from ``alice@``, so matching exactly would reject the
    right address for a reason no user could see.

    Domain matching is equality, never suffix matching. ``example.com``
    accepts neither ``evil-example.com`` nor ``mail.example.com``. The
    obvious shorthand for "and subdomains" is
    ``domain.endswith("example.com")``, which also accepts
    ``notexample.com`` - a domain an attacker can register this afternoon,
    from a bug that reviews cleanly. Guarding that correctly means
    ``domain == d or domain.endswith("." + d)``, and it buys an operator
    nothing they can't get by listing ``mail.example.com`` on its own
    line, so the wildcard doesn't exist here.
    """
    allowed = permitted_recipients(email_config)
    domains = permitted_domains(email_config)
    if not allowed and not domains:
        # A missing required thing, not a malformed one.
        raise KeyError(
            "No email recipients are configured, so there is nowhere to send a passcode. "
            "Add 'email.to' (and optionally 'email.approver_emails') to config.json."
        )

    if requested is None or not requested.strip():
        if not allowed:
            # Domains alone can't supply a default: they say which
            # addresses are acceptable, not which person to ask.
            raise KeyError(
                "No email recipients are configured, so there is no default address for a "
                "passcode. Add 'email.to' to config.json, or name a recipient explicitly."
            )
        # First approver: approver_emails is the list of people this
        # deployment already trusts to authorize actions, and it falls
        # back to `to` in the config loader, so this is never empty when
        # `allowed` isn't.
        return allowed[0]

    candidate = requested.strip()
    wanted = candidate.lower()
    for address in allowed:
        if address.strip().lower() == wanted:
            return address

    if domains:
        domain = _domain_of(candidate)
        if domain is None:
            raise ValueError(
                f"Refusing to send a passcode to {requested!r}: that is not a usable email "
                f"address - it needs exactly one '@', a mailbox name before it, a domain "
                f"after it, and no spaces. {_permitted_summary(allowed, domains)}"
            )
        if domain in domains:
            return candidate

    raise ValueError(
        f"Refusing to send a passcode to {requested!r}: it is not a configured recipient. "
        f"{_permitted_summary(allowed, domains)}"
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

    try:
        issued = otp.create(db_path, address, ttl_minutes=ttl_minutes)
    except otp.RateLimited as limited:
        # Raised, not returned as a RequestOtpResult carrying an apology.
        # Every field of that type is a statement that a code is in an
        # inbox, and a model handed a success object reads the first two
        # and tells someone to go and look for mail that was never sent.
        #
        # Phrased from `retry_after_seconds` rather than by relaying
        # infra's own sentence: the attribute is the interface the two
        # modules agreed on, and wording is not. The original is kept as
        # the cause, so a log still shows which ceiling was hit.
        raise RuntimeError(
            f"No passcode was sent: too many have been requested recently. Wait "
            f"{limited.retry_after_seconds} seconds before asking for another code."
        ) from limited


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
