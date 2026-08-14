"""Tests for infra/otp.py - real tmp_path SQLite, no mocking.

A one-time passcode is only worth anything because of properties that
are invisible when the happy path works: the code isn't recoverable from
the database, it can't be spent twice, it dies on a clock, and guessing
it is bounded. Each of those is asserted here, against a real file,
because every one of them is the kind of thing that silently stops being
true after a refactor while every "correct code verifies" test keeps
passing.
"""

from __future__ import annotations

import hashlib
import hmac
import sqlite3
from pathlib import Path

from mcp_server.infra import otp


def _column(db: Path, sql: str, params: tuple) -> list:
    """Read the table directly. Closing matters on Windows, where an open
    handle blocks tmp_path cleanup."""
    conn = sqlite3.connect(db)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def test_code_is_six_digits():
    """The alphabet is a deliberate choice, not an accident: digits only,
    because a human retypes this from an email. A change here should be
    a decision someone makes, not a diff nobody notices."""
    code = otp.generate_code()

    assert len(code) == 6
    assert code.isdigit()


def test_codes_differ_between_issues(tmp_path: Path):
    """A generator that repeats itself would make every previously
    delivered email a valid credential for the next request."""
    db = tmp_path / "otp.db"
    codes = {otp.create(db, "user@example.com").code for _ in range(25)}

    assert len(codes) > 1


# --- the code is never stored -------------------------------------------


def test_the_code_never_appears_in_the_database_file(tmp_path: Path):
    """The property the whole module exists for. Asserted against the raw
    bytes of the file rather than against columns, so it stays true even
    if someone adds a column, an index, or a debug field later - anywhere
    the plaintext lands, this catches it."""
    db = tmp_path / "otp.db"
    issued = otp.create(db, "user@example.com")

    raw = db.read_bytes()

    assert issued.code.encode("utf-8") not in raw


def test_stored_hash_is_hmac_of_the_per_record_salt(tmp_path: Path):
    db = tmp_path / "otp.db"
    issued = otp.create(db, "user@example.com")

    salt, stored = _column(
        db, "SELECT salt, code_hash FROM otp_codes WHERE otp_id = ?", (issued.otp_id,)
    )[0]

    assert stored == hmac.new(salt, issued.code.encode("utf-8"), hashlib.sha256).digest()


def test_two_records_get_different_salts(tmp_path: Path):
    """The salt, not the hash, is what makes a stolen database useless:
    six digits is a million entries, so one shared salt would mean one
    rainbow table unlocks every code ever issued."""
    db = tmp_path / "otp.db"
    first = otp.create(db, "user@example.com")
    second = otp.create(db, "user@example.com")

    salts = [
        row[0]
        for row in _column(
            db,
            "SELECT salt FROM otp_codes WHERE otp_id IN (?, ?)",
            (first.otp_id, second.otp_id),
        )
    ]

    assert len(salts) == 2
    assert salts[0] != salts[1]


# --- single use ---------------------------------------------------------


def test_correct_code_verifies(tmp_path: Path):
    db = tmp_path / "otp.db"
    issued = otp.create(db, "user@example.com")

    result = otp.verify(db, issued.otp_id, issued.code)

    assert result.verified is True
    assert result.outcome is otp.Outcome.VERIFIED


def test_a_verified_code_cannot_be_used_again(tmp_path: Path):
    """Single use is the name of the thing. A code that verifies twice
    lets anyone who overheard it once replay it - and a double-submitted
    form is the ordinary way that happens, not an attack."""
    db = tmp_path / "otp.db"
    issued = otp.create(db, "user@example.com")
    otp.verify(db, issued.otp_id, issued.code)

    second = otp.verify(db, issued.otp_id, issued.code)

    assert second.verified is False
    assert second.outcome is otp.Outcome.ALREADY_USED


# --- wrong codes and unknown ids ----------------------------------------


def test_wrong_code_is_refused_and_reports_attempts_left(tmp_path: Path):
    db = tmp_path / "otp.db"
    issued = otp.create(db, "user@example.com")
    wrong = "111111" if issued.code != "111111" else "222222"

    result = otp.verify(db, issued.otp_id, wrong)

    assert result.verified is False
    assert result.outcome is otp.Outcome.WRONG_CODE
    assert result.attempts_remaining == otp.DEFAULT_MAX_ATTEMPTS - 1


