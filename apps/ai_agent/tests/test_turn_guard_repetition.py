"""Intervening work distinguishes repeated reads from a stuck tool loop."""

from src.llm.turn_guard import TurnGuard


def test_intervening_tool_calls_allow_productive_repeated_reads():
    guard = TurnGuard()
    for version in range(3):
        guard.check_call("read", {"path": "a"})
        guard.check_call("edit", {"path": "a", "version": version})
