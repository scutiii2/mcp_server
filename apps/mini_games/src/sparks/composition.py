"""The composition root: builds the whole Emberlings object graph once at startup."""

from __future__ import annotations

from src.config import AppConfig
from src.laya_client import LayaClient
from src.sparks.api import SparkServices
from src.sparks.battle_view import BattleViewBuilder
from src.sparks.catalog import Catalog
from src.sparks.collection import CollectionService
from src.sparks.coordinator import CoordinatorSettings, RoundCoordinator
from src.sparks.decider import ActionDecider
from src.sparks.emblem_picker import LayaEmblemPicker
from src.sparks.encounters import EncounterService
from src.sparks.engine import BattleEngine
from src.sparks.idempotency import IdempotentWriter
from src.sparks.policy import ActionPolicy, Mood
from src.sparks.progression import ProgressionService
from src.sparks.repository import SparkRepository, SqliteSparkRepository
from src.sparks.runtime import Clock, RandomSource, SystemClock, SystemRandom
from src.sparks.shop import ShopService
from src.sparks.situation import (
    FallbackSituationReader,
    HeuristicSituationReader,
    LayaPartialSituationReader,
    SituationReader,
    SituationViewBuilder,
)


def build_spark_services(
    config: AppConfig, laya: LayaClient, catalog: Catalog | None = None, repository: SparkRepository | None = None,
    clock: Clock | None = None, rng: RandomSource | None = None,
) -> SparkServices:
    """Everything is injected, so tests and other front ends can swap any part."""
    catalog = catalog or Catalog.load(config.catalog_path, config.sparks_path)
    clock, rng = clock or SystemClock(), rng or SystemRandom()
    repository = repository or SqliteSparkRepository(config.database_path)
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
    return SparkServices(
        catalog=catalog,
        collection=CollectionService(repository, writer, catalog, clock, rng, config.encounter_cooldown_seconds),
        encounters=EncounterService(repository, writer, catalog, clock, rng, config.encounter_cooldown_seconds),
        shop=ShopService(writer, catalog, progression),
        coordinator=coordinator,
    )
