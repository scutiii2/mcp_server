"""Password, passphrase, PIN and TOTP generation.

Pure standard library (`secrets`, `hmac`, `hashlib`): no I/O, no services,
no MCP imports, so everything here is unit-testable directly. All
randomness comes from `secrets` (the OS CSPRNG), never `random`. Nothing
generated is stored or logged; callers get it back once.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import math
import secrets
import string
import struct
import time
from urllib.parse import quote, urlencode

from src.capabilities.generator.contract import (
    PassphraseResult,
    PasswordResult,
    PinResult,
    TotpCodeResult,
    TotpSecretResult,
)
from src.capabilities.generator.utils.wordlist import WORDS

SYMBOLS = "!@#$%^&*()-_=+[]{};:,.?"
AMBIGUOUS = set("Il1O0o")
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
TOTP_SECRET_BYTES = 20  # 160 bits, the RFC 4226 recommendation


def _entropy_bits(pool_size: int, picks: int) -> float:
    return round(picks * math.log2(pool_size), 1)


def generate_password(
    length: int = 20,
    use_upper: bool = True,
    use_lower: bool = True,
    use_digits: bool = True,
    use_symbols: bool = True,
    exclude_ambiguous: bool = False,
) -> PasswordResult:
    """Random password with at least one character from each chosen class."""
    classes = [
        chars
        for enabled, chars in (
            (use_upper, string.ascii_uppercase),
            (use_lower, string.ascii_lowercase),
            (use_digits, string.digits),
            (use_symbols, SYMBOLS),
        )
        if enabled
    ]
    if exclude_ambiguous:
        classes = ["".join(c for c in chars if c not in AMBIGUOUS) for chars in classes]
    if not classes:
        raise ValueError("Pick at least one character type: upper, lower, digits or symbols.")
    if not MIN_PASSWORD_LENGTH <= length <= MAX_PASSWORD_LENGTH:
        raise ValueError(f"length must be between {MIN_PASSWORD_LENGTH} and {MAX_PASSWORD_LENGTH}.")

    pool = "".join(classes)
    chars = [secrets.choice(chars) for chars in classes]
    chars += [secrets.choice(pool) for _ in range(length - len(chars))]
    secrets.SystemRandom().shuffle(chars)
    password = "".join(chars)
    bits = _entropy_bits(len(pool), length)
    return PasswordResult(
        password=password,
        length=length,
        entropy_bits=bits,
        message=f"Generated a {length}-character password (about {bits} bits). It is shown once and not stored.",
    )


def generate_passphrase(
    words: int = 6,
    separator: str = "-",
    capitalize: bool = False,
    add_number: bool = False,
) -> PassphraseResult:
    """Random words from the bundled list, optionally capitalised and with a trailing digit."""
    if not 3 <= words <= 12:
        raise ValueError("words must be between 3 and 12.")
    if len(separator) > 3:
        raise ValueError("separator can be at most 3 characters.")

    picked = [secrets.choice(WORDS) for _ in range(words)]
    if capitalize:
        picked = [word.capitalize() for word in picked]
    passphrase = separator.join(picked)
    bits = _entropy_bits(len(WORDS), words)
    if add_number:
        passphrase += separator + str(secrets.randbelow(10))
        bits = round(bits + math.log2(10), 1)
    return PassphraseResult(
        passphrase=passphrase,
        words=words,
        entropy_bits=bits,
        message=f"Generated a {words}-word passphrase (about {bits} bits). It is shown once and not stored.",
    )


def generate_pin(length: int = 6) -> PinResult:
    """Random digits, leading zeros kept. Also usable as a one-time code."""
    if not 4 <= length <= 12:
        raise ValueError("length must be between 4 and 12.")
    pin = "".join(secrets.choice(string.digits) for _ in range(length))
    return PinResult(
        pin=pin,
        length=length,
        entropy_bits=_entropy_bits(10, length),
        message=f"Generated a {length}-digit code. It is shown once and not stored.",
    )


def _decode_secret(secret: str) -> bytes:
    cleaned = "".join(secret.split()).upper().rstrip("=")
    if not cleaned:
        raise ValueError("secret is empty.")
    try:
        return base64.b32decode(cleaned + "=" * (-len(cleaned) % 8))
    except (binascii.Error, ValueError) as error:
        raise ValueError("secret is not valid base32 (letters A-Z and digits 2-7).") from error


def _hotp(key: bytes, counter: int, digits: int) -> str:
    """RFC 4226 HOTP with HMAC-SHA1 and dynamic truncation."""
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**digits).zfill(digits)


def generate_totp_secret(issuer: str = "", account: str = "") -> TotpSecretResult:
    """New random base32 secret plus the otpauth:// URI that imports it."""
    secret = base64.b32encode(secrets.token_bytes(TOTP_SECRET_BYTES)).decode("ascii").rstrip("=")
    label = quote(f"{issuer}:{account}" if issuer and account else issuer or account or "account", safe="")
    params = {"secret": secret}
    if issuer:
        params["issuer"] = issuer
    uri = f"otpauth://totp/{label}?{urlencode(params, quote_via=quote)}"
    return TotpSecretResult(
        secret=secret,
        otpauth_uri=uri,
        message="Generated a TOTP secret (SHA1, 6 digits, 30 s). Add it to an authenticator app now; it is shown once and not stored.",
    )


def get_totp_code(secret: str, digits: int = 6, period: int = 30, at: float | None = None) -> TotpCodeResult:
    """Current RFC 6238 code for `secret`. `at` (unix seconds) is for tests."""
    if digits not in (6, 7, 8):
        raise ValueError("digits must be 6, 7 or 8.")
    if not 15 <= period <= 120:
        raise ValueError("period must be between 15 and 120 seconds.")
    now = time.time() if at is None else at
    code = _hotp(_decode_secret(secret), int(now // period), digits)
    remaining = period - int(now % period)
    return TotpCodeResult(
        code=code,
        seconds_remaining=remaining,
        period=period,
        message=f"Current code {code}, valid for {remaining} more seconds.",
    )
