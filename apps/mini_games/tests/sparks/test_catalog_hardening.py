import copy
import json
from pathlib import Path

import pytest

from src.sparks.catalog import Catalog, CatalogError

CATALOG_PATH = Path(__file__).resolve().parents[2] / "configs" / "spark_catalog.json"


@pytest.fixture(scope="module")
def raw():
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def _mutated(raw, mutate):
    data = copy.deepcopy(raw)
    mutate(data)
    return data


@pytest.mark.parametrize("mutate,message", [
    (lambda d: d["species"][1].update(id=d["species"][0]["id"]), "species ids must be unique"),
    (lambda d: d["personalities"][1].update(id=d["personalities"][0]["id"]), "personality ids must be unique"),
    (lambda d: d["tiers"][1].update(id=d["tiers"][0]["id"]), "tier ids must be unique"),
    (lambda d: d["species"][1]["abilities"][0].update(id=d["species"][0]["abilities"][0]["id"]), "ability ids must be unique"),
    (lambda d: d["tiers"][0].update(stat_multiplier=0), "must be positive"),
    (lambda d: d["tiers"][0].update(capture_multiplier=-1), "must be positive"),
    (lambda d: d["tiers"][0].update(encounter_probability=-0.1), "non-negative"),
    (lambda d: d["species"][0].update(base_price=0), "base_price must be positive"),
    (lambda d: d.update(tiers=d["tiers"][-1:]), "at least one regular tier"),
])
def test_numeric_and_duplicate_problems_are_rejected(raw, mutate, message):
    with pytest.raises(CatalogError, match=message):
        Catalog(_mutated(raw, mutate))


@pytest.mark.parametrize("mutate", [
    lambda d: d["tiers"][0].update(surprise=1),
    lambda d: d["tiers"][0].pop("id"),
    lambda d: d.update(tiers=[[1, 2]]),
    lambda d: d.update(levels=[1, 2, 3]),
    lambda d: d["levels"].update(extra=1),
    lambda d: d["economy"].pop("xp_reward_factor"),
    lambda d: d.update(economy=5),
    lambda d: d["policy"].update(extra=1),
    lambda d: d.update(policy=[]),
    lambda d: d["species"][0].update(passive={}),
    lambda d: d["species"][0].update(passive=["x"]),
    lambda d: d["personalities"][0].pop("id"),
    lambda d: d["personalities"][0].pop("categories"),
    lambda d: d.update(personalities=["bad"]),
    lambda d: d.update(species=[5]),
    lambda d: d["species"][0]["abilities"][0].update(cooldown="x"),
    lambda d: d.update(version=None) or d.pop("tiers"),
])
def test_malformed_shapes_raise_catalog_error_only(raw, mutate):
    with pytest.raises(CatalogError):
        Catalog(_mutated(raw, mutate))


def test_non_object_catalog_is_a_catalog_error():
    with pytest.raises(CatalogError):
        Catalog([])


def test_negative_copies_clamp_to_the_lowest_tier():
    catalog = Catalog.load(CATALOG_PATH)
    assert catalog.tier_for_copies("sentinel", -5) == "normal"
