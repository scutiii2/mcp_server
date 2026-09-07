"""cancellation.py tests - the round trip register/cancel/is_cancelled/
clear, and the missing-id no-op behavior each caller relies on."""

from __future__ import annotations

from src.llm import cancellation


def test_register_then_is_cancelled_is_false_until_cancelled():
    cancellation.register("req-1")
    assert cancellation.is_cancelled("req-1") is False

    assert cancellation.cancel("req-1") is True
    assert cancellation.is_cancelled("req-1") is True

    cancellation.clear("req-1")
    assert cancellation.is_cancelled("req-1") is False


def test_register_clears_a_stale_entry_for_a_reused_id():
    cancellation.cancel("req-1")
    assert cancellation.is_cancelled("req-1") is True

    cancellation.register("req-1")
    assert cancellation.is_cancelled("req-1") is False

    cancellation.clear("req-1")


def test_cancel_returns_false_for_a_missing_id():
    assert cancellation.cancel(None) is False
    assert cancellation.cancel("") is False


def test_is_cancelled_and_clear_are_safe_for_an_unknown_id():
    assert cancellation.is_cancelled("never-registered") is False
    cancellation.clear("never-registered")  # must not raise
