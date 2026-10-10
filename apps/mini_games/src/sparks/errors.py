"""Errors a caller can fix. Each carries the HTTP status the API maps it to:
400 for bad input, 404 for a missing or foreign record, 409 for a state
conflict (wrong phase, stale revision, not enough money, ...)."""

from __future__ import annotations


class SparkError(Exception):
    status_code = 400


class InvalidRequest(SparkError):
    status_code = 400


class NotFound(SparkError):
    status_code = 404


class Conflict(SparkError):
    status_code = 409


class AlreadyInitialized(Conflict):
    pass


class ActiveBattleExists(Conflict):
    pass


class BattleInProgress(Conflict):
    """The request needs the player's active battle to be over first (409)."""


class BattleAlreadyExists(Conflict):
    """A battle with this id, or for this encounter, was already stored (409)."""


class StaleBattle(Conflict):
    """The caller's round or revision no longer matches the battle."""


class WrongPhase(Conflict):
    pass


class BattleFinished(Conflict):
    pass


class DeadlinePassed(Conflict):
    pass


class EncounterCooldown(Conflict):
    def __init__(self, retry_after: float) -> None:
        super().__init__(f"a new encounter can be rolled in {retry_after:.0f} seconds")
        self.retry_after = retry_after


class SparkFainted(Conflict):
    pass


class InsufficientFunds(Conflict):
    pass


class InsufficientEmblems(Conflict):
    pass


class IdempotencyConflict(Conflict):
    """The same Idempotency-Key was reused with a different request."""


class NothingToSell(Conflict):
    pass