def test_unknown_otp_id_is_refused(tmp_path: Path):
    """Distinguished from a wrong code so a caller can say "that id isn't
    a thing" instead of "wrong digits" - and so a correct code can never
    verify against an id that was never issued."""
    db = tmp_path / "otp.db"
    issued = otp.create(db, "user@example.com")

    result = otp.verify(db, "not-a-real-id", issued.code)

    assert result.outcome is otp.Outcome.UNKNOWN_ID


def test_a_code_does_not_verify_against_another_records_id(tmp_path: Path):
    """Verification is keyed by (id, code), not by the code alone. If the
    code were the lookup key, one guess would be tested against every
    live record at once."""
    db = tmp_path / "otp.db"
    first = otp.create(db, "user@example.com")
    second = otp.create(db, "user@example.com")

    result = otp.verify(db, second.otp_id, first.code)

    assert result.verified is False
    assert otp.verify(db, first.otp_id, first.code).verified is True


# --- expiry -------------------------------------------------------------


def test_expired_code_is_refused_even_when_correct(tmp_path: Path):
    db = tmp_path / "otp.db"
    issued = otp.create(db, "user@example.com", ttl_minutes=-1)

    result = otp.verify(db, issued.otp_id, issued.code)

    assert result.verified is False
    assert result.outcome is otp.Outcome.EXPIRED


def test_expiry_outranks_a_wrong_code_in_the_reported_reason(tmp_path: Path):
    """Someone holding a stale code needs to be told to request a new
    one. Reporting "wrong code" would send them back to retype digits
    that can never work."""
    db = tmp_path / "otp.db"
    issued = otp.create(db, "user@example.com", ttl_minutes=-1)

    assert otp.verify(db, issued.otp_id, "000000").outcome is otp.Outcome.EXPIRED


# --- attempt limiting ---------------------------------------------------


def test_the_record_is_burned_after_the_attempt_limit(tmp_path: Path):
    """The defence that actually matters. Six digits is a million values,
    so an unbounded attempt count is a lock anyone can open by trying -
    and the record has to be burned, not merely refused, so the correct
    code stops working too."""
    db = tmp_path / "otp.db"
    issued = otp.create(db, "user@example.com", max_attempts=3)

    outcomes = [otp.verify(db, issued.otp_id, "000000").outcome for _ in range(3)]

    assert outcomes[:2] == [otp.Outcome.WRONG_CODE, otp.Outcome.WRONG_CODE]
    assert outcomes[2] is otp.Outcome.TOO_MANY_ATTEMPTS
    assert otp.verify(db, issued.otp_id, issued.code).outcome is otp.Outcome.TOO_MANY_ATTEMPTS


def test_attempts_remaining_counts_down(tmp_path: Path):
    db = tmp_path / "otp.db"
    issued = otp.create(db, "user@example.com", max_attempts=4)

    remaining = [otp.verify(db, issued.otp_id, "000000").attempts_remaining for _ in range(3)]

    assert remaining == [3, 2, 1]


def test_a_correct_code_still_works_below_the_limit(tmp_path: Path):
    """The limit must not be so eager that an ordinary typo costs someone
    the code they were sent."""
    db = tmp_path / "otp.db"
    issued = otp.create(db, "user@example.com")
    otp.verify(db, issued.otp_id, "000000")

    assert otp.verify(db, issued.otp_id, issued.code).verified is True


# --- storage mechanics --------------------------------------------------


def test_db_file_created_in_a_nonexistent_parent_directory(tmp_path: Path):
    """OTP_PATH defaults to a relative path, so the first write often
    lands somewhere that doesn't exist yet."""
    db = tmp_path / "does" / "not" / "exist" / "otp.db"

    issued = otp.create(db, "user@example.com")

    assert db.exists()
    assert otp.verify(db, issued.otp_id, issued.code).verified is True


def test_records_do_not_clobber_each_other(tmp_path: Path):
    db = tmp_path / "otp.db"
    first = otp.create(db, "a@example.com")
    second = otp.create(db, "b@example.com")

    otp.verify(db, first.otp_id, first.code)

    assert otp.verify(db, second.otp_id, second.code).verified is True
