from __future__ import annotations

import pytest

from src.engine.page_ranges import parse_page_ranges
from src.errors import ErrorCode, MergerError


@pytest.mark.parametrize("spec", [None, "", "  ", "all", "ALL"])
def test_empty_or_all_means_every_page(spec):
    assert parse_page_ranges(spec, 3) == [0, 1, 2]


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("1", [0]),
        ("1-3,7", [0, 1, 2, 6]),
        (" 2 - 3 , 5 ", [1, 2, 4]),
        ("7,1", [6, 0]),
    ],
)
def test_ranges_are_one_based_and_keep_written_order(spec, expected):
    assert parse_page_ranges(spec, 10) == expected


@pytest.mark.parametrize(
    ("spec", "fragment"),
    [
        ("0", "1 to 5"),
        ("4-6", "1 to 5"),
        ("3-1", "backwards"),
        ("a", "isn't a page"),
        ("1,,2", "isn't a page"),
        ("1-", "isn't a page"),
    ],
)
def test_bad_ranges_raise_invalid_range(spec, fragment):
    with pytest.raises(MergerError) as caught:
        parse_page_ranges(spec, 5)

    assert caught.value.code == ErrorCode.INVALID_RANGE
    assert fragment in caught.value.message
