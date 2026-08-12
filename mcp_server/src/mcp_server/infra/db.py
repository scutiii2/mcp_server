"""HANA database client - thin wrapper for direct SQL access to the SAP database.

This bypasses SAP's RFC/BAPI layer entirely - it's for reporting and
monitoring queries against the database directly, not business logic that
needs SAP's own authorization checks, locking, or update semantics. Don't
reach for this to *change* SAP data; use the RFC-based tools for that.

``hdbcli`` implements Python's standard DB-API 2.0 (PEP 249), so this
follows the same context-manager pattern as ``infra/ssh.py`` rather than
inventing a different shape for "the other kind of remote connection."
"""

from __future__ import annotations

from dataclasses import dataclass
from types import TracebackType
from typing import Any

from hdbcli import dbapi


@dataclass
class DBQueryResult:
    columns: list[str]
    rows: list[dict[str, Any]]


class HanaClient:
    """Context-manager HANA connection.

    Usage:
        with HanaClient(host, port, user, password) as db:
            result = db.query("SELECT * FROM TBTCO WHERE JOBNAME = ?", ("Z_DAILY_CLEANUP",))
    """

    def __init__(self, host: str, port: int, user: str, password: str) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self._conn: Any = None

    def __enter__(self) -> "HanaClient":
        self._conn = dbapi.connect(
            address=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
        )
        return self

    def query(self, sql: str, params: tuple[Any, ...] = ()) -> DBQueryResult:
        assert self._conn is not None, "HanaClient must be used as a context manager"
        cursor = self._conn.cursor()
        try:
            cursor.execute(sql, params)
            columns = [desc[0] for desc in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
            return DBQueryResult(columns=columns, rows=rows)
        finally:
            cursor.close()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._conn is not None:
            self._conn.close()
