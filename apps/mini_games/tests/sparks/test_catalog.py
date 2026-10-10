import copy

import pytest

from src.sparks.catalog import Catalog, CatalogError
from tests.sparks.env import CATALOG_PATH, SPARKS_PATH, load_raw


def _spark(d, spark_id):
    return next(s for s in d["sparks"] if s["id"] == spark_id)


@pytest.fixture(scope="module")
def raw():
    return load_raw()


@pytest.fixture(scope="module")
def catalog():
    return Catalog.load(CATALOG_PATH, SPARKS_PATH)


def test_shipped_catalog_is_valid(catalog):
    assert catalog.version == 1
    assert [t.id for t in catalog.tiers] == ["normal", "rare", "legendary", "royalty", "ascended", "forbidden"]
    assert len(catalog.all_species()) == 7
    assert [s.id for s in catalog.starter_species()] == ["guardian", "scout", "striker"]  # file-name order
    assert catalog.forbidden_species().id == "forbidden"
    assert len(catalog.regular_species()) == 6
    assert [s.id for s in catalog.all_species()] == ["bruiser", "channeler", "forbidden", "guardian", "scout", "sentinel", "striker"]


def test_stats_use_growth_then_tier_multiplier_and_floor(catalog):
    assert catalog.stat_value("guardian", 1, "normal", "hp") == 150
    assert catalog.stat_value("guardian", 11, "normal", "hp") == 300  # 150 + 15 * 10
    assert catalog.stat_value("scout", 3, "rare", "essence") == 33  # (22 + 2.2 * 2) * 1.25 = 33.0
    assert catalog.stat_value("forbidden", 1, "forbidden", "hp") == 800
    assert catalog.stat_value("forbidden", 1, "forbidden", "speed") == 120
    assert catalog.stat_value("scout", 2, "normal", "speed") == 38  # 35 + 3.5 = 38.5 floored


def test_every_species_grows_ten_percent_of_base(catalog):
    for species in catalog.all_species():
        for stat in ("hp", "essence", "speed"):
            assert species.growth[stat] == pytest.approx(species.base[stat] * 0.1)


@pytest.mark.parametrize("copies,tier", [(0, "normal"), (9, "normal"), (10, "rare"), (39, "rare"), (40, "legendary"), (100, "royalty"), (250, "ascended"), (9999, "ascended")])
def test_regular_tier_follows_copies(catalog, copies, tier):
    assert catalog.tier_for_copies("sentinel", copies) == tier


def test_forbidden_is_always_forbidden(catalog):
    assert catalog.tier_for_copies("forbidden", 0) == "forbidden"
    assert catalog.tier_for_copies("forbidden", 100) == "forbidden"


def test_level_caps(catalog):
    assert catalog.level_cap("guardian") == 30 and catalog.level_cap("forbidden") == 50


def test_sale_value_formula(catalog):
    assert catalog.sale_value("guardian", "normal", 1) == 100
    assert catalog.sale_value("guardian", "rare", 11) == 187  # 100 * 1.25 * 1.5 = 187.5
    assert catalog.sale_value("forbidden", "forbidden", 1) == 4000


def _broken(raw, mutate):
    data = copy.deepcopy(raw)
    mutate(data)
    return data


@pytest.mark.parametrize("mutate,message", [
    (lambda d: d["tiers"][0].update(encounter_probability=0.5), "sum to 1"),
    (lambda d: d["tiers"][1].update(id="normal"), "unique"),
    (lambda d: d["tiers"][2].update(copy_threshold=5), "strictly increase"),
    (lambda d: _spark(d, "guardian").update(starter=False), "three species must be starters"),
    (lambda d: _spark(d, "sentinel")["abilities"].pop(), "unlock at levels"),
    (lambda d: _spark(d, "guardian")["abilities"][1].pop("duration"), "SUPPORT needs"),
    (lambda d: _spark(d, "guardian")["abilities"][0].update(category="HEAL"), "category must be"),
    (lambda d: d["personalities"][0].update(categories=["NOPE"]), "invalid categories"),
    (lambda d: d["policy"]["coefficients"].pop("FEAR"), "coefficients missing"),
    (lambda d: _spark(d, "guardian")["base"].pop("hp"), "exactly hp, essence and speed"),
])
def test_inconsistent_catalogs_are_rejected(raw, mutate, message):
    with pytest.raises(CatalogError, match=message):
        Catalog(_broken(raw, mutate))


def test_unreadable_file_is_a_catalog_error(tmp_path):
    with pytest.raises(CatalogError, match="cannot load"):
        Catalog.load(tmp_path / "missing.json", SPARKS_PATH)
