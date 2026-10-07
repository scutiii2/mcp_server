"""Tests for the table tools' domain logic, over a small sales table."""

from __future__ import annotations

import pytest

from src.capabilities.tables import domain
from src.capabilities.tables.contract import Condition, Measure
from src.services.table_loader import load_table
from src.services.tables import TableRegistry

CSV = (
    b"region,product,units,price,sold\n"
    b"EU,A,10,2.5,2026-01-01\n"
    b"EU,B,5,4,2026-01-02\n"
    b"US,A,20,2.5,2026-01-03\n"
    b"US,B,,4,2026-01-04\n"
    b"APAC,A,7,2.5,2026-02-01\n"
)


@pytest.fixture
def registry() -> TableRegistry:
    return TableRegistry()


@pytest.fixture
def table_id(registry) -> str:
    return registry.add("alice", "sales.csv", load_table("sales.csv", CSV), len(CSV)).id


def cond(column, op, value=None) -> Condition:
    return Condition(column=column, op=op, value=value)


def test_list_tables_shows_only_the_callers_tables(registry, table_id):
    registry.add("bob", "other.csv", load_table("other.csv", CSV), 1)

    result = domain.list_tables(registry, "alice")

    assert [(t.table_id, t.filename, t.rows, t.columns) for t in result.tables] == [(table_id, "sales.csv", 5, 5)]
    assert result.tables[0].minutes_left in (29, 30)
    assert domain.list_tables(registry, "nobody").tables == []


def test_describe_summarises_each_column(registry, table_id):
    result = domain.describe(registry, "alice", table_id)

    by_name = {c.name: c for c in result.columns}
    assert result.rows == 5 and result.sheet is None
    assert by_name["units"].kind == "number" and by_name["units"].nulls == 1 and by_name["units"].non_null == 4
    assert (by_name["units"].min, by_name["units"].max, by_name["units"].mean) == (5, 20, 10.5)
    assert by_name["sold"].kind == "date" and by_name["sold"].min == "2026-01-01" and by_name["sold"].max == "2026-02-01"
    assert by_name["region"].distinct == 3 and by_name["region"].top_values[0] == "EU (2)"


def test_head_returns_the_first_rows_capped(registry, table_id):
    result = domain.head(registry, "alice", table_id, limit=2)

    assert result.columns == ["region", "product", "units", "price", "sold"]
    assert result.rows == [["EU", "A", 10, 2.5, "2026-01-01"], ["EU", "B", 5, 4, "2026-01-02"]]
    assert (result.total_matches, result.shown) == (5, 2)
    with pytest.raises(ValueError, match="between 1 and 50"):
        domain.head(registry, "alice", table_id, limit=51)


def test_filter_combines_conditions_with_and(registry, table_id):
    result = domain.filter_rows(registry, "alice", table_id, [cond("units", ">=", 7), cond("region", "=", "eu")])

    assert result.total_matches == 1 and result.rows[0][:3] == ["EU", "A", 10]


def test_filter_text_contains_dates_and_nulls(registry, table_id):
    assert domain.filter_rows(registry, "alice", table_id, [cond("product", "contains", "a")]).total_matches == 3
    assert domain.filter_rows(registry, "alice", table_id, [cond("sold", ">", "2026-01-03")]).total_matches == 2
    assert domain.filter_rows(registry, "alice", table_id, [cond("units", "is_null")]).total_matches == 1
    assert domain.filter_rows(registry, "alice", table_id, [cond("units", "not_null")]).total_matches == 4
    # empty cells never match a comparison
    assert domain.filter_rows(registry, "alice", table_id, [cond("units", "!=", 10)]).total_matches == 3


def test_filter_reports_a_capped_result(registry, table_id):
    result = domain.filter_rows(registry, "alice", table_id, [cond("price", ">", 0)], limit=2)

    assert (result.total_matches, result.shown) == (5, 2) and "first 2" in result.message


def test_filter_errors_name_the_valid_choices(registry, table_id):
    with pytest.raises(ValueError, match="No column 'nope'.*'region'"):
        domain.filter_rows(registry, "alice", table_id, [cond("nope", "=", 1)])
    with pytest.raises(ValueError, match="works on text columns"):
        domain.filter_rows(registry, "alice", table_id, [cond("units", "contains", "1")])
    with pytest.raises(ValueError, match="not a number"):
        domain.filter_rows(registry, "alice", table_id, [cond("units", ">", "lots")])
    with pytest.raises(ValueError, match="needs a value"):
        domain.filter_rows(registry, "alice", table_id, [cond("units", ">")])
    with pytest.raises(ValueError, match="at least one condition"):
        domain.filter_rows(registry, "alice", table_id, [])
    with pytest.raises(ValueError, match="at most 5"):
        domain.filter_rows(registry, "alice", table_id, [cond("units", "not_null")] * 6)


