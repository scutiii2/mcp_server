"""Progression: what a finished battle is worth.

`apply_terminal` runs inside the caller's transaction, so XP, Insignia, copies,
the awarded personality, fainting and the battle result are saved together or
not at all.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

from src.sparks.catalog import Catalog
from src.sparks.models import PersonalityInstance
from src.sparks.records import BattleRecord, PersonalityRecord, SparkRecord
from src.sparks.repository import SparkTransaction
from src.sparks.runtime import Clock, RandomSource, new_id

_EPS = 1e-9
REWARDED = ("won", "captured")
FAINTING = ("knocked_out", "forfeited")


class ProgressionService:
    def __init__(self, catalog: Catalog, clock: Clock, faint_seconds: float) -> None:
        self._catalog, self._clock, self._faint_seconds = catalog, clock, faint_seconds

    # -- pure helpers --------------------------------------------------------------

    def xp_needed(self, level: int) -> int:
        return self._catalog.levels.xp_per_level * level

    def add_xp(self, spark_id: str, level: int, xp: int, gained: int) -> tuple[int, int]:
        """Carry excess XP through level-ups; at the cap XP stops and the excess is discarded."""
        cap = self._catalog.level_cap(spark_id)
        if level >= cap:
            return cap, 0
        xp += gained
        while level < cap and xp >= self.xp_needed(level):
            xp -= self.xp_needed(level)
            level += 1
        return level, (0 if level >= cap else xp)

    def add_copies(self, spark_id: str, copies: int, granted: int) -> int:
        if self._catalog.spark(spark_id).forbidden:
            return min(copies + granted, self._catalog.economy.forbidden_copy_cap)
        return copies + granted

    def rewards_for(self, enemy_level: int, enemy_tier_id: str) -> tuple[int, int]:
        """(XP, Insignia) for beating or collecting an enemy."""
        multiplier = self._catalog.tier(enemy_tier_id).stat_multiplier
        eco = self._catalog.economy
        return (
            math.floor(eco.xp_reward_factor * enemy_level * multiplier + _EPS),
            math.floor(eco.insignia_reward_factor * enemy_level * multiplier + _EPS),
        )

    # -- a finished battle ---------------------------------------------------------

    async def apply_terminal(
        self, tx: SparkTransaction, battle: BattleRecord, terminal: str, rng: RandomSource
    ) -> dict[str, Any]:
        """Apply the consequences of `terminal` and return the public result."""
        owner = battle.owner
        fighter, enemy = battle.setup.player, battle.setup.wild
        result: dict[str, Any] = {"kind": terminal}
        spark = await tx.get_spark(owner, fighter.spark_id)

        if terminal in REWARDED:
            xp, insignia = self.rewards_for(enemy.level, enemy.tier_id)
            level, new_xp = self.add_xp(fighter.spark_id, spark.level, spark.xp, xp)
            await tx.put_spark(replace(spark, level=level, xp=new_xp))
            await tx.add_insignia(owner, insignia)
            result.update(xp=xp, insignia=insignia, level_before=spark.level, level_after=level)
            if terminal == "captured":
                result.update(await self._collect(tx, battle, rng))
        elif terminal in FAINTING:
            until = self._clock.now() + self._faint_seconds
            await tx.put_spark(replace(spark, faint_until=until))
            result["faint_until"] = until
        return result

    async def _collect(self, tx: SparkTransaction, battle: BattleRecord, rng: RandomSource) -> dict[str, Any]:
        owner, enemy = battle.owner, battle.setup.wild
        reward = self._catalog.tier(enemy.tier_id).copy_reward
        owned = await tx.get_spark(owner, enemy.spark_id)
        if owned is None:
            copies = self.add_copies(enemy.spark_id, 0, reward)
            await tx.put_spark(SparkRecord(owner, enemy.spark_id, copies, 1, 0))
            granted = copies
        else:
            copies = self.add_copies(enemy.spark_id, owned.copies, reward)
            await tx.put_spark(replace(owned, copies=copies))
            granted = copies - owned.copies
        instances = battle.wild_personalities
        chosen = instances[min(int(rng.next() * len(instances)), len(instances) - 1)]
        award = PersonalityRecord(new_id(), owner, enemy.spark_id, chosen.type_id, chosen.tier, self._clock.now())
        await tx.add_personality(award)
        return {
            "spark_id": enemy.spark_id,
            "copies_granted": granted,
            "copies": copies,
            "tier_id": self._catalog.tier_for_copies(enemy.spark_id, copies),
            "awarded_personality": _describe(award.instance()),
            "revealed_personalities": [_describe(i) for i in instances],  # every source instance, awarded or not
        }


def _describe(instance: PersonalityInstance) -> dict[str, Any]:
    return {"id": instance.id, "type": instance.type_id, "tier": instance.tier}
