"""Tests for the in-memory table registry: owner binding, expiry, caps."""

from __future__ import annotations

import pytest

from src.services.tables import ParsedTable, TableRefused, TableRegistry


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def parsed(rows: int = 2) -> ParsedTable:
    return ParsedTable(
        columns=["a", "b"],
        kinds=["number", "text"],
        data=[[float(i) for i in range(rows)], ["x"] * rows],
        row_count=rows,
        sheet=None,
        notes=[],
    )


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def registry(clock: Clock) -> TableRegistry:
    return TableRegistry(ttl_seconds=60, max_per_owner=2, max_tables=3, max_total_bytes=100, bytes_per_cell=0, clock=clock)


def test_add_returns_an_opaque_id_and_get_returns_the_table(registry):
    table = registry.add("alice", "Sales 2026.csv", parsed(), 10)

    assert table.id and "Sales" not in table.id
    assert table.filename == "Sales_2026.csv"
    assert table.columns == ("a", "b") and table.row_count == 2
    assert registry.get(table.id, "alice") is table


def test_another_owner_an_unknown_id_and_an_empty_owner_all_get_none(registry):
    table = registry.add("alice", "t.csv", parsed(), 10)

    assert registry.get(table.id, "bob") is None
    assert registry.get("nope", "alice") is None
    assert registry.get(table.id, "") is None


def test_an_unidentified_caller_cannot_add(registry):
    with pytest.raises(TableRefused, match="not identified"):
        registry.add("", "t.csv", parsed(), 10)


def test_entries_expire(registry, clock):
    table = registry.add("alice", "t.csv", parsed(), 10)
    clock.now += 59
    assert registry.get(table.id, "alice") is table
    clock.now += 2
    assert registry.get(table.id, "alice") is None
    assert len(registry) == 0


def test_seconds_left_counts_down(registry, clock):
    table = registry.add("alice", "t.csv", parsed(), 10)
    clock.now += 20
    assert registry.seconds_left(table) == pytest.approx(40)


def test_per_owner_cap_evicts_that_owners_oldest(registry):
    first = registry.add("alice", "1.csv", parsed(), 10)
    registry.add("alice", "2.csv", parsed(), 10)
    registry.add("bob", "b.csv", parsed(), 10)
    registry.add("alice", "3.csv", parsed(), 10)

    assert registry.get(first.id, "alice") is None
    assert [t.filename for t in registry.list_for("alice")] == ["3.csv", "2.csv"]
    assert len(registry.list_for("bob")) == 1


def test_total_table_cap_evicts_the_oldest_overall(registry):
    first = registry.add("a", "1.csv", parsed(), 10)
    registry.add("b", "2.csv", parsed(), 10)
    registry.add("c", "3.csv", parsed(), 10)
    registry.add("d", "4.csv", parsed(), 10)

    assert registry.get(first.id, "a") is None
    assert len(registry) == 3


def test_total_byte_cap_evicts_until_the_new_table_fits(registry):
    first = registry.add("a", "1.csv", parsed(), 60)
    registry.add("b", "2.csv", parsed(), 30)
    registry.add("c", "3.csv", parsed(), 50)

    assert registry.get(first.id, "a") is None
    assert len(registry) == 2


def test_a_table_larger_than_the_byte_cap_is_refused(registry):
    with pytest.raises(TableRefused, match="too large"):
        registry.add("a", "big.csv", parsed(), 101)


def test_list_for_hides_expired_and_other_owners(registry, clock):
    registry.add("alice", "old.csv", parsed(), 10)
    clock.now += 61
    fresh = registry.add("alice", "new.csv", parsed(), 10)
    registry.add("bob", "b.csv", parsed(), 10)

    assert registry.list_for("alice") == [fresh]


def test_the_charge_is_the_estimated_memory_when_that_exceeds_the_file_size(clock):
    registry = TableRegistry(ttl_seconds=60, max_total_bytes=1000, bytes_per_cell=10, clock=clock)
    first = registry.add("a", "1.csv", parsed(rows=5), 20)  # 5 rows x 2 columns x 10 = 100, not 20
    assert first.size_bytes == 20 and first.charged_bytes == 100
    for owner in "bcdefghi":
        registry.add(owner, f"{owner}.csv", parsed(rows=5), 20)  # 9 x 100 = 900
    assert registry.get(first.id, "a") is first
    registry.add("j", "j.csv", parsed(rows=5), 20)  # 1000 fits exactly
    assert registry.get(first.id, "a") is first
    registry.add("k", "k.csv", parsed(rows=5), 20)  # over: the oldest goes
    assert registry.get(first.id, "a") is None


def test_a_table_whose_estimated_memory_exceeds_the_cap_is_refused(clock):
    registry = TableRegistry(max_total_bytes=100, bytes_per_cell=40, clock=clock)
    with pytest.raises(TableRefused, match="too large"):
        registry.add("a", "wide.csv", parsed(rows=2), 10)  # 2 x 2 x 40 = 160 > 100
