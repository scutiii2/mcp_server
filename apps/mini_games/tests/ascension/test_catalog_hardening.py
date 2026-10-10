import copy
import json
import shutil

import pytest

from src.ascension.catalog import Catalog, CatalogError
from tests.ascension.env import CATALOG_PATH, ASCENDEDS_PATH, load_raw


def _ascended(d, ascended_id):
    return next(s for s in d["ascendeds"] if s["id"] == ascended_id)


@pytest.fixture(scope="module")
def raw():
    return load_raw()


def _mutated(raw, mutate):
    data = copy.deepcopy(raw)
    mutate(data)
    return data


@pytest.mark.parametrize("mutate,message", [
    (lambda d: _ascended(d, "striker").update(id=_ascended(d, "guardian")["id"]), "ascended ids must be unique"),
    (lambda d: d["personalities"][1].update(id=d["personalities"][0]["id"]), "personality ids must be unique"),
    (lambda d: d["tiers"][1].update(id=d["tiers"][0]["id"]), "tier ids must be unique"),
    (lambda d: _ascended(d, "striker")["abilities"][0].update(id=_ascended(d, "guardian")["abilities"][0]["id"]), "ability ids must be unique"),
    (lambda d: d["tiers"][0].update(stat_multiplier=0), "must be positive"),
    (lambda d: d["tiers"][0].update(capture_multiplier=-1), "must be positive"),
    (lambda d: d["tiers"][0].update(encounter_probability=-0.1), "non-negative"),
    (lambda d: _ascended(d, "guardian").update(base_price=0), "base_price must be positive"),
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
    lambda d: _ascended(d, "guardian").update(passive={}),
    lambda d: _ascended(d, "guardian").update(passive=["x"]),
    lambda d: d["personalities"][0].pop("id"),
    lambda d: d["personalities"][0].pop("categories"),
    lambda d: d.update(personalities=["bad"]),
    lambda d: d.update(ascendeds=[5]),
    lambda d: _ascended(d, "guardian")["abilities"][0].update(cooldown="x"),
    lambda d: d.update(version=None) or d.pop("tiers"),
])
def test_malformed_shapes_raise_catalog_error_only(raw, mutate):
    with pytest.raises(CatalogError):
        Catalog(_mutated(raw, mutate))


def test_non_object_catalog_is_a_catalog_error():
    with pytest.raises(CatalogError):
        Catalog([])


def test_negative_copies_clamp_to_the_lowest_tier():
    catalog = Catalog.load(CATALOG_PATH, ASCENDEDS_PATH)
    assert catalog.tier_for_copies("sentinel", -5) == "common"


@pytest.fixture
def ascendeds_dir(tmp_path):
    target = tmp_path / "ascendeds"
    shutil.copytree(ASCENDEDS_PATH, target)
    return target


def test_a_copied_ascendeds_directory_loads(ascendeds_dir):
    assert len(Catalog.load(CATALOG_PATH, ascendeds_dir).all_ascendeds()) == 7


def test_a_missing_ascendeds_directory_is_a_catalog_error(tmp_path):
    with pytest.raises(CatalogError, match="does not exist"):
        Catalog.load(CATALOG_PATH, tmp_path / "nope")


def test_an_empty_ascendeds_directory_is_a_catalog_error(tmp_path):
    with pytest.raises(CatalogError, match="holds no"):
        Catalog.load(CATALOG_PATH, tmp_path)


def test_a_ascendeds_path_that_is_a_file_is_a_catalog_error():
    with pytest.raises(CatalogError, match="does not exist"):
        Catalog.load(CATALOG_PATH, CATALOG_PATH)


def test_a_malformed_ascended_file_is_named(ascendeds_dir):
    (ascendeds_dir / "scout" / "catalog.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(CatalogError, match="scout/catalog.json"):
        Catalog.load(CATALOG_PATH, ascendeds_dir)


def test_a_ascended_file_that_is_not_an_object_is_named(ascendeds_dir):
    (ascendeds_dir / "scout" / "catalog.json").write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(CatalogError, match="scout/catalog.json"):
        Catalog.load(CATALOG_PATH, ascendeds_dir)


def test_a_folder_name_that_differs_from_the_id_is_rejected(ascendeds_dir):
    (ascendeds_dir / "scout").rename(ascendeds_dir / "tracker")
    with pytest.raises(CatalogError, match="tracker/catalog.json.*must equal the folder name"):
        Catalog.load(CATALOG_PATH, ascendeds_dir)


def test_a_duplicate_ascended_id_is_rejected(ascendeds_dir):
    shutil.copytree(ascendeds_dir / "scout", ascendeds_dir / "scout2")
    with pytest.raises(CatalogError, match="scout2/catalog.json"):
        Catalog.load(CATALOG_PATH, ascendeds_dir)


def test_folders_without_a_catalog_file_and_loose_files_are_skipped(ascendeds_dir):
    (ascendeds_dir / "empty_draft").mkdir()
    (ascendeds_dir / "ascended_common_front_template.png").write_bytes(b"png")
    assert len(Catalog.load(CATALOG_PATH, ascendeds_dir).all_ascendeds()) == 7


def test_the_load_order_is_alphabetical(ascendeds_dir):
    catalog = Catalog.load(CATALOG_PATH, ascendeds_dir)
    ids = [s.id for s in catalog.all_ascendeds()]
    assert ids == sorted(ids)


def test_a_missing_rules_file_is_a_catalog_error(tmp_path):
    with pytest.raises(CatalogError, match="cannot load catalog"):
        Catalog.load(tmp_path / "missing.json", ASCENDEDS_PATH)
