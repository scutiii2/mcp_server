"""Spark passives as small polymorphic objects.

Each passive overrides only the hooks it changes; the base class holds the
neutral defaults, so the engine asks every passive the same questions.
"""

from __future__ import annotations

import math
from typing import Callable

from src.sparks.models import PassiveSpec


class Passive:
    """Neutral behavior: a Spark without a passive effect."""

    def start_buffs(self, essence: int) -> list[tuple[str, int]]:
        """(stat, amount) bonuses applied once when the battle starts."""
        return []

    def defense_limits(self) -> tuple[int, int]:
        """(protected attacks, rounds) of a fresh DEFENSE effect."""
        return 1, 1

    def defense_rating_bonus(self, essence: int) -> float:
        return 0.0

    def support_extra_rounds(self) -> int:
        return 0

    def attack_bonus(self, essence: int, hp: int, max_hp: int, target_chose_defense: bool) -> float:
        """Raw damage added to an attack, before mitigation."""
        return 0.0

    def cooldown(self, base: int) -> int:
        return base


class DefenseExtension(Passive):
    def __init__(self, protected_attacks: int, rounds: int) -> None:
        self._attacks, self._rounds = protected_attacks, rounds

    def defense_limits(self) -> tuple[int, int]:
        return self._attacks, self._rounds


class LowHpAttackBonus(Passive):
    def __init__(self, hp_below: float, essence_fraction: float) -> None:
        self._below, self._fraction = hp_below, essence_fraction

    def attack_bonus(self, essence: int, hp: int, max_hp: int, target_chose_defense: bool) -> float:
        return essence * self._fraction if hp < max_hp * self._below else 0.0


class BattleStartSpeed(Passive):
    def __init__(self, essence_fraction: float) -> None:
        self._fraction = essence_fraction

    def start_buffs(self, essence: int) -> list[tuple[str, int]]:
        return [("speed", math.floor(essence * self._fraction))]


class DefenseRatingBonus(Passive):
    def __init__(self, essence_fraction: float) -> None:
        self._fraction = essence_fraction

    def defense_rating_bonus(self, essence: int) -> float:
        return essence * self._fraction


class AttackBonusVersusDefense(Passive):
    def __init__(self, essence_fraction: float) -> None:
        self._fraction = essence_fraction

    def attack_bonus(self, essence: int, hp: int, max_hp: int, target_chose_defense: bool) -> float:
        return essence * self._fraction if target_chose_defense else 0.0


class SupportDurationBonus(Passive):
    def __init__(self, rounds: int) -> None:
        self._rounds = rounds

    def support_extra_rounds(self) -> int:
        return self._rounds


class CooldownReduction(Passive):
    def __init__(self, rounds: int, minimum: int) -> None:
        self._rounds, self._minimum = rounds, minimum

    def cooldown(self, base: int) -> int:
        return max(base - self._rounds, self._minimum)


class PassiveFactory:
    """Builds a Passive from the saved spec. Register new kinds with `register`."""

    def __init__(self) -> None:
        self._kinds: dict[str, Callable[..., Passive]] = {
            "none": Passive,
            "defense_extension": DefenseExtension,
            "low_hp_attack_bonus": LowHpAttackBonus,
            "battle_start_speed": BattleStartSpeed,
            "defense_rating_bonus": DefenseRatingBonus,
            "attack_bonus_vs_defense": AttackBonusVersusDefense,
            "support_duration_bonus": SupportDurationBonus,
            "cooldown_reduction": CooldownReduction,
        }

    def register(self, kind: str, builder: Callable[..., Passive]) -> None:
        self._kinds[kind] = builder

    def create(self, spec: PassiveSpec) -> Passive:
        try:
            return self._kinds[spec.kind](**spec.params)
        except KeyError:
            raise ValueError(f"unknown passive kind {spec.kind!r}") from None
