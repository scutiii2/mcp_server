"""Alembic environment. Always driven by `src.services.migrations`, which
hands in a live connection; there is no offline (SQL script) mode."""

from alembic import context

from src import models  # noqa: F401  (registers every table on Base.metadata)
from src.db import Base

connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("Run migrations with `python -m scripts.migrate_db`, not the alembic command.")

context.configure(
    connection=connection,
    target_metadata=Base.metadata,
    # SQLite cannot alter a column in place; batch mode rebuilds the table.
    render_as_batch=True,
    compare_type=True,
)
with context.begin_transaction():
    context.run_migrations()
