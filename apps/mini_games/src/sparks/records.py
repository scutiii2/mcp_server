"""Rows as immutable values, so services never touch SQL or JSON text."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.sparks.models import BattleSetup, BattleState, PersonalityInstance


@dataclass(frozen=True)
class PlayerRecord:
    owner: str
    insignia: int
    last_roll_at: float | None
    created_at: float


@dataclass(frozen=True)
class SparkRecord:
    owner: str
    spark_id: str
    copies: int
    level: int
    xp: int
    faint_until: float | None = None


@dataclass(frozen=True)
class PersonalityRecord:
    id: str
    owner: str
    spark_id: str
    type_id: str
    tier: int
    created_at: float
    seq: int = 0  # assigned by the database

    def instance(self) -> PersonalityInstance:
        return PersonalityInstance(self.id, self.type_id, self.tier)


@dataclass(frozen=True)
class PresetRecord:
    owner: str
    spark_id: str
    slot: int
    instance_ids: tuple[str, ...]


@dataclass(frozen=True)
class EncounterRecord:
    id: str
    owner: str
    spark_id: str
    tier_id: str
    level: int
    status: str  # pending, declined, started or expired
    wild_personalities: tuple[PersonalityInstance, ...]  # hidden until a capture
    created_at: float


@dataclass(frozen=True)
class BattleRecord:
    id: str
    owner: str
    encounter_id: str
    status: str  # active or terminal
    phase: str  # choosing, awaiting_emblem or terminal
    mode: str  # manual or autonomous
    revision: int
    setup: BattleSetup
    state: BattleState
    player_personalities: tuple[PersonalityInstance, ...]  # frozen from the preset at start
    wild_personalities: tuple[PersonalityInstance, ...]
    emblem_limit: str | None
    rng_seed: int
    rng_counter: int
    created_at: float
    updated_at: float
    pending: dict[str, Any] | None = None  # private: wild action and EMBLEM prompt while awaiting_emblem
    result: dict[str, Any] | None = None


@dataclass(frozen=True)
class IdempotencyRecord:
    request_hash: str
    response: dict[str, Any] = field(default_factory=dict)
