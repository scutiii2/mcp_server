"""Moves chat_app's accounts, chats and token usage into ember_api.

    python -m scripts.import_chat_app --chat-app ../chat_app            (dry run)
    python -m scripts.import_chat_app --chat-app ../chat_app --apply

Run from ember_api/ with ember_api stopped. A dry run changes nothing and
prints what an apply would do. --apply first copies ember_api's database to
<name>.bak-<timestamp>. chat_app's files are only ever read.
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
from datetime import datetime
from pathlib import Path

from src.config import load_settings
from src.db import Database
from src.services.chat_app_import import ChatAppImporter, ChatAppSource, ImportReport, TableReport
from src.services.migrations import MigrationRunner


def format_report(report: ImportReport) -> str:
    lines = ["APPLIED" if report.applied else "DRY RUN (nothing written)"]
    for name in report.missing_files:
        lines.append(f"  not found, left out: {name}")
    for label, table in (("accounts", report.accounts), ("chats", report.chats), ("usage rows", report.usage)):
        lines.append(_table_line(label, table))
        lines.extend(f"    - {note}" for note in table.notes)
    if report.roles_created:
        lines.append("roles created with no permissions (give them some in the Admin page): " + ", ".join(report.roles_created))
    return "\n".join(lines)


def _table_line(label: str, table: TableReport) -> str:
    return f"{label}: {table.imported} imported, {table.skipped} skipped, {table.failed} failed"


async def run(chat_app: Path, apply: bool) -> ImportReport:
    settings = load_settings()
    data_dir = chat_app / "data"
    if not data_dir.is_dir():
        raise SystemExit(f"No data folder at {data_dir}")
    if apply and settings.database_path.is_file():
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        backup = settings.database_path.with_name(f"{settings.database_path.name}.bak-{stamp}")
        await asyncio.to_thread(shutil.copyfile, settings.database_path, backup)
        print(f"Backup: {backup}")
    database = Database(settings.database_url)
    try:
        await MigrationRunner(database.engine).run()
        async with database.sessions() as session:
            return await ChatAppImporter(session, ChatAppSource(data_dir)).run(apply)
    finally:
        await database.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--chat-app", type=Path, required=True, help="the chat_app folder (holds data/)")
    parser.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    args = parser.parse_args(argv)
    print(format_report(asyncio.run(run(args.chat_app, args.apply))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
