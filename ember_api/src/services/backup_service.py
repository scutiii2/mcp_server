"""Backups of ember_api's SQLite database.

`DatabaseBackup` copies the file with SQLite's own online backup (safe while
the app is writing), checks the copy, and keeps only the newest few.
`BackupScheduler` runs it in the background, and after a restart waits only
as long as is left of the interval, so restarting often does not pile up copies.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import Awaitable, Callable
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

from src.db import utcnow

logger = logging.getLogger(__name__)

STAMP_FORMAT = "%Y%m%d-%H%M%S"


class BackupError(Exception):
    """A backup could not be made; the message is safe to log."""


class DatabaseBackup:
    """Copies one SQLite file into `folder` as `<name>-<UTC timestamp>.db`,
    keeping the newest `keep` copies of that name."""

    def __init__(
        self, source: Path, folder: Path, keep: int, clock: Callable[[], datetime] = utcnow
    ) -> None:
        if keep < 1:
            raise ValueError("keep must be at least 1")
        self._source = source
        self._folder = folder
        self._keep = keep
        self._clock = clock

    async def run(self) -> Path:
        """Makes one backup off the event loop and returns its path."""
        return await asyncio.to_thread(self._run)

    def existing(self) -> list[Path]:
        """This database's backups, oldest first."""
        return sorted(self._folder.glob(f"{self._source.stem}-*.db"))

    def seconds_until_due(self, every: timedelta) -> float:
        """0 when no backup exists or the newest is `every` old or older; else the time left."""
        newest = next(iter(reversed(self.existing())), None)
        if newest is None:
            return 0.0
        taken = self._taken_at(newest)
        if taken is None:
            return 0.0
        return max(0.0, (taken + every - self._clock()).total_seconds())

    def _taken_at(self, path: Path) -> datetime | None:
        stamp = path.stem.removeprefix(f"{self._source.stem}-")
        try:
            return datetime.strptime(stamp, STAMP_FORMAT)
        except ValueError:
            return None

    def _run(self) -> Path:
        if not self._source.is_file():
            raise BackupError(f"database not found: {self._source}")
        self._folder.mkdir(parents=True, exist_ok=True)
        final = self._folder / f"{self._source.stem}-{self._clock().strftime(STAMP_FORMAT)}.db"
        partial = final.with_name(final.name + ".partial")
        try:
            # Read-only: a backup can never change the database it copies.
            with closing(sqlite3.connect(f"{self._source.resolve().as_uri()}?mode=ro", uri=True)) as source:
                with closing(sqlite3.connect(partial)) as target:
                    source.backup(target)
                    verdict = self._integrity(target)
            if verdict != "ok":
                raise BackupError(f"the copy failed its integrity check: {verdict}")
            partial.replace(final)
        except BackupError:
            partial.unlink(missing_ok=True)
            raise
        except (sqlite3.Error, OSError) as error:
            partial.unlink(missing_ok=True)
            raise BackupError(f"{type(error).__name__}: {error}") from error
        self._prune()
        return final

    @staticmethod
    def _integrity(database: sqlite3.Connection) -> str:
        """SQLite's own quick check of a database: "ok", or what it found wrong."""
        row = database.execute("PRAGMA quick_check").fetchone()
        return str(row[0]) if row else "no answer"

    def _prune(self) -> None:
        for old in self.existing()[: -self._keep]:
            try:
                old.unlink()
            except OSError as error:
                logger.warning("could not remove the old backup %s: %s", old, error)


class BackupScheduler:
    """Runs a backup whenever one is due, until stopped."""

    def __init__(
        self,
        backup: DatabaseBackup,
        every: timedelta,
        on_error: Callable[[str], Awaitable[None]] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._backup = backup
        self._every = every
        self._on_error = on_error
        self._sleep = sleep
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="database-backups")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _loop(self) -> None:
        while True:
            await self._sleep(await asyncio.to_thread(self._backup.seconds_until_due, self._every))
            try:
                path = await self._backup.run()
                logger.info("database backup written: %s", path)
            except BackupError as error:
                logger.error("database backup failed: %s", error)
                if self._on_error is not None:
                    await self._on_error(str(error))
                # Not due again until a backup exists: wait a full interval rather than retrying in a tight loop.
                await self._sleep(self._every.total_seconds())
