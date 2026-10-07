"""Read-only questions about a table an uploaded file became: describe,
filter, group, rank. Plain Python over column tuples - no pandas, no `eval`,
no expression strings. Every result is capped, and says so when it is.

Functions take the registry and the caller's name instead of reaching for
globals, so tests (and the tool wrappers) decide which store and which owner.
"""

from __future__ import annotations

import heapq
import operator
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from src.capabilities.tables.contract import (
    AggregateResult,
    Cell,
    ColumnSummary,
    Condition,
    CountsResult,
    DescribeResult,
    GroupRow,
    Measure,
    RowsResult,
    TableInfo,
    TableListResult,
    ValueCount,
)
from src.services.table_loader import parse_date, parse_number
from src.services.tables import Table, TableRegistry

MAX_ROWS_SHOWN = 50
MAX_GROUPS = 100
MAX_CONDITIONS = 5
MAX_GROUP_COLUMNS = 2
MAX_MEASURES = 6
CELL_CHARS = 200
TOP_VALUES = 5
MAX_NAMES_LISTED = 30

_MIDNIGHT = datetime.min.time()
_COMPARE: dict[str, Callable[[Any, Any], bool]] = {
    "=": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
}


class TableNotFound(ValueError):
    """The id is unknown, expired or belongs to someone else - deliberately not told apart."""


def list_tables(registry: TableRegistry, owner: str) -> TableListResult:
    tables = [
        TableInfo(
            table_id=table.id,
            filename=table.filename,
            rows=table.row_count,
            columns=len(table.columns),
            minutes_left=max(0, round(registry.seconds_left(table) / 60)),
        )
        for table in registry.list_for(owner)
    ]
    message = f"{len(tables)} tables." if tables else "No tables. Ask the user to attach a CSV or Excel file."
    return TableListResult(tables=tables, message=message)


def describe(registry: TableRegistry, owner: str, table_id: str) -> DescribeResult:
    table = _table(registry, owner, table_id)
    columns = [_summarize(table, index) for index in range(len(table.columns))]
    return DescribeResult(
        table_id=table.id,
        filename=table.filename,
        sheet=table.sheet,
        rows=table.row_count,
        columns=columns,
        notes=list(table.notes),
        message=f"{table.filename}: {table.row_count} rows, {len(table.columns)} columns.",
    )


def head(registry: TableRegistry, owner: str, table_id: str, limit: int = 10) -> RowsResult:
    table = _table(registry, owner, table_id)
    _check_limit(limit, MAX_ROWS_SHOWN)
    return _rows_result(table, range(table.row_count), limit, "rows")


def filter_rows(
    registry: TableRegistry, owner: str, table_id: str, conditions: list[Condition], limit: int = 20
) -> RowsResult:
    table = _table(registry, owner, table_id)
    _check_limit(limit, MAX_ROWS_SHOWN)
    if not conditions:
        raise ValueError("Give at least one condition. Use the head tool to see rows without a test.")
    return _rows_result(table, _matching(table, conditions), limit, "matching rows")


def aggregate(
    registry: TableRegistry,
    owner: str,
    table_id: str,
    measures: list[Measure],
    group_by: list[str] | None = None,
    conditions: list[Condition] | None = None,
    sort_by: str = "",
    descending: bool = True,
    limit: int = 25,
) -> AggregateResult:
    table = _table(registry, owner, table_id)
    group_by = group_by or []
    if len(group_by) > MAX_GROUP_COLUMNS:
        raise ValueError(f"Group by at most {MAX_GROUP_COLUMNS} columns.")
    if not 1 <= len(measures) <= MAX_MEASURES:
        raise ValueError(f"Give between 1 and {MAX_MEASURES} measures.")
    _check_limit(limit, MAX_GROUPS)
    group_indexes = [_column(table, name) for name in group_by]
    plan = [(measure.fn, _measure_column(table, measure)) for measure in measures]
    labels = [f"{fn}({table.columns[index]})" for fn, index in plan]

    groups: dict[tuple, list[_Accumulator]] = {}
    for row in _matching(table, conditions or []):
        key = tuple(table.data[index][row] for index in group_indexes)
        accumulators = groups.get(key)
        if accumulators is None:
            accumulators = groups[key] = [_Accumulator() for _ in plan]
        for accumulator, (_fn, index) in zip(accumulators, plan, strict=True):
            accumulator.add(table.data[index][row])

    items = [(key, [acc.result(fn) for acc, (fn, _i) in zip(accs, plan, strict=True)]) for key, accs in groups.items()]
    items = _sorted(items, _sort_position(table, sort_by, group_indexes, labels), descending)
    shown = items[:limit]
    capped = f" Showing the first {limit}; narrow with a condition or a smaller limit." if len(items) > limit else ""
    return AggregateResult(
        table_id=table.id,
        group_by=[table.columns[index] for index in group_indexes],
        measures=labels,
        groups=[GroupRow(keys=[_show(k) for k in key], values=[_show(v) for v in values]) for key, values in shown],
        total_groups=len(items),
        shown=len(shown),
        message=f"{len(items)} groups.{capped}",
    )


