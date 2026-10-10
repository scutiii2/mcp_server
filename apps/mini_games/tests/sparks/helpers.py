"""Test doubles and builders shared by the Spark tests."""

from __future__ import annotations

from src.sparks.models import PLAYER, WILD, AbilitySpec, BattleSetup, Fighter, PassiveSpec


class ScriptedRandom:
    """Returns the given draws in order; fails loudly if the code draws too often."""

    def __init__(self, *values: float) -> None:
        self._values = list(values)
        self.used = 0

    def next(self) -> float:
        if self.used >= len(self._values):
            raise AssertionError("more random draws than the test scripted")
        value = self._values[self.used]
        self.used += 1
        return value


class FixedClock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.t = now

    def now(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def fighter(
    side: str = PLAYER,
    hp: int = 100,
    essence: int = 40,
    speed: int = 20,
    abilities: tuple[AbilitySpec, ...] = (),
    passive: PassiveSpec | None = None,
    spark_id: str = "guardian",
    tier_id: str = "normal",
    level: int = 1,
) -> Fighter:
    return Fighter(side, spark_id, tier_id, level, hp, essence, speed, abilities, passive or PassiveSpec("none"))


def setup(player: Fighter | None = None, wild: Fighter | None = None) -> BattleSetup:
    return BattleSetup(player or fighter(PLAYER), wild or fighter(WILD))


def ability(
    id: str = "a1", category: str = "ATTACK", percentage: float = 150, cooldown: int = 1,
    stat: str | None = None, duration: int | None = None, unlock_level: int = 1,
) -> AbilitySpec:
    return AbilitySpec(id, id, unlock_level, category, percentage, cooldown, stat, duration)


def battle_record(owner: str = "ann", battle_id: str = "b1", encounter_id: str = "e1", status: str = "active", revision: int = 1):
    """A minimal valid BattleRecord for repository tests."""
    from src.sparks.models import BattleState, FighterState, PersonalityInstance
    from src.sparks.records import BattleRecord

    s = setup()
    state = BattleState(1, FighterState(100), FighterState(100))
    return BattleRecord(
        id=battle_id, owner=owner, encounter_id=encounter_id, status=status, phase="choosing" if status == "active" else "terminal",
        mode="manual", revision=revision, setup=s, state=state,
        player_personalities=(PersonalityInstance("p1", "AGGRESSIVE", 1),), wild_personalities=(PersonalityInstance("w1", "COWARD", 2),),
        emblem_limit=None, rng_seed=42, rng_counter=0, created_at=1.0, updated_at=1.0,
    )


class ScriptedPolicy:
    """Stands in for ActionPolicy: returns scripted action keys per actor, then basic ATTACK.

    The player's Spark is the collector. It never draws, so scripted tests stay exact."""

    def __init__(self, player=(), wild=()) -> None:
        self.player, self.wild = list(player), list(wild)
        self.contexts = []

    def probabilities(self, actions, ctx):
        return [1 / len(actions)] * len(actions)

    def choose(self, actions, ctx, u):
        from src.sparks.policy import PolicyDecision

        self.contexts.append(ctx)
        script = self.player if ctx.collector else self.wild
        key = script.pop(0) if script else "attack"
        action = next(a for a in actions if a.key == key)
        return PolicyDecision(action, tuple(self.probabilities(actions, ctx)))
