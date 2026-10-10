"""Wild encounters: roll a preview, decline it, and hand it to a battle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.sparks.catalog import Catalog
from src.sparks.errors import ActiveBattleExists, EncounterCooldown, InvalidRequest, NotFound, WrongPhase
from src.sparks.idempotency import IdempotentWriter
from src.sparks.models import PersonalityInstance
from src.sparks.records import EncounterRecord
from src.sparks.repository import SparkRepository, SparkTransaction
from src.sparks.runtime import Clock, RandomSource, new_id


@dataclass(frozen=True)
class RolledEncounter:
    spark_id: str
    tier_id: str
    level: int
    personalities: tuple[PersonalityInstance, ...]


class EncounterRoller:
    """The random draws behind an encounter. Pure given the random source."""

    def __init__(self, catalog: Catalog) -> None:
        self._catalog = catalog

    @staticmethod
    def _pick(count: int, u: float) -> int:
        return min(int(u * count), count - 1)

    def _tier(self, u: float) -> str:
        cumulative = 0.0
        for tier in self._catalog.tiers:
            cumulative += tier.encounter_probability
            if u < cumulative:
                return tier.id
        return self._catalog.tiers[-1].id

    def roll(self, highest_level: int, rng: RandomSource) -> RolledEncounter:
        tier_id = self._tier(rng.next())
        if tier_id == self._catalog.forbidden_tier.id:
            spec = self._catalog.forbidden_spark()
        else:
            regular = self._catalog.regular_sparks()
            spec = regular[self._pick(len(regular), rng.next())]
        cap = self._catalog.level_cap(spec.id)
        window = self._catalog.economy.encounter_level_window
        low = min(max(highest_level - window, 1), cap)
        high = min(max(highest_level + window, 1), cap)
        level = low + self._pick(high - low + 1, rng.next())
        types = list(self._catalog.personalities)
        tier_odds = self._catalog.economy.personality_tier_probabilities
        instances = []
        for index in range(1 + self._pick(3, rng.next())):
            type_id = types[self._pick(len(types), rng.next())]
            u, tier, cumulative = rng.next(), len(tier_odds), 0.0
            for number, probability in enumerate(tier_odds, start=1):
                cumulative += probability
                if u < cumulative:
                    tier = number
                    break
            instances.append(PersonalityInstance(new_id(), type_id, tier))
        return RolledEncounter(spec.id, tier_id, level, tuple(instances))


class EncounterService:
    def __init__(self, repository: SparkRepository, writer: IdempotentWriter, catalog: Catalog,
                 clock: Clock, rng: RandomSource, cooldown_seconds: float) -> None:
        self._repo, self._writer, self._catalog = repository, writer, catalog
        self._clock, self._rng, self._cooldown = clock, rng, cooldown_seconds
        self._roller = EncounterRoller(catalog)

    def preview(self, record: EncounterRecord) -> dict[str, Any]:
        """What the player may see: the Spark, tier and level, never the personalities."""
        spec = self._catalog.spark(record.spark_id)
        return {"id": record.id, "spark_id": record.spark_id, "name": spec.name,
                "tier_id": record.tier_id, "level": record.level, "status": record.status,
                "created_at": record.created_at}

    async def roll(self, owner: str, key: str) -> dict[str, Any]:
        async def work(tx: SparkTransaction) -> dict[str, Any]:
            player = await tx.get_player(owner)
            if player is None:
                raise NotFound("no profile yet; choose a starter first")
            if await tx.active_battle(owner) is not None:
                raise ActiveBattleExists("finish or forfeit the active battle first")
            now = self._clock.now()
            if player.last_roll_at is not None and now - player.last_roll_at < self._cooldown:
                raise EncounterCooldown(self._cooldown - (now - player.last_roll_at))
            previous = await tx.pending_encounter(owner)
            if previous is not None:
                await tx.set_encounter_status(previous.id, "expired")
            highest = max(s.level for s in await tx.list_sparks(owner))
            rolled = self._roller.roll(highest, self._rng)
            record = EncounterRecord(new_id(), owner, rolled.spark_id, rolled.tier_id, rolled.level, "pending",
                                     rolled.personalities, now)
            await tx.add_encounter(record)
            await tx.set_last_roll(owner, now)
            return self.preview(record)

        return await self._writer.commit(owner, key, "encounter.roll", {}, work)

    async def get(self, owner: str, encounter_id: str) -> dict[str, Any]:
        async with self._repo.transaction() as tx:
            record = await tx.get_encounter(owner, encounter_id)
        if record is None:
            raise NotFound("no such encounter")
        return self.preview(record)

    async def decline(self, owner: str, key: str, encounter_id: str) -> dict[str, Any]:
        if not encounter_id:
            raise InvalidRequest("an encounter id is required")

        async def work(tx: SparkTransaction) -> dict[str, Any]:
            record = await tx.get_encounter(owner, encounter_id)
            if record is None:
                raise NotFound("no such encounter")
            if record.status != "pending":
                raise WrongPhase(f"this encounter is already {record.status}")
            await tx.set_encounter_status(record.id, "declined")
            return self.preview(EncounterRecord(**{**record.__dict__, "status": "declined"}))

        return await self._writer.commit(owner, key, "encounter.decline", {"id": encounter_id}, work)
