from __future__ import annotations

import pytest

from src.services import capability_meta


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setattr(capability_meta, "_BY_FOLDER", {})


def test_unregister_lets_the_folder_register_again():
    capability_meta.register(folder="widgets", id="wid", label="Widgets")

    capability_meta.unregister("widgets")

    assert capability_meta.for_folder("widgets") is None
    assert capability_meta.register(folder="widgets", id="wid2", label="W2").id == "wid2"


def test_unregister_of_an_unknown_folder_is_a_no_op():
    capability_meta.unregister("nothing")
