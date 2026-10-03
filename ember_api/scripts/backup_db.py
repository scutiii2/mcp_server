"""Backs up ember_api's database now.

    python -m scripts.backup_db            (keeps the number set in config_app.json)
    python -m scripts.backup_db --keep 30

Safe while ember_api is running. Copies go to <database folder>/backups.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from src.config import load_settings
from src.services.backup_service import BackupError, DatabaseBackup


async def run(keep: int | None) -> Path:
    settings = load_settings()
    backup = DatabaseBackup(settings.database_path, settings.backup_dir, settings.backup.keep if keep is None else keep)
    return await backup.run()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--keep", type=int, help="how many backups to keep (default: backup.keep in config_app.json)")
    args = parser.parse_args(argv)
    if args.keep is not None and args.keep < 1:
        parser.error("--keep must be at least 1")
    try:
        print(f"Backup written: {asyncio.run(run(args.keep))}")
    except BackupError as error:
        print(f"Backup failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
