"""Tables an uploaded CSV or XLSX file became, kept in memory for the data tools.

Modeled on `services/downloads.py`: nothing here names a file on disk. The id
is random and opaque, the data is held in memory, and an entry is bound to the
account that uploaded it. Another account, an expired id and an unknown id are
indistinguishable (`get` -> None), so ids cannot be probed. A restart drops
every table; the person attaches the file again.

Data is column-major (`data[column][row]`) so a tool that needs one column
walks one tuple. Plain threads call this (tools run in `@offload` worker
threads, the upload route on the event loop), so every change takes the lock.
"""

from __future__ import annotations

import hmac
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.services.downloads import safe_filename

TTL_SECONDS = 1800
MAX_PER_OWNER = 10
MAX_TABLES = 20
MAX_FILE_BYTES = 15 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024
MAX_ROWS = 200_000
MAX_COLUMNS = 200


class TableRefused(ValueError):
    """The file cannot become a table; the message is safe to show to the caller."""


@dataclass
class ParsedTable:
    """What the loader produced, before it is stored. `kinds` holds "number", "date" or "text"."""

    columns: list[str]
    kinds: list[str]
    data: list[list[Any]]
    row_count: int
    sheet: str | None
    notes: list[str]


@dataclass(frozen=True)
class Table:
    id: str
    owner: str
    filename: str
    sheet: str | None
    columns: tuple[str, ...]
    kinds: tuple[str, ...]
    data: tuple[tuple[Any, ...], ...]
    row_count: int
    size_bytes: int
    notes: tuple[str, ...]
    expires_at: float


class TableRegistry:
    def __init__(
        self,
        ttl_seconds: float = TTL_SECONDS,
        max_per_owner: int = MAX_PER_OWNER,
        max_tables: int = MAX_TABLES,
        max_total_bytes: int = MAX_TOTAL_BYTES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._max_per_owner = max_per_owner
        self._max_tables = max_tables
        self._max_total = max_total_bytes
        self._clock = clock
        self._entries: OrderedDict[str, Table] = OrderedDict()
        self._total = 0
        self._lock = threading.Lock()

    def add(self, owner: str, filename: str, parsed: ParsedTable, size_bytes: int) -> Table:
        """Keeps `parsed` for `owner`, evicting the oldest entries to stay inside the caps."""
        if not owner:
            raise TableRefused("The caller is not identified, so the table cannot be kept.")
        if size_bytes > self._max_total:
            raise TableRefused(f"The file is too large to keep (limit {self._max_total // (1024 * 1024)} MB).")
        table = Table(
            id=secrets.token_urlsafe(16),
            owner=owner,
            filename=safe_filename(filename),
            sheet=parsed.sheet,
            columns=tuple(parsed.columns),
            kinds=tuple(parsed.kinds),
            data=tuple(tuple(column) for column in parsed.data),
            row_count=parsed.row_count,
            size_bytes=size_bytes,
            notes=tuple(parsed.notes),
            expires_at=self._clock() + self._ttl,
        )
        with self._lock:
            self._drop_expired()
            while self._count_for(owner) >= self._max_per_owner:
                self._drop(next(key for key, entry in self._entries.items() if entry.owner == owner))
            while self._entries and (
                len(self._entries) >= self._max_tables or self._total + size_bytes > self._max_total
            ):
                self._drop(next(iter(self._entries)))
            self._entries[table.id] = table
            self._total += size_bytes
        return table

    def get(self, table_id: str, owner: str) -> Table | None:
        """The table, only for the account that uploaded it and before it expires."""
        with self._lock:
            self._drop_expired()
            table = self._entries.get(table_id)
        if table is None or not owner:
            return None
        if not hmac.compare_digest(table.owner.encode("utf-8"), owner.encode("utf-8")):
            return None
        return table

    def list_for(self, owner: str) -> list[Table]:
        """`owner`'s live tables, newest first."""
        with self._lock:
            self._drop_expired()
            return [table for table in reversed(self._entries.values()) if table.owner == owner]

    def seconds_left(self, table: Table) -> float:
        return max(0.0, table.expires_at - self._clock())

    def __len__(self) -> int:
        with self._lock:
            self._drop_expired()
            return len(self._entries)

    def _count_for(self, owner: str) -> int:
        return sum(1 for entry in self._entries.values() if entry.owner == owner)

    def _drop_expired(self) -> None:
        now = self._clock()
        for key in [k for k, entry in self._entries.items() if entry.expires_at <= now]:
            self._drop(key)

    def _drop(self, key: str) -> None:
        self._total -= self._entries.pop(key).size_bytes


# The one store this server uses; tests swap it.
registry = TableRegistry()
