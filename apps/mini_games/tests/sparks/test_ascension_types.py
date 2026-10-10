import copy

import pytest

from src.sparks.ascension_types import AscensionType
from src.sparks.catalog import Catalog, CatalogError
from tests.sparks.env import load_raw
from tests.sparks.test_catalog_hardening import _spark


@pytest.fixture(scope="module")
def raw():
    return load_raw()


def _with_types(raw, value):
    data = copy.deepcopy(raw)
    _spark(data, "guardian")["ascension_types"] = value
    return Catalog(data)


def test_the_six_ascension_types_are_known():
    assert [t.value for t in AscensionType] == ["pure", "abyss", "divine", "crimson", "enchant", "synthetic"]
    assert AscensionType.ABYSS.label == "Abyss"


def test_every_shipped_ascended_is_enchant():
    catalog = Catalog.load()
    assert all(s.ascension_types == (AscensionType.ENCHANT,) for s in catalog.all_sparks())


def test_a_catalog_accepts_several_types_or_none(raw):
    assert _with_types(raw, ["enchant", "divine"]).spark("guardian").ascension_types == (AscensionType.ENCHANT, AscensionType.DIVINE)
    assert _with_types(raw, []).spark("guardian").ascension_types == ()


def test_a_missing_field_means_no_types(raw):
    data = copy.deepcopy(raw)
    _spark(data, "guardian").pop("ascension_types", None)
    assert Catalog(data).spark("guardian").ascension_types == ()


@pytest.mark.parametrize("value", [["fire"], ["enchant", "enchant"], "enchant", [1], None])
def test_bad_types_are_rejected(raw, value):
    with pytest.raises(CatalogError, match="ascension_types"):
        _with_types(raw, value)
