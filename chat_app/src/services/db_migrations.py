"""Closes the one gap db.create_all() leaves open.

create_all() creates tables that don't exist yet, but never alters a
table that already exists to add a column a model gained since the
table was first created. Account.email_verified (added later) crashed the very first query touching
accounts.* on any database created before that column existed - that
incident is what this module exists to prevent from recurring for the
next column someone adds.

Deliberately narrow: this only ever adds a column that's missing. It
never drops, renames, or retypes one - the same "only ever creates"
restraint create_all() itself already has, just extended one notch
further. A real migration tool (Alembic) is still the right answer for
anything beyond that; this exists so the common case (a new column on
an existing table) doesn't take prod down with a raw OperationalError.
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.schema import MetaData

from src.utils.catalog import catalog

logger = logging.getLogger(__name__)


@catalog
def apply_additive_column_migrations(engine: Engine, metadata: MetaData) -> list[str]:
    """Add any column present in `metadata`'s models but missing from the
    live database, one ALTER TABLE ADD COLUMN per column.

    Call this right after db.create_all() - that call already handles
    brand-new tables (skipped here via `existing_tables`); this handles
    new columns on tables that already existed. Returns "table.column"
    for each column actually added, so the caller can log what happened -
    silence here would just trade one invisible schema drift for another.
    """
    inspector = sa.inspect(engine)
    existing_tables = set(inspector.get_table_names())
    added: list[str] = []

    with engine.begin() as conn:
        for table in metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # brand-new table - create_all() already made it
            existing_columns = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_columns:
                    continue
                ddl = _add_column_ddl(table.name, column, engine.dialect)
                conn.execute(sa.text(ddl))
                added.append(f"{table.name}.{column.name}")

    return added


def _add_column_ddl(table_name: str, column: sa.Column, dialect) -> str:
    """One ALTER TABLE ADD COLUMN statement for `column`.

    A NOT NULL column needs a static DEFAULT for existing rows to satisfy
    the constraint immediately - every backend (SQLite included) rejects
    ADD COLUMN NOT NULL without one. When the model's default is a Python
    callable (e.g. `default=lambda: datetime.now(...)`) there's no way to
    express that as a SQL literal, so the column is added nullable
    instead of failing the whole startup: existing rows get NULL until
    something backfills them, while new rows still get the callable
    default from the ORM as normal.
    """
    col_type = column.type.compile(dialect=dialect)
    ddl = f"ALTER TABLE {table_name} ADD COLUMN {column.name} {col_type}"

    default_sql = _static_default_sql(column)
    if not column.nullable and default_sql is not None:
        return f"{ddl} NOT NULL DEFAULT {default_sql}"
    if default_sql is not None:
        return f"{ddl} DEFAULT {default_sql}"
    return ddl


def _static_default_sql(column: sa.Column) -> str | None:
    """The column's default as a SQL literal, or None if it has no
    default or the default isn't a fixed value (a callable or a
    sequence)."""
    if column.server_default is not None:
        return str(column.server_default.arg)
    if column.default is not None and column.default.is_scalar:
        return _literal(column.default.arg)
    return None


def _literal(value) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


RETIRED_TABLES = ("capability_approvers",)


@catalog
def drop_retired_tables(engine: Engine, tables: tuple[str, ...] = RETIRED_TABLES) -> list[str]:
    """Drop tables whose models were removed. Only names listed in
    `tables` are ever dropped, never a table merely absent from
    `metadata`. Returns the names actually dropped."""
    existing = set(sa.inspect(engine).get_table_names())
    dropped = [name for name in tables if name in existing]
    with engine.begin() as conn:
        for name in dropped:
            conn.execute(sa.text(f'DROP TABLE "{name}"'))
    return dropped
