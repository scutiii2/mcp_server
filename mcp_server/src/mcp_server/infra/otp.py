"""One-time passcodes: minting, storage, and verification.

A one-time passcode proves control of an inbox. That only holds if three
things are true at once, and all three are enforced here rather than left
to whoever calls this module - a caller that forgets one doesn't get a
weaker OTP, it gets something that looks like an OTP and isn't:

  1. The code is short-lived (minutes, not days).
  2. A code can be used at most once.
  3. Guessing is bounded - a six-digit code is only a million values, so
     an unlimited-attempts OTP is a password anyone can brute force over
     a coffee break.

Deliberately its own table rather than a row in ``pending_requests``.
That store models "a human must approve this before it runs": opaque
payload, 72-hour token, one atomic claim. An OTP is the other shape -
the secret is short, low-entropy and typed by hand, so it needs an
attempt counter, a much shorter clock, and a lookup keyed by a public id
rather than by the secret. Bolting those columns onto
``pending_requests`` would leave every approval row carrying attempt
counters that mean nothing there, and would tempt future code into
mixing the two lifecycles. Same connection style and same stdlib-first
choice (``sqlite3``), just a table that means one thing.

**The code itself is never written down.** Only ``hmac(salt, code)`` is,
with a fresh random salt per record. Plain SHA-256 would be no better
than plaintext here: six digits is a million-entry rainbow table anyone
can build in seconds, so the salt - not the hash - is what makes a
database copy useless.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path


# Digits only, and six of them, because a person reads this out of an
# email and retypes it - often on a phone keyboard. An alphanumeric code
# would buy entropy at the cost of every 0/O and 1/l/I misread, and the
# entropy isn't what's defending this anyway: the attempt limit and the
# ten-minute clock are (see ``verify``). Any alphabet that survived
# transcription would need the same two guards, so the extra characters
# would only cost usability.
_ALPHABET = "0123456789"
DEFAULT_CODE_LENGTH = 6

# Ten minutes: long enough to switch to a mail client and back on a slow
# phone, short enough that a code sitting in an inbox stops being a
# credential quickly. Deliberately nothing like pending_requests' 72
# hours - an approval link waits for a human's schedule, an OTP waits for
# a human's attention.
DEFAULT_TTL_MINUTES = 10

# Five wrong guesses out of a million values leaves a 1-in-200,000 chance
# per issued code, which is the actual defence for a secret this short.
# Higher and the guard stops meaning much; lower and an ordinary typo
# streak locks a legitimate person out of a code they were sent.
DEFAULT_MAX_ATTEMPTS = 5


class Outcome(str, Enum):
    """Why a verification did or didn't succeed.

    A bare bool would force every caller to invent its own explanation
    for a failure, and the honest explanations differ enormously: "wrong
    code" means try again, "expired" means request a new one, and
    "too many attempts" means this code is dead no matter what you type.
    Telling a person the wrong one of those is how OTP flows become
    unusable.

    ``ALREADY_USED`` exists alongside ``WRONG_CODE`` for the same reason:
    presenting a correct-but-spent code is a different mistake (usually a
    double submit) from typing the wrong digits, and it's the one case
    where the right answer is "that worked, once".
    """

    VERIFIED = "verified"
    WRONG_CODE = "wrong_code"
    EXPIRED = "expired"
    TOO_MANY_ATTEMPTS = "too_many_attempts"
    ALREADY_USED = "already_used"
    UNKNOWN_ID = "unknown_id"


@dataclass(frozen=True)
class VerificationResult:
    outcome: Outcome
    # None whenever the number would be misleading rather than merely
    # unknown - there is nothing left to attempt on a burned, expired,
    # spent or nonexistent record.
    attempts_remaining: int | None = None

    @property
    def verified(self) -> bool:
        return self.outcome is Outcome.VERIFIED


@dataclass(frozen=True)
class IssuedOtp:
    """What ``create`` hands back. ``code`` exists here and nowhere else.

    This is the only object in the system that holds the plaintext code,
    and it exists so the caller can put it in an email. Anything that
    receives one is responsible for not letting the code escape into a
    return value, a log line, or a tool result - see
    ``capabilities/otp/domain.py``, where that rule is the whole point of
    the capability.
    """

    otp_id: str
    code: str
    expires_at: str


def _hash_code(salt: bytes, code: str) -> bytes:
    """HMAC rather than ``sha256(salt + code)``.

    Not because length-extension is reachable here - it isn't, with a
    fixed-width digest and no attacker-controlled suffix - but because
    HMAC is the construction that's specified for keyed hashing, so
    nobody reviewing this has to reason about whether the ad-hoc one is
    safe in this particular arrangement.
    """
    return hmac.new(salt, code.encode("utf-8"), hashlib.sha256).digest()


def _code_matches(salt: bytes, stored_hash: bytes, code: str) -> bool:
    """Registered into SQLite so the comparison can happen *inside* the
    UPDATE below (see ``verify``). ``compare_digest`` rather than ``==``:
    a byte-at-a-time comparison leaks, through timing, how much of a
    guess was right, which turns a search over a million codes into a
    search over ten digits six times."""
    return secrets.compare_digest(stored_hash, _hash_code(salt, code))


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS otp_codes (
            otp_id TEXT PRIMARY KEY,
            salt BLOB NOT NULL,
            code_hash BLOB NOT NULL,
            -- Recorded for whoever later has to answer "where did this
            -- code go?" from the database alone. Nothing in the
            -- verification path reads it: a code is proven by the code,
            -- not by who it was addressed to.
            recipient TEXT NOT NULL,
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL,
            max_attempts INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            verified_at TEXT
        )
        """
    )
    # deterministic=True lets SQLite treat this as a pure function, which
    # is what makes it legal in a WHERE clause it may evaluate more than
    # once. It is pure: same salt, same hash, same code, same answer.
    conn.create_function("otp_code_matches", 3, _code_matches, deterministic=True)
    return conn


