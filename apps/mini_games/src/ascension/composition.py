"""The composition root: builds the whole Ascension object graph once at startup."""

from __future__ import annotations

from src.config import AppConfig
from src.laya_client import LayaClient
from src.ascension.api import AscendedServices
from src.ascension.battle_view import BattleViewBuilder
from src.ascension.catalog import Catalog
from src.ascension.collection import CollectionService
from src.ascension.coordinator import CoordinatorSettings, RoundCoordinator
from src.ascension.decider import ActionDecider
from src.ascension.emblem_picker import LayaEmblemPicker
from src.ascension.encounters import EncounterService
from src.ascension.engine import BattleEngine
from src.ascension.idempotency import IdempotentWriter
from src.ascension.policy import ActionPolicy, Mood
from src.ascension.progression import ProgressionService
from src.ascension.repository import AscendedRepository, SqliteAscendedRepository
from src.ascension.runtime import Clock, RandomSource, SystemClock, SystemRandom
from src.ascension.shop import ShopService
from src.ascension.situation import (
    FallbackSituationReader,
    HeuristicSituationReader,
    LayaPartialSituationReader,
    SituationReader,
    SituationViewBuilder,
)


def build_ascended_services(
    config: AppConfig, laya: LayaClient, catalog: Catalog | None = None, repository: AscendedRepository | None = None,
    clock: Clock | None = None, rng: RandomSource | None = None,
) -> AscendedServices:
    """Everything is injected, so tests and other front ends can swap any part."""
    catalog = catalog or Catalog.load()
    clock, rng = clock or SystemClock(), rng or SystemRandom()
    repository = repository or SqliteAscendedRepository(config.database_path)
    writer = IdempotentWriter(repository, clock)
    engine = BattleEngine(catalog)
    progression = ProgressionService(catalog, clock, config.faint_seconds)
    heuristic = HeuristicSituationReader(catalog.policy.default_aggression)
    reader: SituationReader = (
        FallbackSituationReader(LayaPartialSituationReader(laya), heuristic) if config.situation_source == "laya" else heuristic
    )
    situation_views = SituationViewBuilder(engine)
    decider = ActionDecider(catalog, engine, ActionPolicy(catalog.policy), Mood(catalog), reader, situation_views)
    coordinator = RoundCoordinator(
        repository, writer, catalog, engine, decider, situation_views, LayaEmblemPicker(laya), progression,
        BattleViewBuilder(engine, catalog), clock, CoordinatorSettings(config.emblem_prompt_seconds),
    )
    return AscendedServices(
        catalog=catalog,
        collection=CollectionService(repository, writer, catalog, clock, rng, config.encounter_cooldown_seconds),
        encounters=EncounterService(repository, writer, catalog, clock, rng, config.encounter_cooldown_seconds),
        shop=ShopService(writer, catalog, progression),
        coordinator=coordinator,
    )
