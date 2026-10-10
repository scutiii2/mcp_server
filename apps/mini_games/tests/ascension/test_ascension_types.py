import copy

import pytest

from src.ascension.ascension_types import AscensionType
from src.ascension.catalog import Catalog, CatalogError
from tests.ascension.env import load_raw
from tests.ascension.test_catalog_hardening import _ascended


@pytest.fixture(scope="module")
def raw():
    return load_raw()


def _with_types(raw, value):
    data = copy.deepcopy(raw)
    _ascended(data, "guardian")["ascension_types"] = value
    return Catalog(data)


def test_the_six_ascension_types_are_known():
    assert [t.value for t in AscensionType] == ["pure", "abyss", "divine", "crimson", "enchant", "synthetic"]
    assert AscensionType.ABYSS.label == "Abyss"


def test_every_shipped_ascended_is_enchant():
    catalog = Catalog.load()
    assert all(s.ascension_types == (AscensionType.ENCHANT,) for s in catalog.all_ascendeds())


def test_a_catalog_accepts_several_types_or_none(raw):
    assert _with_types(raw, ["enchant", "divine"]).ascended("guardian").ascension_types == (AscensionType.ENCHANT, AscensionType.DIVINE)
    assert _with_types(raw, []).ascended("guardian").ascension_types == ()


def test_a_missing_field_means_no_types(raw):
    data = copy.deepcopy(raw)
    _ascended(data, "guardian").pop("ascension_types", None)
    assert Catalog(data).ascended("guardian").ascension_types == ()


@pytest.mark.parametrize("value", [["fire"], ["enchant", "enchant"], "enchant", [1], None])
def test_bad_types_are_rejected(raw, value):
    with pytest.raises(CatalogError, match="ascension_types"):
        _with_types(raw, value)
