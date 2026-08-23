"""Shapes for the OTP tools.

There is no request model here, unlike the pattern's usual
contract-in/contract-out symmetry: both tools take one or two scalars,
and wrapping those in a model would only add a nesting level to the JSON
schema an MCP client has to fill in.

The result models are where the security property is visible. Read
``RequestOtpResult`` as a promise: these are all the fields the model
ever sees, and none of them is the code.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RequestOtpResult(BaseModel):
    """Deliberately has no ``code`` field, and must never grow one.

    A passcode delivered by email proves that whoever answers it can read
    that inbox. That proof is worth exactly nothing if the assistant
    asking for it could also read the code - it could then "verify"
    itself, or be talked into reciting the code to whoever asked. So the
    code goes to the mail server and nowhere else, and everything here is
    safe to show in a transcript.
    """

    otp_id: str = Field(
        description="Non-secret handle for this passcode. Pass it back to verify_otp_tool."
    )
    sent_to: str = Field(description="The address the code was emailed to.")
    expires_in_minutes: int = Field(description="How long the code stays valid.")
    message: str = Field(description="Human-readable confirmation, safe to relay verbatim.")


class VerifyOtpResult(BaseModel):
    verified: bool = Field(description="True only if the code was correct, live and unused.")
    outcome: str = Field(
        description=(
            "Machine-readable reason: verified, wrong_code, expired, "
            "too_many_attempts, already_used, or unknown_id."
        )
    )
    attempts_remaining: int | None = Field(
        default=None,
        description="Guesses left before the code locks. None when nothing can be attempted.",
    )
    message: str = Field(description="Human-readable explanation, safe to relay verbatim.")
