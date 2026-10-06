"""Tests for the generator capability's domain logic. Pure functions, no
mocks; TOTP is checked against the RFC 6238 SHA1 test vectors."""

from __future__ import annotations

import math
import re
import string
from urllib.parse import parse_qs, urlparse

import pytest

from src.capabilities.generator import domain
from src.capabilities.generator.utils.wordlist import WORDS

RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # ASCII "12345678901234567890"


def test_wordlist_is_the_eff_long_list():
    assert len(WORDS) == len(set(WORDS)) == 7776
    assert (WORDS[0], WORDS[-1]) == ("abacus", "zoom")
    # Lowercase words; the published list has four hyphenated entries (drop-down, felt-tip, t-shirt, yo-yo).
    assert all(re.fullmatch(r"[a-z]+(?:-[a-z]+)?", word) for word in WORDS)


def test_password_has_requested_length_and_every_class():
    for _ in range(50):
        result = domain.generate_password(length=12)
        assert len(result.password) == 12
        assert any(c in string.ascii_uppercase for c in result.password)
        assert any(c in string.ascii_lowercase for c in result.password)
        assert any(c in string.digits for c in result.password)
        assert any(c in domain.SYMBOLS for c in result.password)


def test_password_respects_disabled_classes():
    result = domain.generate_password(length=30, use_upper=False, use_symbols=False)
    assert set(result.password) <= set(string.ascii_lowercase + string.digits)


def test_password_can_exclude_ambiguous_characters():
    for _ in range(50):
        result = domain.generate_password(length=40, exclude_ambiguous=True)
        assert not (set(result.password) & domain.AMBIGUOUS)


def test_password_entropy_grows_with_length():
    short = domain.generate_password(length=10).entropy_bits
    long = domain.generate_password(length=20).entropy_bits
    assert long == pytest.approx(short * 2, rel=0.01)


@pytest.mark.parametrize("length", [7, 129])
def test_password_rejects_bad_length(length):
    with pytest.raises(ValueError, match="length"):
        domain.generate_password(length=length)


def test_password_needs_a_character_class():
    with pytest.raises(ValueError, match="at least one"):
        domain.generate_password(use_upper=False, use_lower=False, use_digits=False, use_symbols=False)


def test_two_passwords_differ():
    assert domain.generate_password().password != domain.generate_password().password


def test_passphrase_words_and_separator():
    result = domain.generate_passphrase(words=5, separator=".")
    parts = result.passphrase.split(".")
    assert len(parts) == 5
    assert all(part in WORDS for part in parts)
    assert result.entropy_bits == round(5 * math.log2(7776), 1)


def test_passphrase_capitalize_and_number():
    # A separator that cannot occur inside a word, so the split is exact.
    result = domain.generate_passphrase(words=4, separator=".", capitalize=True, add_number=True)
    *words, number = result.passphrase.split(".")
    assert len(words) == 4
    assert all(word[0].isupper() for word in words)
    assert len(number) == 1 and number.isdigit()
    assert result.entropy_bits > domain.generate_passphrase(words=4).entropy_bits


@pytest.mark.parametrize("kwargs", [{"words": 2}, {"words": 13}, {"separator": "abcd"}])
def test_passphrase_rejects_bad_input(kwargs):
    with pytest.raises(ValueError):
        domain.generate_passphrase(**kwargs)


def test_pin_is_digits_of_requested_length():
    for _ in range(50):
        pin = domain.generate_pin(8).pin
        assert len(pin) == 8 and pin.isdigit()


@pytest.mark.parametrize("length", [3, 13])
def test_pin_rejects_bad_length(length):
    with pytest.raises(ValueError):
        domain.generate_pin(length)


@pytest.mark.parametrize(
    "at,digits,expected",
    [(59, 8, "94287082"), (1111111109, 8, "07081804"), (1234567890, 8, "89005924"), (59, 6, "287082")],
)
def test_totp_matches_rfc_6238_vectors(at, digits, expected):
    assert domain.get_totp_code(RFC_SECRET, digits=digits, at=at).code == expected


def test_totp_reports_seconds_remaining():
    assert domain.get_totp_code(RFC_SECRET, at=59).seconds_remaining == 1
    assert domain.get_totp_code(RFC_SECRET, at=60).seconds_remaining == 30


def test_totp_accepts_spaced_lowercase_secret():
    spaced = " ".join(RFC_SECRET[i : i + 4] for i in range(0, len(RFC_SECRET), 4)).lower()
    assert domain.get_totp_code(spaced, at=59).code == "287082"


@pytest.mark.parametrize("secret", ["", "   ", "not base32 !!", "1"])
def test_totp_rejects_bad_secret(secret):
    with pytest.raises(ValueError):
        domain.get_totp_code(secret)


@pytest.mark.parametrize("kwargs", [{"digits": 5}, {"period": 10}])
def test_totp_rejects_bad_options(kwargs):
    with pytest.raises(ValueError):
        domain.get_totp_code(RFC_SECRET, **kwargs)


def test_totp_secret_round_trips_into_a_code():
    result = domain.generate_totp_secret(issuer="Ember", account="me@example.com")
    assert re.fullmatch(r"[A-Z2-7]{32}", result.secret)
    assert len(domain.get_totp_code(result.secret).code) == 6


def test_totp_uri_shape():
    result = domain.generate_totp_secret(issuer="Ember App", account="me@example.com")
    uri = urlparse(result.otpauth_uri)
    query = parse_qs(uri.query)
    assert uri.scheme == "otpauth" and uri.netloc == "totp"
    assert query["secret"] == [result.secret]
    assert query["issuer"] == ["Ember App"]
    assert "Ember%20App%3Ame%40example.com" in result.otpauth_uri


def test_totp_uri_without_names_still_valid():
    assert domain.generate_totp_secret().otpauth_uri.startswith("otpauth://totp/account?secret=")
