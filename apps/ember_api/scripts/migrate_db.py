"""Shows or changes ember_api's database schema.

    python -m scripts.migrate_db status            (revision the database is at, and the newest)
    python -m scripts.migrate_db upgrade           (what ember_api does at startup, after a backup)
    python -m scripts.migrate_db revision "add the foo column"
                                                   (writes a new migration from your model edits)

Stop ember_api before `upgrade`. Review the file `revision` writes before using it.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from src.config import load_settings
from src.db import Database
from src.services.backup_service import BackupError, DatabaseBackup
from src.services.migrations import MigrationRunner


async def run(action: str, message: str | None) -> str:
    settings = load_settings()
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    database = Database(settings.database_url)
    try:
        backup = DatabaseBackup(settings.database_path, settings.backup_dir, settings.backup.keep)
        runner = MigrationRunner(database.engine, before_upgrade=backup.run)
        if action == "status":
            current, head = await runner.current()
            return f"database: {current or 'not migrated yet'}, newest: {head}"
        if action == "upgrade":
            return f"result: {await runner.run()}"
        return f"written: {await runner.revision(message or '')}"
    finally:
        await database.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("status")
    actions.add_parser("upgrade")
    revision = actions.add_parser("revision")
    revision.add_argument("message", help="what the migration does, in a few words")
    args = parser.parse_args(argv)
    try:
        print(asyncio.run(run(args.action, getattr(args, "message", None))))
    except BackupError as error:
        print(f"Backup failed, nothing changed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
