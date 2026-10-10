"""Alembic environment. Always driven by `src.services.migrations`, which
hands in a live connection; there is no offline (SQL script) mode."""

from alembic import context

from src import models  # noqa: F401  (registers every table on Base.metadata)
from src.db import Base

connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("Run migrations with `python -m scripts.migrate_db`, not the alembic command.")

# Batch rebuilds drop tables; SQLite must not cascade that drop to their children.
# Change enforcement outside a transaction, and restore it even after a failure.
is_sqlite = connection.dialect.name == "sqlite"
foreign_keys = None
if is_sqlite:
    foreign_keys = connection.exec_driver_sql("PRAGMA foreign_keys").scalar()
    connection.commit()
    connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    connection.commit()

try:
    with connection.begin():
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            # SQLite cannot alter a column in place; batch mode rebuilds the table.
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
        if is_sqlite and connection.exec_driver_sql("PRAGMA foreign_key_check").first():
            raise RuntimeError("Migration left invalid foreign key references")
finally:
    if is_sqlite:
        connection.exec_driver_sql(f"PRAGMA foreign_keys={int(foreign_keys)}")
        connection.commit()
