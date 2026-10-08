"""Database schema migrations (Alembic) run at startup.

`MigrationRunner.run()` brings the database to the newest revision:

- no tables yet: runs every migration;
- tables but no revision recorded (a database made before migrations existed):
  stamps it as the baseline, then runs whatever came after;
- already behind: runs the missing migrations, after `before_upgrade`
  (a backup) when the database holds data.

Alembic is synchronous, so it runs inside `AsyncConnection.run_sync`.
SQLite commits DDL statements as it goes, so a failed migration can leave the
schema half changed; the backup is the way back.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, inspect
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
BASELINE = "0001"
# Present in every database ember_api ever created.
LEGACY_MARKER_TABLE = "accounts"


class MigrationRunner:
    def __init__(
        self,
        engine: AsyncEngine,
        before_upgrade: Callable[[], Awaitable[object]] | None = None,
        scripts: Path = MIGRATIONS_DIR,
    ) -> None:
        self._engine = engine
        self._before_upgrade = before_upgrade
        self._scripts = scripts

    async def run(self) -> str:
        """Returns what was done: "current", "created", "stamped" or "upgraded"."""
        async with self._engine.connect() as conn:
            has_data, current, head = await conn.run_sync(self._state)
        if current == head:
            return "current"
        legacy = has_data and current is None
        starts_at = BASELINE if legacy else current
        if has_data and starts_at != head and self._before_upgrade is not None:
            await self._before_upgrade()
        async with self._engine.begin() as conn:
            await conn.run_sync(self._apply, legacy)
        if not has_data:
            return "created"
        return "upgraded" if starts_at != head else "stamped"

    async def revision(self, message: str) -> str:
        """Writes a new migration from the difference between the models and
        the database (brought up to date first); returns the file's path."""
        await self.run()
        async with self._engine.begin() as conn:
            script = await conn.run_sync(self._autogenerate, message)
        return str(script.path)

    async def current(self) -> tuple[str | None, str]:
        """(revision the database is at, newest revision)."""
        async with self._engine.connect() as conn:
            _, current, head = await conn.run_sync(self._state)
        return current, head

    def _config(self, connection: Connection) -> Config:
        config = Config()
        config.set_main_option("script_location", str(self._scripts))
        config.attributes["connection"] = connection
        return config

    def _state(self, connection: Connection) -> tuple[bool, str | None, str]:
        tables = set(inspect(connection).get_table_names())
        current = MigrationContext.configure(connection).get_current_revision()
        head = ScriptDirectory.from_config(self._config(connection)).get_current_head()
        return LEGACY_MARKER_TABLE in tables, current, str(head)

    def _apply(self, connection: Connection, legacy: bool) -> None:
        config = self._config(connection)
        if legacy:
            logger.info("database predates migrations; marking it as revision %s", BASELINE)
            command.stamp(config, BASELINE)
        command.upgrade(config, "head")

    def _autogenerate(self, connection: Connection, message: str):
        return command.revision(self._config(connection), message=message, autogenerate=True)
