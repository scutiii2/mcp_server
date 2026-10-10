"""Immutable value objects shared by the battle engine, policy and services.

Everything that is saved with a battle has to_dict/from_dict so a battle can be
rebuilt exactly after a restart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PLAYER, WILD = "player", "wild"
SIDES = (PLAYER, WILD)
CATEGORIES = ("ATTACK", "DEFENSE", "SUPPORT", "FEAR", "INTERCEPT")
ABILITY_CATEGORIES = ("ATTACK", "DEFENSE", "SUPPORT")


def other(side: str) -> str:
    return WILD if side == PLAYER else PLAYER


@dataclass(frozen=True)
class AbilitySpec:
    id: str
    name: str
    unlock_level: int
    category: str  # ATTACK, DEFENSE or SUPPORT
    percentage: float  # of ESSENCE
    cooldown: int
    stat: str | None = None  # SUPPORT only: "essence" or "speed"
    duration: int | None = None  # SUPPORT only: rounds, counting the activation round

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AbilitySpec":
        return cls(**raw)


@dataclass(frozen=True)
class PassiveSpec:
    kind: str
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "params": dict(self.params)}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PassiveSpec":
        return cls(raw["kind"], dict(raw.get("params", {})))


@dataclass(frozen=True)
class Action:
    """A choice for one round. `kind` is attack (basic), ability, flee or catch."""

    kind: str
    category: str
    ability_id: str | None = None
    percentage: float = 100.0
    emblem_tier: str | None = None  # CATCH by the collecting side only

    @property
    def key(self) -> str:
        return f"ability:{self.ability_id}" if self.kind == "ability" else self.kind

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "category": self.category, "ability_id": self.ability_id,
                "percentage": self.percentage, "emblem_tier": self.emblem_tier}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Action":
        return cls(raw["kind"], raw["category"], raw.get("ability_id"), raw.get("percentage", 100.0), raw.get("emblem_tier"))


@dataclass(frozen=True)
class Buff:
    source: str  # ability id, or "passive:<kind>"
    stat: str  # "essence" or "speed"
    amount: int
    rounds_left: int | None  # None = lasts the whole battle

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Buff":
        return cls(**raw)


@dataclass(frozen=True)
class DefenseEffect:
    rating: float
    attacks_left: int
    rounds_left: int

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "DefenseEffect":
        return cls(**raw)


@dataclass(frozen=True)
class Fighter:
    """A battle participant's stats and abilities, frozen when the battle starts
    so later balance changes never alter a fight in progress."""

    side: str
    spark_id: str
    tier_id: str
    level: int
    max_hp: int
    essence: int  # unbuffed
    speed: int  # unbuffed
    abilities: tuple[AbilitySpec, ...]
    passive: PassiveSpec

    def to_dict(self) -> dict[str, Any]:
        return {
            "side": self.side, "spark_id": self.spark_id, "tier_id": self.tier_id, "level": self.level,
            "max_hp": self.max_hp, "essence": self.essence, "speed": self.speed,
            "abilities": [a.to_dict() for a in self.abilities], "passive": self.passive.to_dict(),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Fighter":
        return cls(
            raw["side"], raw["spark_id"], raw["tier_id"], raw["level"], raw["max_hp"], raw["essence"], raw["speed"],
            tuple(AbilitySpec.from_dict(a) for a in raw["abilities"]), PassiveSpec.from_dict(raw["passive"]),
        )


@dataclass(frozen=True)
class FighterState:
    hp: int
    buffs: tuple[Buff, ...] = ()
    defense: DefenseEffect | None = None
    cooldowns: tuple[tuple[str, int], ...] = ()  # (ability id, first round it is available again)

    def to_dict(self) -> dict[str, Any]:
        return {"hp": self.hp, "buffs": [b.to_dict() for b in self.buffs],
                "defense": self.defense.to_dict() if self.defense else None,
                "cooldowns": [[a, r] for a, r in self.cooldowns]}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "FighterState":
        return cls(raw["hp"], tuple(Buff.from_dict(b) for b in raw["buffs"]),
                   DefenseEffect.from_dict(raw["defense"]) if raw["defense"] else None,
                   tuple((a, r) for a, r in raw["cooldowns"]))


@dataclass(frozen=True)
class RevealedRound:
    """What both sides chose in a finished round: public after the reveal."""

    round: int
    actions: dict[str, tuple[str, str]]  # side -> (action key, category)
    events: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"round": self.round, "actions": {s: list(a) for s, a in self.actions.items()}, "events": list(self.events)}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "RevealedRound":
        return cls(raw["round"], {s: (a[0], a[1]) for s, a in raw["actions"].items()}, tuple(raw["events"]))


@dataclass(frozen=True)
class BattleState:
    round: int
    player: FighterState
    wild: FighterState
    history: tuple[RevealedRound, ...] = ()

    def of(self, side: str) -> FighterState:
        return self.player if side == PLAYER else self.wild

    def to_dict(self) -> dict[str, Any]:
        return {"round": self.round, "player": self.player.to_dict(), "wild": self.wild.to_dict(),
                "history": [h.to_dict() for h in self.history]}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "BattleState":
        return cls(raw["round"], FighterState.from_dict(raw["player"]), FighterState.from_dict(raw["wild"]),
                   tuple(RevealedRound.from_dict(h) for h in raw["history"]))


@dataclass(frozen=True)
class BattleSetup:
    """The two frozen fighters of one battle."""

    player: Fighter
    wild: Fighter

    def of(self, side: str) -> Fighter:
        return self.player if side == PLAYER else self.wild

    def to_dict(self) -> dict[str, Any]:
        return {"player": self.player.to_dict(), "wild": self.wild.to_dict()}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "BattleSetup":
        return cls(Fighter.from_dict(raw["player"]), Fighter.from_dict(raw["wild"]))


@dataclass(frozen=True)
class PersonalityInstance:
    """One collected personality: a type (AGGRESSIVE ...) at tier 1 to 3."""

    id: str
    type_id: str
    tier: int

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PersonalityInstance":
        return cls(raw["id"], raw["type_id"], raw["tier"])


@dataclass(frozen=True)
class RoundOutcome:
    state: BattleState
    events: tuple[dict[str, Any], ...]
    terminal: str | None  # won, knocked_out, captured, escaped, wild_escaped
    emblem_consumed: str | None
    draws: tuple[float, ...]


TERMINAL_KINDS = ("won", "knocked_out", "captured", "escaped", "wild_escaped", "forfeited")
