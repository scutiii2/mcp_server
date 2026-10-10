"""A player's collection: profile, starter, personality pool and presets."""

from __future__ import annotations

from typing import Any

from src.sparks.catalog import Catalog
from src.sparks.errors import AlreadyInitialized, BattleInProgress, InvalidRequest, NotFound
from src.sparks.idempotency import IdempotentWriter
from src.sparks.records import PersonalityRecord, PresetRecord, SparkRecord
from src.sparks.repository import SparkRepository, SparkTransaction
from src.sparks.runtime import Clock, RandomSource, new_id

PRESET_SLOTS = range(1, 6)
PRESET_SIZE = 3
DEFAULT_PAGE, MAX_PAGE = 50, 100


def check_preset_slot(slot: int) -> None:
    """The one rule for preset slots, shared by the collection and the battle start."""
    if slot not in PRESET_SLOTS:
        raise InvalidRequest(f"preset slot must be from {PRESET_SLOTS.start} to {PRESET_SLOTS.stop - 1}")


class CollectionService:
    def __init__(self, repository: SparkRepository, writer: IdempotentWriter, catalog: Catalog,
                 clock: Clock, rng: RandomSource, roll_cooldown_seconds: float) -> None:
        self._repo, self._writer, self._catalog = repository, writer, catalog
        self._clock, self._rng, self._cooldown = clock, rng, roll_cooldown_seconds

    # -- profile -------------------------------------------------------------------

    async def profile_view(self, tx: SparkTransaction, owner: str) -> dict[str, Any]:
        player = await tx.get_player(owner)
        if player is None:
            raise NotFound("no profile yet; choose a starter first")
        now = self._clock.now()
        sparks = []
        for spark in await tx.list_sparks(owner):
            spec = self._catalog.spark(spark.spark_id)
            level_cap = self._catalog.level_cap(spark.spark_id)
            sparks.append({
                "spark_id": spark.spark_id, "name": spec.name,
                "ascension_types": [t.value for t in spec.ascension_types], "level": spark.level, "xp": spark.xp,
                "xp_needed": None if spark.level >= level_cap else self._catalog.levels.xp_per_level * spark.level,
                "level_cap": level_cap, "copies": spark.copies,
                "tier_id": self._catalog.tier_for_copies(spark.spark_id, spark.copies),
                "faint_until": spark.faint_until,
                "fainted": spark.faint_until is not None and spark.faint_until > now,
            })
        pending = await tx.pending_encounter(owner)
        active = await tx.active_battle(owner)
        return {
            "owner": owner, "insignia": player.insignia, "emblems": await tx.emblem_counts(owner), "sparks": sparks,
            "pending_encounter": pending.id if pending else None, "active_battle": active.id if active else None,
            "next_roll_at": None if player.last_roll_at is None else player.last_roll_at + self._cooldown,
        }

    async def profile(self, owner: str) -> dict[str, Any]:
        async with self._repo.transaction() as tx:
            return await self.profile_view(tx, owner)

    async def initialize(self, owner: str, key: str, starter_spark_id: str) -> dict[str, Any]:
        """Create the profile once: a level-1 starter with one random tier-1 personality in preset 1."""
        starters = {s.id for s in self._catalog.starter_sparks()}
        if starter_spark_id not in starters:
            raise InvalidRequest(f"choose a starter from: {', '.join(sorted(starters))}")

        async def work(tx: SparkTransaction) -> dict[str, Any]:
            if await tx.get_player(owner) is not None:
                raise AlreadyInitialized("this profile already exists")
            now = self._clock.now()
            await tx.create_player(owner, now)
            for tier_id, count in self._catalog.economy.starter_emblems.items():
                await tx.add_emblems(owner, tier_id, count)
            await tx.put_spark(SparkRecord(owner, starter_spark_id, 0, 1, 0))
            types = list(self._catalog.personalities)
            type_id = types[min(int(self._rng.next() * len(types)), len(types) - 1)]
            personality = PersonalityRecord(new_id(), owner, starter_spark_id, type_id,
                                            self._catalog.economy.starter_personality_tier, now)
            await tx.add_personality(personality)
            await tx.put_preset(PresetRecord(owner, starter_spark_id, 1, (personality.id,)))
            return await self.profile_view(tx, owner)

        return await self._writer.commit(owner, key, "profile.initialize", {"starter": starter_spark_id}, work)

    async def reset(self, owner: str, key: str) -> dict[str, Any]:
        """Delete all of the player's progress, so they can choose a starter again."""
        async def work(tx: SparkTransaction) -> dict[str, Any]:
            if await tx.get_player(owner) is None:
                raise NotFound("no profile yet; choose a starter first")
            if await tx.active_battle(owner) is not None:
                raise BattleInProgress("finish or forfeit your battle before resetting")
            await tx.delete_player_data(owner)
            return {"reset": True}

        return await self._writer.commit(owner, key, "profile.reset", {}, work)

    # -- personalities and presets -------------------------------------------------

    async def _require_spark(self, tx: SparkTransaction, owner: str, spark_id: str) -> None:
        if not self._catalog.has_spark(spark_id) or await tx.get_spark(owner, spark_id) is None:
            raise NotFound("you do not own that Spark")

    async def personalities(self, owner: str, spark_id: str, limit: int | None, cursor: int) -> dict[str, Any]:
        limit = DEFAULT_PAGE if limit is None else limit
        if not 1 <= limit <= MAX_PAGE:
            raise InvalidRequest(f"limit must be from 1 to {MAX_PAGE}")
        async with self._repo.transaction() as tx:
            await self._require_spark(tx, owner, spark_id)
            rows = await tx.list_personalities(owner, spark_id, limit + 1, max(cursor, 0))
        page = rows[:limit]
        return {
            "items": [{"id": r.id, "type": r.type_id, "tier": r.tier} for r in page],
            "next_cursor": page[-1].seq if len(rows) > limit else None,
        }

    async def get_preset(self, owner: str, spark_id: str, slot: int) -> dict[str, Any]:
        self._check_slot(slot)
        async with self._repo.transaction() as tx:
            await self._require_spark(tx, owner, spark_id)
            preset = await tx.get_preset(owner, spark_id, slot)
        return {"spark_id": spark_id, "slot": slot, "instance_ids": list(preset.instance_ids) if preset else []}

    @staticmethod
    def _check_slot(slot: int) -> None:
        check_preset_slot(slot)

    async def put_preset(self, owner: str, key: str, spark_id: str, slot: int, instance_ids: list[str]) -> dict[str, Any]:
        """Equip up to three distinct personality instances of this Spark. The same
        instance may appear in several presets."""
        self._check_slot(slot)
        if not isinstance(instance_ids, list) or len(instance_ids) > PRESET_SIZE or len(set(instance_ids)) != len(instance_ids):
            raise InvalidRequest(f"a preset holds up to {PRESET_SIZE} distinct personality instances")

        async def work(tx: SparkTransaction) -> dict[str, Any]:
            await self._require_spark(tx, owner, spark_id)
            found = await tx.get_personalities(owner, spark_id, instance_ids)
            if len(found) != len(instance_ids):
                raise InvalidRequest("every instance must be one of this Spark's collected personalities")
            await tx.put_preset(PresetRecord(owner, spark_id, slot, tuple(instance_ids)))
            return {"spark_id": spark_id, "slot": slot, "instance_ids": list(instance_ids)}

        return await self._writer.commit(
            owner, key, "preset.put", {"spark": spark_id, "slot": slot, "ids": instance_ids}, work)
