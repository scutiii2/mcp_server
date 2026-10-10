"""Builds the service graph over a temporary database for service-level tests."""

from __future__ import annotations

import asyncio
import itertools
import json
from pathlib import Path

from src.sparks.catalog import Catalog
from src.sparks.collection import CollectionService
from src.sparks.encounters import EncounterService
from src.sparks.engine import BattleEngine
from src.sparks.idempotency import IdempotentWriter
from src.sparks.progression import ProgressionService
from src.sparks.repository import SqliteSparkRepository
from src.sparks.runtime import RandomSource, SeededRandom
from src.sparks.shop import ShopService
from tests.sparks.helpers import FixedClock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = PROJECT_ROOT / "configs" / "spark_catalog.json"
SPARKS_PATH = PROJECT_ROOT / "sparks"
CATALOG = Catalog.load(CATALOG_PATH, SPARKS_PATH)


def load_raw() -> dict:
    """The shipped catalog as the raw dict Catalog() takes: the rules plus the Sparks, by folder name."""
    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    raw["sparks"] = [json.loads(f.read_text(encoding="utf-8")) for f in sorted(SPARKS_PATH.glob("*/catalog.json"), key=lambda f: f.parent.name)]
    return raw
COOLDOWN = 30.0
FAINT = 300.0
PROMPT = 5.0
_KEYS = itertools.count(1)  # unique across Env instances, so a restarted Env never reuses a key


class Env:
    def __init__(self, db_path: Path, rng: RandomSource | None = None) -> None:
        self.catalog = CATALOG
        self.clock = FixedClock()
        self.rng = rng or SeededRandom(11)
        self.repo = SqliteSparkRepository(db_path)
        self.writer = IdempotentWriter(self.repo, self.clock)
        self.engine = BattleEngine(CATALOG)
        self.progression = ProgressionService(CATALOG, self.clock, FAINT)
        self.collection = CollectionService(self.repo, self.writer, CATALOG, self.clock, self.rng, COOLDOWN)
        self.encounters = EncounterService(self.repo, self.writer, CATALOG, self.clock, self.rng, COOLDOWN)
        self.shop = ShopService(self.writer, CATALOG, self.progression)

    def coordinator(self, policy=None, reader=None, picker=None, laya=None):
        """A RoundCoordinator over this Env. Imports are local: the coordinator is built in a later task."""
        from src.laya_client import LayaClient
        from src.sparks.battle_view import BattleViewBuilder
        from src.sparks.coordinator import CoordinatorSettings, RoundCoordinator
        from src.sparks.decider import ActionDecider
        from src.sparks.emblem_picker import LayaEmblemPicker
        from src.sparks.policy import ActionPolicy, Mood
        from src.sparks.situation import HeuristicSituationReader, SituationViewBuilder
        from tests.fake_laya import FakeEngine

        views = BattleViewBuilder(self.engine, CATALOG)
        client = LayaClient(laya or FakeEngine(fail=True))
        situation_views = SituationViewBuilder(self.engine)
        decider = ActionDecider(
            CATALOG, self.engine, policy or ActionPolicy(CATALOG.policy), Mood(CATALOG),
            reader or HeuristicSituationReader(CATALOG.policy.default_aggression), situation_views,
        )
        return RoundCoordinator(
            self.repo, self.writer, CATALOG, self.engine, decider, situation_views,
            picker or LayaEmblemPicker(client), self.progression, views, self.clock, CoordinatorSettings(PROMPT),
        )

    def key(self) -> str:
        return f"key-{next(_KEYS)}"

    async def start_player(self, owner: str = "ann", starter: str = "guardian") -> dict:
        return await self.collection.initialize(owner, self.key(), starter)

    async def give(self, owner: str = "ann", insignia: int = 0, **sparks) -> None:
        """Test setup: add Insignia and/or replace Spark records directly."""
        async with self.repo.transaction() as tx:
            if insignia:
                await tx.add_insignia(owner, insignia)
            for record in sparks.values():
                await tx.put_spark(record)

    async def close(self) -> None:
        await self.repo.close()


def run(coro):
    return asyncio.run(coro)
