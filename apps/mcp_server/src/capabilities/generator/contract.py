"""Result models for the generator tools. Every result ends with a
`message` meant to be relayed to a person verbatim."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PasswordResult(BaseModel):
    password: str = Field(description="The generated password. Shown once; this server does not store it.")
    length: int = Field(description="How many characters the password has.")
    entropy_bits: float = Field(description="Approximate strength in bits (length x log2 of the character pool).")
    message: str = Field(description="Human-readable summary, safe to relay verbatim.")


class PassphraseResult(BaseModel):
    passphrase: str = Field(description="The generated passphrase. Shown once; this server does not store it.")
    words: int = Field(description="How many words it holds.")
    entropy_bits: float = Field(description="Strength in bits (words x log2 of the word-list size, plus any digit).")
    message: str = Field(description="Human-readable summary, safe to relay verbatim.")


class PinResult(BaseModel):
    pin: str = Field(description="The generated digits, with leading zeros kept. Shown once; not stored.")
    length: int = Field(description="How many digits it has.")
    entropy_bits: float = Field(description="Strength in bits (length x log2 of 10).")
    message: str = Field(description="Human-readable summary, safe to relay verbatim.")


class TotpSecretResult(BaseModel):
    secret: str = Field(description="Base32 TOTP secret for an authenticator app. Shown once; not stored.")
    otpauth_uri: str = Field(description="otpauth:// URI an authenticator app or QR generator can import.")
    message: str = Field(description="Human-readable summary, safe to relay verbatim.")


class TotpCodeResult(BaseModel):
    code: str = Field(description="The current one-time code, with leading zeros kept.")
    seconds_remaining: int = Field(description="Seconds until this code stops being valid.")
    period: int = Field(description="Length of one code window in seconds.")
    message: str = Field(description="Human-readable summary, safe to relay verbatim.")
