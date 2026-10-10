"""The battle lifecycle: start, choose, resolve, prompt for an EMBLEM, switch
mode, forfeit, and resume after a restart.

Rules this class keeps:
- Decisions are built from public state only. The wild Spark's action is
  decided before the player's action is read, and nothing but the battle's
  public state is passed to the situation reader, so an AI never sees the
  opponent's pending choice.
- A round's lock and resolution commit in one transaction with the new
  checkpoint, the EMBLEM spent and (when the battle ends) the rewards. The
  only choice ever stored before a reveal is the wild action and the player's
  CATCH intent while an EMBLEM prompt is open; a restart never rerolls it.
- The battle's random stream is (seed, counter). Retries and restarts replay
  the same draws; mutations are idempotent and revision-checked.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Any

from src.sparks.battle_view import BattleViewBuilder
from src.sparks.catalog import Catalog, CatalogError
from src.sparks.decider import ActionDecider, Decision
from src.sparks.emblem_picker import EmblemPicker
from src.sparks.engine import ActionError, BattleEngine
from src.sparks.errors import (
    BattleFinished,
    DeadlinePassed,
    InsufficientEmblems,
    InvalidRequest,
    NotFound,
    SparkFainted,
    StaleBattle,
    WrongPhase,
)
from src.sparks.idempotency import IdempotentWriter
from src.sparks.models import PLAYER, WILD, Action, BattleSetup
from src.sparks.progression import ProgressionService
from src.sparks.records import BattleRecord
from src.sparks.repository import SparkRepository, SparkTransaction
from src.sparks.runtime import Clock, SeededRandom, new_id, new_seed
from src.sparks.situation import SituationViewBuilder

MODES = ("manual", "autonomous")


@dataclass(frozen=True)
class CoordinatorSettings:
    emblem_prompt_seconds: float


class RoundCoordinator:
    def __init__(
        self, repository: SparkRepository, writer: IdempotentWriter, catalog: Catalog, engine: BattleEngine,
        decider: ActionDecider, situation_views: SituationViewBuilder, emblem_picker: EmblemPicker,
        progression: ProgressionService, battle_views: BattleViewBuilder, clock: Clock, settings: CoordinatorSettings,
    ) -> None:
        self._repo, self._writer, self._catalog, self._engine = repository, writer, catalog, engine
        self._decider, self._situation_views = decider, situation_views
        self._emblem_picker, self._progression, self._battle_views = emblem_picker, progression, battle_views
        self._clock, self._settings = clock, settings
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, battle_id: str) -> asyncio.Lock:
        return self._locks.setdefault(battle_id, asyncio.Lock())

    # -- reading -------------------------------------------------------------------

    async def _load(self, owner: str, battle_id: str) -> tuple[BattleRecord, dict[str, int]]:
        async with self._repo.transaction() as tx:
            record = await tx.get_battle(owner, battle_id)
            if record is None:
                raise NotFound("no such battle")
            return record, await tx.emblem_counts(owner)

    async def view(self, owner: str, battle_id: str) -> dict[str, Any]:
        record, emblems = await self._load(owner, battle_id)
        return self._battle_views.build(record, emblems, self._clock.now())

    @staticmethod
    def _require(record: BattleRecord, *, round: int, revision: int, phase: str | tuple[str, ...] = "choosing") -> None:
        if record.status != "active":
            raise BattleFinished("this battle is over")
        phases = (phase,) if isinstance(phase, str) else phase
        if record.phase not in phases:
            raise WrongPhase(f"this battle is in the {record.phase} phase")
        if record.state.round != round or record.revision != revision:
            raise StaleBattle("the battle moved on; reload it and try again")

    # -- starting ------------------------------------------------------------------

    async def start(
        self, owner: str, key: str, *, encounter_id: str, species_id: str, preset_slot: int | None,
        mode: str, emblem_limit: str | None,
    ) -> dict[str, Any]:
        payload = {"encounter": encounter_id, "species": species_id, "slot": preset_slot, "mode": mode, "limit": emblem_limit}
        if mode not in MODES:
            raise InvalidRequest(f"mode must be one of {', '.join(MODES)}")
        try:
            if emblem_limit is not None:
                self._catalog.tier(emblem_limit)
            self._catalog.species(species_id)
        except CatalogError as error:
            raise InvalidRequest(str(error)) from error
        if mode == "autonomous" and (emblem_limit is None or preset_slot is None):
            raise InvalidRequest("autonomous play needs a personality preset and an EMBLEM tier limit")

        async def work(tx: SparkTransaction) -> dict[str, Any]:
            encounter = await tx.get_encounter(owner, encounter_id)
            if encounter is None:
                raise NotFound("no such encounter")
            if encounter.status != "pending":
                raise WrongPhase(f"this encounter is already {encounter.status}")
            spark = await tx.get_spark(owner, species_id)
            if spark is None:
                raise NotFound("you do not own that species")
            now = self._clock.now()
            if spark.faint_until is not None and spark.faint_until > now:
                raise SparkFainted(f"that Spark is fainted for another {spark.faint_until - now:.0f} seconds")
            instances = ()
            if preset_slot is not None:
                preset = await tx.get_preset(owner, species_id, preset_slot)
                ids = list(preset.instance_ids) if preset else []
                by_id = {p.id: p.instance() for p in await tx.get_personalities(owner, species_id, ids)}
                instances = tuple(by_id[i] for i in ids if i in by_id)  # frozen for the whole battle
            if mode == "autonomous" and not instances:
                raise InvalidRequest("that preset has no personalities; equip at least one")
            setup = BattleSetup(
                self._engine.build_fighter(PLAYER, species_id, self._catalog.tier_for_copies(species_id, spark.copies), spark.level),
                self._engine.build_fighter(WILD, encounter.species_id, encounter.tier_id, encounter.level),
            )
            record = BattleRecord(
                id=new_id(), owner=owner, encounter_id=encounter.id, status="active", phase="choosing", mode=mode,
                revision=1, setup=setup, state=self._engine.start_state(setup), player_personalities=instances,
                wild_personalities=encounter.wild_personalities, emblem_limit=emblem_limit, rng_seed=new_seed(),
                rng_counter=0, created_at=now, updated_at=now,
            )
            await tx.add_battle(record)
            await tx.set_encounter_status(encounter.id, "started")
            return self._battle_views.build(record, await tx.emblem_counts(owner), now)

        return await self._writer.commit(owner, key, "battle.start", payload, work)

    # -- deciding ------------------------------------------------------------------

    async def _decide(self, record: BattleRecord, side: str, rng: SeededRandom, *, can_collect: bool) -> Decision:
        instances = record.player_personalities if side == PLAYER else record.wild_personalities
        return await self._decider.decide(record.setup, record.state, side, instances, rng, can_collect=can_collect)

    # -- committing ----------------------------------------------------------------

    async def _commit_round(
        self, owner: str, key: str, operation: str, payload: dict[str, Any], record: BattleRecord,
        player_action: Action, wild_action: Action, rng: SeededRandom, audits: list[dict[str, Any]],
    ) -> dict[str, Any]:
        async def work(tx: SparkTransaction) -> dict[str, Any]:
            fresh = await tx.get_battle(owner, record.id)
            if fresh is None or fresh.revision != record.revision or fresh.status != "active":
                raise StaleBattle("the battle moved on; reload it and try again")
            emblems = await tx.emblem_counts(owner)
            if player_action.kind == "catch" and emblems.get(player_action.emblem_tier, 0) < 1:
                raise InsufficientEmblems(f"you have no {player_action.emblem_tier} EMBLEM")
            outcome = self._engine.resolve_round(fresh.setup, fresh.state, player_action, wild_action, rng)
            now = self._clock.now()
            updated = replace(fresh, state=outcome.state, revision=fresh.revision + 1, phase="choosing", pending=None, updated_at=now)
            if outcome.emblem_consumed:
                await tx.add_emblems(owner, outcome.emblem_consumed, -1)
            await tx.add_round(fresh.id, fresh.state.round, {
                "actions": {PLAYER: player_action.to_dict(), WILD: wild_action.to_dict()}, "audit": audits,
                "draws": list(outcome.draws), "events": list(outcome.events), "terminal": outcome.terminal,
            })
            if outcome.terminal:
                result = await self._progression.apply_terminal(tx, updated, outcome.terminal, rng)
                updated = replace(updated, status="terminal", phase="terminal", result=result)
            updated = replace(updated, rng_counter=rng.counter)
            await tx.save_battle(updated, fresh.revision)
            return self._battle_views.build(updated, await tx.emblem_counts(owner), now)

        return await self._writer.commit(owner, key, operation, payload, work)

    # -- manual play ---------------------------------------------------------------

    async def submit_action(
        self, owner: str, key: str, battle_id: str, *, round: int, revision: int, action: dict[str, Any]
    ) -> dict[str, Any]:
        payload = {"battle": battle_id, "round": round, "revision": revision, "action": action}
        cached = await self._writer.lookup(owner, key, "battle.action", payload)
        if cached is not None:
            return cached
        async with self._lock(battle_id):
            record, emblems = await self._load(owner, battle_id)
            self._require(record, round=round, revision=revision)
            if record.mode != "manual":
                raise WrongPhase("this battle is autonomous; switch to manual or use advance")
            legal = self._engine.legal_actions(record.setup, record.state, PLAYER, can_collect=bool(emblems))
            try:
                player_action = self._engine.resolve_action(legal, action)
            except (ActionError, CatalogError) as error:
                raise InvalidRequest(str(error)) from error
            if player_action.kind == "catch" and emblems.get(player_action.emblem_tier, 0) < 1:
                raise InsufficientEmblems(f"you have no {player_action.emblem_tier} EMBLEM")
            rng = SeededRandom(record.rng_seed, record.rng_counter)
            wild = await self._decide(record, WILD, rng, can_collect=False)  # decided without sight of player_action
            return await self._commit_round(
                owner, key, "battle.action", payload, record, player_action, wild.action, rng, [wild.audit])

    # -- autonomous play -----------------------------------------------------------

    async def advance(self, owner: str, key: str, battle_id: str, *, round: int, revision: int) -> dict[str, Any]:
        """Play one autonomous round, or settle an EMBLEM prompt whose time is up."""
        payload = {"battle": battle_id, "round": round, "revision": revision}
        cached = await self._writer.lookup(owner, key, "battle.advance", payload)
        if cached is not None:
            return cached
        async with self._lock(battle_id):
            record, emblems = await self._load(owner, battle_id)
            self._require(record, round=round, revision=revision, phase=("choosing", "awaiting_emblem"))
            if record.mode != "autonomous":
                raise WrongPhase("this battle is manual; choose an action")
            now = self._clock.now()
            if record.phase == "awaiting_emblem":
                if now < record.pending["deadline"]:
                    return self._battle_views.build(record, emblems, now)  # still the player's turn to answer
                return await self._settle_prompt(owner, key, payload, record, emblems)
            rng = SeededRandom(record.rng_seed, record.rng_counter)
            permitted = self._battle_views.permitted_tiers(emblems, record.emblem_limit)
            player = await self._decide(record, PLAYER, rng, can_collect=bool(permitted))
            wild = await self._decide(record, WILD, rng, can_collect=False)
            if player.action.kind == "catch":
                return await self._open_prompt(owner, key, payload, record, wild, player, rng)
            return await self._commit_round(
                owner, key, "battle.advance", payload, record, player.action, wild.action, rng, [player.audit, wild.audit])

    async def _open_prompt(self, owner, key, payload, record, wild: Decision, player: Decision, rng) -> dict[str, Any]:
        """The player's Spark wants to CATCH: keep both private choices and ask for an EMBLEM."""
        async def work(tx: SparkTransaction) -> dict[str, Any]:
            fresh = await tx.get_battle(owner, record.id)
            if fresh is None or fresh.revision != record.revision:
                raise StaleBattle("the battle moved on; reload it and try again")
            now = self._clock.now()
            pending = {
                "wild_action": wild.action.to_dict(), "audit": [player.audit, wild.audit],
                "deadline": now + self._settings.emblem_prompt_seconds,
            }
            updated = replace(fresh, phase="awaiting_emblem", pending=pending, revision=fresh.revision + 1,
                              rng_counter=rng.counter, updated_at=now)
            await tx.save_battle(updated, fresh.revision)
            return self._battle_views.build(updated, await tx.emblem_counts(owner), now)

        return await self._writer.commit(owner, key, "battle.advance", payload, work)

    async def _settle_prompt(self, owner, key, payload, record: BattleRecord, emblems: dict[str, int]) -> dict[str, Any]:
        """The prompt expired: Laya picks within the player's limit, else basic ATTACK."""
        permitted = self._battle_views.permitted_tiers(emblems, record.emblem_limit)
        wild_state = record.state.wild
        chances = {t: self._engine.capture_chance(t, record.setup.wild, wild_state) for t in permitted}
        tier = await self._emblem_picker.pick(self._situation_views.build(record.setup, record.state, PLAYER), chances)
        player_action = (
            Action("catch", "INTERCEPT", emblem_tier=tier) if tier in chances else Action("attack", "ATTACK")
        )
        rng = SeededRandom(record.rng_seed, record.rng_counter)
        wild_action = Action.from_dict(record.pending["wild_action"])
        return await self._commit_round(
            owner, key, "battle.advance", payload, record, player_action, wild_action, rng, record.pending["audit"])

    async def answer_emblem(
        self, owner: str, key: str, battle_id: str, *, round: int, revision: int, tier: str
    ) -> dict[str, Any]:
        """The player's own EMBLEM choice (any owned tier, even above the autonomous limit)."""
        payload = {"battle": battle_id, "round": round, "revision": revision, "tier": tier}
        cached = await self._writer.lookup(owner, key, "battle.emblem", payload)
        if cached is not None:
            return cached
        async with self._lock(battle_id):
            record, emblems = await self._load(owner, battle_id)
            self._require(record, round=round, revision=revision, phase="awaiting_emblem")
            if self._clock.now() >= record.pending["deadline"]:
                raise DeadlinePassed("the prompt has expired; advance the battle instead")
            try:
                self._catalog.tier(tier)
            except CatalogError as error:
                raise InvalidRequest(str(error)) from error
            if emblems.get(tier, 0) < 1:
                raise InsufficientEmblems(f"you have no {tier} EMBLEM")
            rng = SeededRandom(record.rng_seed, record.rng_counter)
            return await self._commit_round(
                owner, key, "battle.emblem", payload, record, Action("catch", "INTERCEPT", emblem_tier=tier),
                Action.from_dict(record.pending["wild_action"]), rng, record.pending["audit"])

    # -- mode and forfeit ----------------------------------------------------------

    async def set_mode(
        self, owner: str, key: str, battle_id: str, *, round: int, revision: int, mode: str, emblem_limit: str | None
    ) -> dict[str, Any]:
        """Switch between manual and autonomous before the next action is locked."""
        payload = {"battle": battle_id, "round": round, "revision": revision, "mode": mode, "limit": emblem_limit}
        if mode not in MODES:
            raise InvalidRequest(f"mode must be one of {', '.join(MODES)}")
        async with self._lock(battle_id):
            async def work(tx: SparkTransaction) -> dict[str, Any]:
                record = await tx.get_battle(owner, battle_id)
                if record is None:
                    raise NotFound("no such battle")
                self._require(record, round=round, revision=revision)
                limit = emblem_limit or record.emblem_limit
                if mode == "autonomous" and (not record.player_personalities or limit is None):
                    raise InvalidRequest("autonomous play needs equipped personalities and an EMBLEM tier limit")
                try:
                    if limit is not None:
                        self._catalog.tier(limit)
                except CatalogError as error:
                    raise InvalidRequest(str(error)) from error
                now = self._clock.now()
                updated = replace(record, mode=mode, emblem_limit=limit, revision=record.revision + 1, updated_at=now)
                await tx.save_battle(updated, record.revision)
                return self._battle_views.build(updated, await tx.emblem_counts(owner), now)

            return await self._writer.commit(owner, key, "battle.mode", payload, work)

    async def forfeit(self, owner: str, key: str, battle_id: str) -> dict[str, Any]:
        """End the battle as a loss. Serialized with resolution, so a finished result is never replaced."""
        async with self._lock(battle_id):
            async def work(tx: SparkTransaction) -> dict[str, Any]:
                record = await tx.get_battle(owner, battle_id)
                if record is None:
                    raise NotFound("no such battle")
                if record.status != "active":
                    raise BattleFinished("this battle is already over")
                rng = SeededRandom(record.rng_seed, record.rng_counter)
                result = await self._progression.apply_terminal(tx, record, "forfeited", rng)
                now = self._clock.now()
                updated = replace(record, status="terminal", phase="terminal", pending=None, result=result,
                                  revision=record.revision + 1, rng_counter=rng.counter, updated_at=now)
                await tx.save_battle(updated, record.revision)
                return self._battle_views.build(updated, await tx.emblem_counts(owner), now)

            return await self._writer.commit(owner, key, "battle.forfeit", {"battle": battle_id}, work)
