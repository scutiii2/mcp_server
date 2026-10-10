"""The versioned game catalog: Sparks, abilities, tiers, personalities, the
economy and the action-policy numbers. Loaded and validated once at startup.

Balance numbers are initial values; changing the file affects future battles
only (a battle freezes its fighters when it starts).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from src.sparks.models import ABILITY_CATEGORIES, CATEGORIES, AbilitySpec, PassiveSpec

ABILITY_UNLOCK_LEVELS = (1, 10, 20)
# The catalog always sits in the same place in the project tree, so it has no config entry.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = PROJECT_ROOT / "configs" / "spark_catalog.json"
SPARKS_PATH = PROJECT_ROOT / "sparks"
SPARK_FILE = "catalog.json"
STATS = ("hp", "essence", "speed")


class CatalogError(ValueError):
    """The catalog file is missing a field or holds an inconsistent value."""


@dataclass(frozen=True)
class TierSpec:
    id: str
    stat_multiplier: float
    capture_multiplier: float
    hp_floor: float
    emblem_strength: int
    emblem_price: int
    encounter_probability: float
    copy_threshold: int | None  # None = outside the copy-based progression (Forbidden)
    copy_reward: int


@dataclass(frozen=True)
class SparkSpec:
    id: str
    name: str
    starter: bool
    forbidden: bool
    base_price: int
    base: Mapping[str, float]
    growth: Mapping[str, float]
    passive: PassiveSpec
    abilities: tuple[AbilitySpec, ...]


@dataclass(frozen=True)
class PersonalitySpec:
    id: str
    categories: tuple[str, ...]


@dataclass(frozen=True)
class PolicySpec:
    gain: float
    off_mood_factor: float
    repeat_factor: float
    floor: float
    default_aggression: float
    default_flee_share: float
    coefficients: Mapping[str, Mapping[str, float]]


@dataclass(frozen=True)
class Economy:
    xp_reward_factor: float
    insignia_reward_factor: float
    sale_level_bonus: float
    purchase_factor: float
    forbidden_copy_cap: int
    base_capture_resistance: float
    starter_emblems: Mapping[str, int]
    starter_personality_tier: int
    encounter_level_window: int
    personality_tier_probabilities: tuple[float, ...]


@dataclass(frozen=True)
class Levels:
    regular_cap: int
    forbidden_cap: int
    xp_per_level: int


def _require(raw: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in raw:
        raise CatalogError(f"{where}: missing {key!r}")
    return raw[key]


def _ability(raw: Mapping[str, Any], spark_id: str) -> AbilitySpec:
    where = f"spark {spark_id!r} ability {raw.get('id')!r}"
    ability = AbilitySpec(
        id=_require(raw, "id", where), name=_require(raw, "name", where),
        unlock_level=_require(raw, "unlock_level", where), category=_require(raw, "category", where),
        percentage=float(_require(raw, "percentage", where)), cooldown=_require(raw, "cooldown", where),
        stat=raw.get("stat"), duration=raw.get("duration"),
    )
    if ability.category not in ABILITY_CATEGORIES:
        raise CatalogError(f"{where}: category must be one of {ABILITY_CATEGORIES}")
    if ability.cooldown < 1 or ability.percentage <= 0:
        raise CatalogError(f"{where}: cooldown must be at least 1 and percentage positive")
    if ability.category == "SUPPORT" and (ability.stat not in ("essence", "speed") or not ability.duration or ability.duration < 1):
        raise CatalogError(f"{where}: SUPPORT needs a stat (essence or speed) and a duration of at least 1")
    return ability


def _spark_spec(raw: Mapping[str, Any]) -> SparkSpec:
    sid = _require(raw, "id", "spark")
    where = f"spark {sid!r}"
    base, growth = _require(raw, "base", where), _require(raw, "growth", where)
    if set(base) != set(STATS) or set(growth) != set(STATS):
        raise CatalogError(f"{where}: base and growth need exactly hp, essence and speed")
    abilities = tuple(_ability(a, sid) for a in _require(raw, "abilities", where))
    if tuple(a.unlock_level for a in abilities) != ABILITY_UNLOCK_LEVELS:
        raise CatalogError(f"{where}: abilities must unlock at levels {ABILITY_UNLOCK_LEVELS}")
    passive = _require(raw, "passive", where)
    return SparkSpec(
        id=sid, name=_require(raw, "name", where), starter=bool(raw.get("starter")), forbidden=bool(raw.get("forbidden")),
        base_price=_require(raw, "base_price", where), base=dict(base), growth=dict(growth),
        passive=PassiveSpec(_require(passive, "kind", f"{where} passive"), dict(passive.get("params", {}))), abilities=abilities,
    )


class Catalog:
    def __init__(self, raw: Mapping[str, Any]) -> None:
        try:
            self._build(raw)
        except CatalogError:
            raise
        except (TypeError, KeyError, AttributeError, ValueError, IndexError) as error:
            raise CatalogError(f"malformed catalog: {type(error).__name__}: {error}") from error

    def _build(self, raw: Mapping[str, Any]) -> None:
        if not isinstance(raw, Mapping):
            raise CatalogError("catalog must be an object")
        self.version: int = _require(raw, "version", "catalog")
        self.tiers: tuple[TierSpec, ...] = tuple(TierSpec(**t) for t in _require(raw, "tiers", "catalog"))
        self.levels = Levels(**_require(raw, "levels", "catalog"))
        economy = dict(_require(raw, "economy", "catalog"))
        economy["personality_tier_probabilities"] = tuple(economy["personality_tier_probabilities"])
        self.economy = Economy(**economy)
        personalities = [PersonalitySpec(p["id"], tuple(p["categories"])) for p in _require(raw, "personalities", "catalog")]
        self.personalities: dict[str, PersonalitySpec] = {p.id: p for p in personalities}
        if len(self.personalities) != len(personalities):
            raise CatalogError("personality ids must be unique")
        policy = dict(_require(raw, "policy", "catalog"))
        self.policy = PolicySpec(**policy)
        specs = [_spark_spec(s) for s in _require(raw, "sparks", "catalog")]
        self._sparks = {s.id: s for s in specs}
        if len(self._sparks) != len(specs):
            raise CatalogError("spark ids must be unique")
        # Action keys and cooldowns key on the ability id, so it is unique across Sparks.
        ability_ids = [a.id for s in specs for a in s.abilities]
        if len(set(ability_ids)) != len(ability_ids):
            raise CatalogError("ability ids must be unique across all Sparks")
        self._tiers = {t.id: t for t in self.tiers}
        self._validate()

    # -- validation ----------------------------------------------------------------

    def _validate(self) -> None:
        if len(self._tiers) != len(self.tiers):
            raise CatalogError("tier ids must be unique")
        if len(self.tiers) < 2:
            raise CatalogError("need at least one regular tier plus the Forbidden tier")
        for tier in self.tiers:
            if tier.stat_multiplier <= 0 or tier.capture_multiplier <= 0 or tier.encounter_probability < 0:
                raise CatalogError(f"tier {tier.id!r}: multipliers must be positive and probability non-negative")
        for spec in self._sparks.values():
            if spec.base_price <= 0:
                raise CatalogError(f"spark {spec.id!r}: base_price must be positive")
        if not math.isclose(sum(t.encounter_probability for t in self.tiers), 1.0, abs_tol=1e-9):
            raise CatalogError("tier encounter probabilities must sum to 1")
        if not math.isclose(sum(self.economy.personality_tier_probabilities), 1.0, abs_tol=1e-9):
            raise CatalogError("personality tier probabilities must sum to 1")
        forbidden_tiers = [t for t in self.tiers if t.copy_threshold is None]
        if len(forbidden_tiers) != 1 or self.tiers[-1] is not forbidden_tiers[0]:
            raise CatalogError("exactly one tier, the last, may have copy_threshold null (Forbidden)")
        thresholds = [t.copy_threshold for t in self.regular_tiers]
        if thresholds[0] != 0 or thresholds != sorted(set(thresholds)):
            raise CatalogError("regular copy thresholds must start at 0 and strictly increase")
        if len([s for s in self._sparks.values() if s.starter]) != 3:
            raise CatalogError("exactly three Sparks must be starters")
        if len([s for s in self._sparks.values() if s.forbidden]) != 1:
            raise CatalogError("exactly one Spark must be Forbidden")
        if any(s.starter and s.forbidden for s in self._sparks.values()):
            raise CatalogError("a starter cannot be Forbidden")
        for personality in self.personalities.values():
            if not personality.categories or any(c not in CATEGORIES for c in personality.categories):
                raise CatalogError(f"personality {personality.id!r} has invalid categories")
        for category in CATEGORIES:
            if category not in self.policy.coefficients:
                raise CatalogError(f"policy coefficients missing for {category}")
        for tier_id in self.economy.starter_emblems:
            self.tier(tier_id)

    # -- lookups -------------------------------------------------------------------

    @classmethod
    def load(cls, catalog_path: Path = CATALOG_PATH, sparks_path: Path = SPARKS_PATH) -> "Catalog":
        """Global rules from one file, the Sparks from one folder each (sorted by
        folder name, so the Spark order and every draw over it stay deterministic)."""
        try:
            raw = json.loads(catalog_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise CatalogError(f"cannot load catalog {catalog_path}: {error}") from error
        if not isinstance(raw, dict):
            raise CatalogError(f"cannot load catalog {catalog_path}: must be an object")
        raw["sparks"] = cls._load_sparks(sparks_path)
        return cls(raw)

    @staticmethod
    def _load_sparks(sparks_path: Path) -> list[Any]:
        if not sparks_path.is_dir():
            raise CatalogError(f"sparks directory {sparks_path} does not exist")
        folders = sorted((d for d in sparks_path.iterdir() if (d / SPARK_FILE).is_file()), key=lambda d: d.name)
        if not folders:
            raise CatalogError(f"sparks directory {sparks_path} holds no <spark>/{SPARK_FILE} files")
        sparks: list[Any] = []
        for folder in folders:
            label = f"{folder.name}/{SPARK_FILE}"
            try:
                spark = json.loads((folder / SPARK_FILE).read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise CatalogError(f"cannot load spark file {label}: {error}") from error
            if not isinstance(spark, dict) or spark.get("id") != folder.name:
                found = spark.get("id") if isinstance(spark, dict) else spark
                raise CatalogError(f"spark file {label}: id {found!r} must equal the folder name {folder.name!r}")
            sparks.append(spark)
        return sparks

    @property
    def regular_tiers(self) -> tuple[TierSpec, ...]:
        return self.tiers[:-1]

    @property
    def forbidden_tier(self) -> TierSpec:
        return self.tiers[-1]

    def tier(self, tier_id: str) -> TierSpec:
        try:
            return self._tiers[tier_id]
        except KeyError:
            raise CatalogError(f"unknown tier {tier_id!r}") from None

    def spark(self, spark_id: str) -> SparkSpec:
        try:
            return self._sparks[spark_id]
        except KeyError:
            raise CatalogError(f"unknown spark {spark_id!r}") from None

    def has_spark(self, spark_id: str) -> bool:
        return spark_id in self._sparks

    def all_sparks(self) -> tuple[SparkSpec, ...]:
        return tuple(self._sparks.values())

    def regular_sparks(self) -> tuple[SparkSpec, ...]:
        return tuple(s for s in self._sparks.values() if not s.forbidden)

    def starter_sparks(self) -> tuple[SparkSpec, ...]:
        return tuple(s for s in self._sparks.values() if s.starter)

    def forbidden_spark(self) -> SparkSpec:
        return next(s for s in self._sparks.values() if s.forbidden)

    def level_cap(self, spark_id: str) -> int:
        return self.levels.forbidden_cap if self.spark(spark_id).forbidden else self.levels.regular_cap

    def stat_value(self, spark_id: str, level: int, tier_id: str, stat: str) -> int:
        """Full-precision stat, then floored to a positive whole number."""
        spec = self.spark(spark_id)
        raw = (spec.base[stat] + spec.growth[stat] * (level - 1)) * self.tier(tier_id).stat_multiplier
        return max(1, math.floor(raw + 1e-9))

    def tier_for_copies(self, spark_id: str, copies: int) -> str:
        """Highest regular tier whose threshold the copy count meets; Forbidden is fixed.
        A negative count clamps to the lowest tier."""
        if self.spark(spark_id).forbidden:
            return self.forbidden_tier.id
        reached = [t for t in self.regular_tiers if copies >= t.copy_threshold]
        return (reached or self.regular_tiers[:1])[-1].id

    def sale_value(self, spark_id: str, tier_id: str, level: int) -> int:
        """Insignia for selling one copy of a Spark at this tier and level."""
        spec = self.spark(spark_id)
        factor = 1 + self.economy.sale_level_bonus * (level - 1)
        return math.floor(spec.base_price * self.tier(tier_id).stat_multiplier * factor + 1e-9)