def top_n(
    registry: TableRegistry,
    owner: str,
    table_id: str,
    column: str,
    n: int = 10,
    largest: bool = True,
    conditions: list[Condition] | None = None,
) -> RowsResult:
    table = _table(registry, owner, table_id)
    _check_limit(n, MAX_ROWS_SHOWN)
    index = _column(table, column)
    if table.kinds[index] == "text":
        raise ValueError(f"Rank by a number or date column; {table.columns[index]!r} is text.")
    values = table.data[index]
    candidates = [row for row in _matching(table, conditions or []) if values[row] is not None]
    pick = heapq.nlargest if largest else heapq.nsmallest
    chosen = pick(n, candidates, key=values.__getitem__)
    word = "highest" if largest else "lowest"
    result = _rows_result(table, chosen, n, f"rows with a value in {table.columns[index]!r}")
    result.total_matches = len(candidates)
    result.message = f"The {len(chosen)} {word} of {len(candidates)} rows by {table.columns[index]!r}."
    return result


def value_counts(registry: TableRegistry, owner: str, table_id: str, column: str, limit: int = 20) -> CountsResult:
    table = _table(registry, owner, table_id)
    _check_limit(limit, MAX_GROUPS)
    index = _column(table, column)
    counter = Counter(value for value in table.data[index] if value is not None)
    nulls = table.row_count - sum(counter.values())
    more = f" Showing the top {limit}." if len(counter) > limit else ""
    empty = f" {nulls} cells are empty." if nulls else ""
    return CountsResult(
        table_id=table.id,
        column=table.columns[index],
        counts=[ValueCount(value=_show(value), count=count) for value, count in counter.most_common(limit)],
        distinct=len(counter),
        message=f"{len(counter)} distinct values.{more}{empty}",
    )


def _table(registry: TableRegistry, owner: str, table_id: str) -> Table:
    table = registry.get(table_id.strip(), owner)
    if table is None:
        raise TableNotFound(
            "Table not found or expired. Ask the user to attach the file again, "
            "or list the tables with tool_tables_listTables."
        )
    return table


def _check_limit(limit: int, maximum: int) -> None:
    if not 1 <= limit <= maximum:
        raise ValueError(f"The limit must be between 1 and {maximum}, not {limit}.")


def _column(table: Table, name: str) -> int:
    if name in table.columns:
        return table.columns.index(name)
    lowered = [index for index, column in enumerate(table.columns) if column.lower() == name.strip().lower()]
    if len(lowered) == 1:
        return lowered[0]
    listed = ", ".join(repr(column) for column in table.columns[:MAX_NAMES_LISTED])
    listed += " ..." if len(table.columns) > MAX_NAMES_LISTED else ""
    if lowered:
        raise ValueError(f"Column {name!r} is ambiguous; use the exact name. Columns: {listed}.")
    raise ValueError(f"No column {name!r}. Columns: {listed}.")


