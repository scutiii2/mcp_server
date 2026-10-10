import copy
import json
import shutil

import pytest

from src.sparks.catalog import Catalog, CatalogError
from tests.sparks.env import CATALOG_PATH, SPARKS_PATH, load_raw


def _spark(d, spark_id):
    return next(s for s in d["sparks"] if s["id"] == spark_id)


@pytest.fixture(scope="module")
def raw():
    return load_raw()


def _mutated(raw, mutate):
    data = copy.deepcopy(raw)
    mutate(data)
    return data


@pytest.mark.parametrize("mutate,message", [
    (lambda d: _spark(d, "striker").update(id=_spark(d, "guardian")["id"]), "spark ids must be unique"),
    (lambda d: d["personalities"][1].update(id=d["personalities"][0]["id"]), "personality ids must be unique"),
    (lambda d: d["tiers"][1].update(id=d["tiers"][0]["id"]), "tier ids must be unique"),
    (lambda d: _spark(d, "striker")["abilities"][0].update(id=_spark(d, "guardian")["abilities"][0]["id"]), "ability ids must be unique"),
    (lambda d: d["tiers"][0].update(stat_multiplier=0), "must be positive"),
    (lambda d: d["tiers"][0].update(capture_multiplier=-1), "must be positive"),
    (lambda d: d["tiers"][0].update(encounter_probability=-0.1), "non-negative"),
    (lambda d: _spark(d, "guardian").update(base_price=0), "base_price must be positive"),
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
    lambda d: _spark(d, "guardian").update(passive={}),
    lambda d: _spark(d, "guardian").update(passive=["x"]),
    lambda d: d["personalities"][0].pop("id"),
    lambda d: d["personalities"][0].pop("categories"),
    lambda d: d.update(personalities=["bad"]),
    lambda d: d.update(sparks=[5]),
    lambda d: _spark(d, "guardian")["abilities"][0].update(cooldown="x"),
    lambda d: d.update(version=None) or d.pop("tiers"),
])
def test_malformed_shapes_raise_catalog_error_only(raw, mutate):
    with pytest.raises(CatalogError):
        Catalog(_mutated(raw, mutate))


def test_non_object_catalog_is_a_catalog_error():
    with pytest.raises(CatalogError):
        Catalog([])


def test_negative_copies_clamp_to_the_lowest_tier():
    catalog = Catalog.load(CATALOG_PATH, SPARKS_PATH)
    assert catalog.tier_for_copies("sentinel", -5) == "common"


@pytest.fixture
def sparks_dir(tmp_path):
    target = tmp_path / "sparks"
    shutil.copytree(SPARKS_PATH, target)
    return target


def test_a_copied_sparks_directory_loads(sparks_dir):
    assert len(Catalog.load(CATALOG_PATH, sparks_dir).all_sparks()) == 7


def test_a_missing_sparks_directory_is_a_catalog_error(tmp_path):
    with pytest.raises(CatalogError, match="does not exist"):
        Catalog.load(CATALOG_PATH, tmp_path / "nope")


def test_an_empty_sparks_directory_is_a_catalog_error(tmp_path):
    with pytest.raises(CatalogError, match="holds no"):
        Catalog.load(CATALOG_PATH, tmp_path)


def test_a_sparks_path_that_is_a_file_is_a_catalog_error():
    with pytest.raises(CatalogError, match="does not exist"):
        Catalog.load(CATALOG_PATH, CATALOG_PATH)


def test_a_malformed_spark_file_is_named(sparks_dir):
    (sparks_dir / "scout" / "catalog.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(CatalogError, match="scout/catalog.json"):
        Catalog.load(CATALOG_PATH, sparks_dir)


def test_a_spark_file_that_is_not_an_object_is_named(sparks_dir):
    (sparks_dir / "scout" / "catalog.json").write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(CatalogError, match="scout/catalog.json"):
        Catalog.load(CATALOG_PATH, sparks_dir)


def test_a_folder_name_that_differs_from_the_id_is_rejected(sparks_dir):
    (sparks_dir / "scout").rename(sparks_dir / "tracker")
    with pytest.raises(CatalogError, match="tracker/catalog.json.*must equal the folder name"):
        Catalog.load(CATALOG_PATH, sparks_dir)


def test_a_duplicate_spark_id_is_rejected(sparks_dir):
    shutil.copytree(sparks_dir / "scout", sparks_dir / "scout2")
    with pytest.raises(CatalogError, match="scout2/catalog.json"):
        Catalog.load(CATALOG_PATH, sparks_dir)


def test_folders_without_a_catalog_file_and_loose_files_are_skipped(sparks_dir):
    (sparks_dir / "empty_draft").mkdir()
    (sparks_dir / "spark_normal_front_template.png").write_bytes(b"png")
    assert len(Catalog.load(CATALOG_PATH, sparks_dir).all_sparks()) == 7


def test_the_load_order_is_alphabetical(sparks_dir):
    catalog = Catalog.load(CATALOG_PATH, sparks_dir)
    ids = [s.id for s in catalog.all_sparks()]
    assert ids == sorted(ids)


def test_a_missing_rules_file_is_a_catalog_error(tmp_path):
    with pytest.raises(CatalogError, match="cannot load catalog"):
        Catalog.load(tmp_path / "missing.json", SPARKS_PATH)