def test_column_names_match_case_insensitively(registry, table_id):
    assert domain.filter_rows(registry, "alice", table_id, [cond("REGION", "=", "US")]).total_matches == 2


def test_aggregate_groups_and_sorts_descending_by_the_first_measure(registry, table_id):
    result = domain.aggregate(registry, "alice", table_id, [Measure(column="units", fn="sum")], group_by=["region"])

    assert result.measures == ["sum(units)"]
    assert [(g.keys, g.values) for g in result.groups] == [(["US"], [20]), (["EU"], [15]), (["APAC"], [7])]
    assert (result.total_groups, result.shown) == (3, 3)


def test_aggregate_several_measures_conditions_and_ascending_sort(registry, table_id):
    result = domain.aggregate(
        registry,
        "alice",
        table_id,
        [Measure(column="units", fn="mean"), Measure(column="product", fn="count")],
        group_by=["region"],
        conditions=[cond("product", "=", "A")],
        sort_by="region",
        descending=False,
    )

    assert [(g.keys, g.values) for g in result.groups] == [(["APAC"], [7, 1]), (["EU"], [10, 1]), (["US"], [20, 1])]


def test_aggregate_without_group_by_is_one_total_row(registry, table_id):
    result = domain.aggregate(
        registry, "alice", table_id, [Measure(column="price", fn="sum"), Measure(column="sold", fn="max")]
    )

    assert [(g.keys, g.values) for g in result.groups] == [([], [15.5, "2026-02-01"])]


def test_aggregate_puts_empty_results_last_and_validates(registry, table_id):
    result = domain.aggregate(registry, "alice", table_id, [Measure(column="units", fn="sum")], group_by=["product"], sort_by="sum(units)")
    assert result.groups[0].keys == ["A"]

    with pytest.raises(ValueError, match="needs a number column"):
        domain.aggregate(registry, "alice", table_id, [Measure(column="region", fn="sum")])
    with pytest.raises(ValueError, match="number or date"):
        domain.aggregate(registry, "alice", table_id, [Measure(column="region", fn="max")])
    with pytest.raises(ValueError, match="at most 2"):
        domain.aggregate(registry, "alice", table_id, [Measure(column="units", fn="sum")], group_by=["region", "product", "sold"])
    with pytest.raises(ValueError, match="Cannot sort by"):
        domain.aggregate(registry, "alice", table_id, [Measure(column="units", fn="sum")], group_by=["region"], sort_by="price")


def test_top_n_and_bottom_n_skip_empty_cells(registry, table_id):
    top = domain.top_n(registry, "alice", table_id, "units", n=2)
    bottom = domain.top_n(registry, "alice", table_id, "units", n=1, largest=False)

    assert [row[2] for row in top.rows] == [20, 10] and top.total_matches == 4
    assert [row[2] for row in bottom.rows] == [5]
    with pytest.raises(ValueError, match="number or date"):
        domain.top_n(registry, "alice", table_id, "region")


def test_value_counts(registry, table_id):
    result = domain.value_counts(registry, "alice", table_id, "region")

    assert [(c.value, c.count) for c in result.counts] == [("EU", 2), ("US", 2), ("APAC", 1)]
    assert result.distinct == 3
    assert [c.count for c in domain.value_counts(registry, "alice", table_id, "region", limit=1).counts] == [2]


def test_an_unknown_expired_or_foreign_table_is_not_found(registry, table_id):
    for call in (
        lambda: domain.describe(registry, "alice", "nope"),
        lambda: domain.describe(registry, "bob", table_id),
        lambda: domain.head(registry, "", table_id),
    ):
        with pytest.raises(domain.TableNotFound, match="attach the file again"):
            call()


def test_long_cell_text_is_clipped():
    registry = TableRegistry()
    long = b"note\n" + b"x" * 500 + b"\n"
    table_id = registry.add("a", "n.csv", load_table("n.csv", long), len(long)).id

    cell = domain.head(registry, "a", table_id).rows[0][0]

    assert len(cell) == domain.CELL_CHARS + 3 and cell.endswith("...")