def _show(value: Any) -> Cell:
    """A cell as a result carries it: whole numbers without a decimal point, dates as ISO text, long text clipped."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() and abs(value) < 1e15 else round(value, 6)
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == _MIDNIGHT else value.isoformat(sep=" ")
    text = str(value)
    return text if len(text) <= CELL_CHARS else text[:CELL_CHARS] + "..."


def _summarize(table: Table, index: int) -> ColumnSummary:
    kind = table.kinds[index]
    values = [value for value in table.data[index] if value is not None]
    low = high = mean = None
    top: list[str] = []
    if kind in ("number", "date") and values:
        low, high = min(values), max(values)
    if kind == "number" and values:
        mean = round(sum(values) / len(values), 6)
    if kind == "text":
        top = [f"{_show(value)} ({count})" for value, count in Counter(values).most_common(TOP_VALUES)]
    return ColumnSummary(
        name=table.columns[index],
        kind=kind,
        non_null=len(values),
        nulls=table.row_count - len(values),
        distinct=len(set(values)),
        min=_show(low),
        max=_show(high),
        mean=mean,
        top_values=top,
    )


def _rows_result(table: Table, indexes: Sequence[int], limit: int, noun: str) -> RowsResult:
    shown = indexes[:limit]
    rows = [[_show(column[row]) for column in table.data] for row in shown]
    capped = f" Showing the first {limit}; narrow with a condition." if len(indexes) > limit else ""
    return RowsResult(
        table_id=table.id,
        columns=list(table.columns),
        rows=rows,
        total_matches=len(indexes),
        shown=len(rows),
        message=f"{len(indexes)} {noun}.{capped}",
    )


def _matching(table: Table, conditions: list[Condition]) -> Sequence[int]:
    if len(conditions) > MAX_CONDITIONS:
        raise ValueError(f"Use at most {MAX_CONDITIONS} conditions.")
    tests = [_predicate(table, condition) for condition in conditions]
    if not tests:
        return range(table.row_count)
    return [row for row in range(table.row_count) if all(test(row) for test in tests)]


def _predicate(table: Table, condition: Condition) -> Callable[[int], bool]:
    index = _column(table, condition.column)
    values, kind, op = table.data[index], table.kinds[index], condition.op
    if op == "is_null":
        return lambda row: values[row] is None
    if op == "not_null":
        return lambda row: values[row] is not None
    if condition.value is None:
        raise ValueError(f"The {op!r} test on {table.columns[index]!r} needs a value.")
    if op == "contains":
        if kind != "text":
            raise ValueError(f"'contains' works on text columns; {table.columns[index]!r} is {kind}.")
        needle = str(condition.value).lower()
        return lambda row: values[row] is not None and needle in values[row].lower()
    target = _coerce(table.columns[index], kind, condition.value)
    compare = _COMPARE[op]
    if kind == "text":
        return lambda row: values[row] is not None and compare(values[row].lower(), target)
    return lambda row: values[row] is not None and compare(values[row], target)


def _coerce(column: str, kind: str, value: str | float) -> Any:
    if kind == "number":
        number = parse_number(value)
        if number is None:
            raise ValueError(f"{value!r} is not a number, and column {column!r} is numeric.")
        return number
    if kind == "date":
        moment = parse_date(value)
        if moment is None:
            raise ValueError(f"{value!r} is not a date like 2026-01-31, and column {column!r} is a date column.")
        return moment
    return str(value).lower()


def _measure_column(table: Table, measure: Measure) -> int:
    index = _column(table, measure.column)
    kind = table.kinds[index]
    if measure.fn in ("sum", "mean") and kind != "number":
        raise ValueError(f"{measure.fn} needs a number column; {table.columns[index]!r} is {kind}.")
    if measure.fn in ("min", "max") and kind == "text":
        raise ValueError(f"{measure.fn} needs a number or date column; {table.columns[index]!r} is text.")
    return index


class _Accumulator:
    """Running count, sum, low and high of one measure within one group."""

    __slots__ = ("count", "total", "low", "high")

    def __init__(self) -> None:
        self.count = 0
        self.total = 0.0
        self.low: Any = None
        self.high: Any = None

    def add(self, value: Any) -> None:
        if value is None:
            return
        self.count += 1
        if isinstance(value, float):
            self.total += value
        if self.low is None or value < self.low:
            self.low = value
        if self.high is None or value > self.high:
            self.high = value

    def result(self, fn: str) -> Any:
        if fn == "count":
            return self.count
        if fn == "sum":
            return self.total if self.count else None
        if fn == "mean":
            return self.total / self.count if self.count else None
        return self.low if fn == "min" else self.high


def _sort_position(table: Table, sort_by: str, group_indexes: list[int], labels: list[str]) -> tuple[str, int]:
    """Where in a group the sort value lives: ("value", i) for a measure, ("key", j) for a group column."""
    if not sort_by:
        return "value", 0
    for position, label in enumerate(labels):
        if label.lower() == sort_by.strip().lower():
            return "value", position
    try:
        index = _column(table, sort_by)
    except ValueError:
        index = -1
    if index in group_indexes:
        return "key", group_indexes.index(index)
    raise ValueError(f"Cannot sort by {sort_by!r}. Use one of {labels} or a group_by column.")


def _sorted(items: list[tuple[tuple, list]], position: tuple[str, int], descending: bool) -> list[tuple[tuple, list]]:
    where, offset = position

    def sort_value(item: tuple[tuple, list]) -> Any:
        return item[0][offset] if where == "key" else item[1][offset]

    present = [item for item in items if sort_value(item) is not None]
    missing = [item for item in items if sort_value(item) is None]
    present.sort(key=sort_value, reverse=descending)
    return present + missing
