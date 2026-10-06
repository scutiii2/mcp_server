"""MCP tool wrappers for the generator capability - thin on purpose.
No config: call the domain function, return its result. Generated values
come back in the result and are neither stored nor logged."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from src.capabilities.generator import domain
from src.capabilities.generator.contract import (
    PassphraseResult,
    PasswordResult,
    PinResult,
    TotpCodeResult,
    TotpSecretResult,
)
from src.commands import command
from src.offload import offload
from src.server import mcp


@command(name="password", description="Generate a random password")
@mcp.tool(meta={"keywords": ["generator", "password", "random", "secure", "generate"], "display_label": "Generating password"})
@offload
def tool_gen_generatePassword(
    length: Annotated[int, Field(description="Password length in characters.", ge=8, le=128)] = 20,
    use_upper: Annotated[bool, Field(description="Include A-Z.")] = True,
    use_lower: Annotated[bool, Field(description="Include a-z.")] = True,
    use_digits: Annotated[bool, Field(description="Include 0-9.")] = True,
    use_symbols: Annotated[bool, Field(description="Include symbols such as ! @ # $ %.")] = True,
    exclude_ambiguous: Annotated[bool, Field(description="Leave out look-alike characters (I l 1 O 0 o).")] = False,
) -> PasswordResult:
    """Generate a cryptographically random password with at least one character
    of every chosen type. Deterministic rules, random output; the value is
    returned once and not stored. Tell the person to copy it now."""
    return domain.generate_password(length, use_upper, use_lower, use_digits, use_symbols, exclude_ambiguous)


@command(name="passphrase", description="Generate a random passphrase")
@mcp.tool(meta={"keywords": ["generator", "passphrase", "words", "diceware", "random", "generate"], "display_label": "Generating passphrase"})
@offload
def tool_gen_generatePassphrase(
    words: Annotated[int, Field(description="How many words.", ge=3, le=12)] = 6,
    separator: Annotated[str, Field(description="Text between words (up to 3 characters).", max_length=3)] = "-",
    capitalize: Annotated[bool, Field(description="Capitalise each word.")] = False,
    add_number: Annotated[bool, Field(description="Append one random digit.")] = False,
) -> PassphraseResult:
    """Generate a passphrase of random words from a bundled word list. Easier
    to type and remember than a random password; 6 words is about 62 bits.
    The value is returned once and not stored."""
    return domain.generate_passphrase(words, separator, capitalize, add_number)


@command(name="pin", description="Generate a random PIN or one-time code")
@mcp.tool(meta={"keywords": ["generator", "pin", "otp", "one-time", "code", "digits", "random", "generate"], "display_label": "Generating code"})
@offload
def tool_gen_generatePin(
    length: Annotated[int, Field(description="How many digits.", ge=4, le=12)] = 6,
) -> PinResult:
    """Generate a random numeric PIN. Use it as a one-time code too: it is
    plain random digits with no time window or secret, so the caller must
    store and check it. For authenticator-app codes use `tool_gen_getTotpCode`."""
    return domain.generate_pin(length)


@command(name="totp_secret", description="Generate a TOTP secret for an authenticator app")
@mcp.tool(meta={"keywords": ["generator", "totp", "otp", "secret", "authenticator", "2fa", "mfa", "generate"], "display_label": "Generating TOTP secret"})
@offload
def tool_gen_generateTotpSecret(
    issuer: Annotated[str, Field(description="Service name shown in the authenticator app, e.g. Ember. Optional.")] = "",
    account: Annotated[str, Field(description="Account name shown in the authenticator app, e.g. an email. Optional.")] = "",
) -> TotpSecretResult:
    """Generate a new base32 TOTP secret and its otpauth:// URI. The person adds
    the secret to an authenticator app; `tool_gen_getTotpCode` then shows the
    same codes. The value is returned once and not stored."""
    return domain.generate_totp_secret(issuer, account)


@command(name="totp", description="Show the current TOTP code for a secret")
@mcp.tool(meta={"keywords": ["generator", "totp", "otp", "code", "authenticator", "2fa", "mfa", "current"], "display_label": "Computing TOTP code"})
@offload
def tool_gen_getTotpCode(
    secret: Annotated[
        str,
        Field(description="Base32 TOTP secret (spaces allowed).", json_schema_extra={"input": "password"}),
    ],
    digits: Annotated[int, Field(description="Code length.", ge=6, le=8)] = 6,
    period: Annotated[int, Field(description="Seconds each code stays valid.", ge=15, le=120)] = 30,
) -> TotpCodeResult:
    """Compute the current RFC 6238 one-time code for a base32 secret, plus
    the seconds left before it changes. Only the person who holds the secret
    should ask for this; the secret is not stored."""
    return domain.get_totp_code(secret, digits, period)
