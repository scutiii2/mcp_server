"""Tests for chat_app settings resolution.

``_secret_key`` and ``_env`` are tested directly rather than through
``settings``, which is built once at import time and so can't see
monkeypatched environment variables afterwards.
"""

from __future__ import annotations

from chat_app.config import _env, _secret_key


def test_env_returns_the_configured_value(monkeypatch):
    monkeypatch.setenv("SOME_SETTING", "configured")

    assert _env("SOME_SETTING", "fallback") == "configured"


def test_blank_env_var_falls_back_to_the_default(monkeypatch):
    """A blank line in .env (OPENAI_MODEL=) means "I didn't set this", but
    os.getenv reports it as set-to-empty and would override the default."""
    monkeypatch.setenv("SOME_SETTING", "")

    assert _env("SOME_SETTING", "fallback") == "fallback"


def test_secret_key_uses_the_configured_value(monkeypatch):
    monkeypatch.setenv("FLASK_SECRET_KEY", "a-real-configured-key")

    assert _secret_key() == "a-real-configured-key"


def test_unset_secret_key_is_random_not_a_fixed_default(monkeypatch):
    """An unconfigured deployment should be inconvenient (restarting
    invalidates sessions), never predictable."""
    monkeypatch.delenv("FLASK_SECRET_KEY", raising=False)

    assert _secret_key() != _secret_key()
    assert len(_secret_key()) >= 32


def test_the_old_placeholder_key_is_treated_as_unset(monkeypatch):
    """"dev-change-me" shipped in .env.example for a while. Anyone who has
    read this repo knows it, so honouring it would be the same as having
    no secret at all."""
    monkeypatch.setenv("FLASK_SECRET_KEY", "dev-change-me")

    assert _secret_key() != "dev-change-me"