def generate_code(length: int = DEFAULT_CODE_LENGTH) -> str:
    """``secrets``, never ``random`` - the latter's Mersenne Twister state
    is recoverable from its own output, so previously issued codes would
    predict the next one."""
    if length < 1:
        raise ValueError(f"OTP length must be at least 1, got {length}")
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def create(
    db_path: Path,
    recipient: str,
    *,
    ttl_minutes: int = DEFAULT_TTL_MINUTES,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    length: int = DEFAULT_CODE_LENGTH,
) -> IssuedOtp:
    """Mint a code, store only its salted HMAC, and return both ids.

    ``otp_id`` is deliberately *not* a secret and deliberately *not* the
    code: it's the handle the caller quotes back at ``verify``, so it
    travels through tool results and chat transcripts where the code must
    never go. It's still generated with ``secrets`` because a guessable
    id would let an attacker aim their five attempts at somebody else's
    live code instead of having to know one exists.
    """
    salt = secrets.token_bytes(16)
    code = generate_code(length)
    otp_id = secrets.token_urlsafe(12)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=ttl_minutes)

    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO otp_codes (otp_id, salt, code_hash, recipient, status, attempts, "
            "max_attempts, created_at, expires_at) VALUES (?, ?, ?, ?, 'pending', 0, ?, ?, ?)",
            (
                otp_id,
                salt,
                _hash_code(salt, code),
                recipient,
                max_attempts,
                now.isoformat(),
                expires_at.isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return IssuedOtp(otp_id=otp_id, code=code, expires_at=expires_at.isoformat())


def verify(db_path: Path, otp_id: str, code: str) -> VerificationResult:
    """Consume a code. Correct-and-live is the only path that succeeds.

    The success path is one UPDATE, not a read-then-write, for the same
    reason as ``pending_requests.claim``: "check whether it's still
    usable, then mark it used" has a gap in the middle, and a code that
    two concurrent requests can both spend is not one-time. Every
    condition that makes a code usable - still pending, not expired,
    attempts left, digits correct - is in that one WHERE clause, so the
    row is either won outright or not at all. Comparing the code inside
    SQL is what makes that possible, hence the registered
    ``otp_code_matches``.

    Expiry is checked in SQL rather than trusted to the caller, again
    following ``claim``: this is the last gate before whatever the code
    authorizes, so it does its own checking. ISO-8601 UTC compares
    correctly as text.

    Everything after the UPDATE is only there to explain a failure, and
    it charges the attempt: the counter has to move on a wrong guess or
    the limit is decorative. The record is burned at the limit rather
    than merely refused, so that further guesses fail even if one of them
    is right - otherwise an attacker who exhausts the counter could still
    win by racing a legitimate verification.
    """
    now = datetime.now(timezone.utc).isoformat()
    conn = _connect(db_path)
    try:
        won = conn.execute(
            "UPDATE otp_codes SET status = 'verified', attempts = attempts + 1, verified_at = ? "
            "WHERE otp_id = ? AND status = 'pending' AND expires_at > ? AND attempts < max_attempts "
            "AND otp_code_matches(salt, code_hash, ?)",
            (now, otp_id, now, code),
        ).rowcount
        conn.commit()
        if won == 1:
            return VerificationResult(Outcome.VERIFIED)

        row = conn.execute(
            "SELECT status, expires_at, attempts, max_attempts FROM otp_codes WHERE otp_id = ?",
            (otp_id,),
        ).fetchone()
        if row is None:
            return VerificationResult(Outcome.UNKNOWN_ID)

        status, expires_at, attempts, max_attempts = row
        if status == "verified":
            return VerificationResult(Outcome.ALREADY_USED)
        if status == "burned":
            return VerificationResult(Outcome.TOO_MANY_ATTEMPTS)
        # Expiry outranks a wrong code on purpose. An expired record is
        # already dead, so charging it an attempt would only produce a
        # confusing "3 attempts remaining" next to a code that can never
        # work again.
        if expires_at <= now:
            return VerificationResult(Outcome.EXPIRED)

        # A live record with the wrong digits. The increment and the burn
        # are one statement so two simultaneous guesses can't both read
        # the same count and write the same successor - that is precisely
        # how a five-attempt limit turns into an unlimited one.
        conn.execute(
            "UPDATE otp_codes SET attempts = attempts + 1, "
            "status = CASE WHEN attempts + 1 >= max_attempts THEN 'burned' ELSE 'pending' END "
            "WHERE otp_id = ? AND status = 'pending'",
            (otp_id,),
        )
        conn.commit()
        status, attempts, max_attempts = conn.execute(
            "SELECT status, attempts, max_attempts FROM otp_codes WHERE otp_id = ?",
            (otp_id,),
        ).fetchone()
    finally:
        conn.close()

    if status == "burned":
        return VerificationResult(Outcome.TOO_MANY_ATTEMPTS)
    return VerificationResult(Outcome.WRONG_CODE, attempts_remaining=max(max_attempts - attempts, 0))
