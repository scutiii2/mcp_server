"""Moves chat_app's accounts, chats, token usage, activity log and known devices into ember_api.

    python -m scripts.import_chat_app --chat-app ../chat_app            (dry run)
    python -m scripts.import_chat_app --chat-app ../chat_app --apply
    python -m scripts.import_chat_app --chat-app ../chat_app --apply --agent-map anthropic=claude-agent

--agent-map OLD=NEW (repeatable) renames a chat_app agent name (its provider) to an ember
agent id listed in ai_agent's registry (ai_agent must be running), for new rows and for rows
imported before under the old name.

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
from src.services.agent_directory import AgentDirectory
from src.db import Database
from src.services.chat_app_import import ChatAppImporter, ChatAppSource, ImportReport, TableReport
from src.services.migrations import MigrationRunner


def format_report(report: ImportReport) -> str:
    lines = ["APPLIED" if report.applied else "DRY RUN (nothing written)"]
    for name in report.missing_files:
        lines.append(f"  not found, left out: {name}")
    for label, table in (
        ("accounts", report.accounts),
        ("chats", report.chats),
        ("usage rows", report.usage),
        ("log entries", report.logs),
        ("devices", report.devices),
    ):
        lines.append(_table_line(label, table))
        lines.extend(f"    - {note}" for note in table.notes)
    if report.roles_created:
        lines.append("roles created with no permissions (give them some in the Admin page): " + ", ".join(report.roles_created))
    return "\n".join(lines)


def _table_line(label: str, table: TableReport) -> str:
    relabelled = f", {table.relabelled} relabelled" if table.relabelled else ""
    return f"{label}: {table.imported} imported, {table.skipped} skipped, {table.failed} failed{relabelled}"


def parse_agent_map(pairs: list[str]) -> dict[str, str]:
    """["old=new", ...] as a dict; SystemExit with a message for a bad pair."""
    mapping: dict[str, str] = {}
    for pair in pairs:
        old, sep, new = pair.partition("=")
        if not sep or not old.strip() or not new.strip():
            raise SystemExit(f"--agent-map wants OLD=NEW, not {pair!r}")
        if old.strip() in mapping:
            raise SystemExit(f"--agent-map names {old.strip()!r} twice")
        mapping[old.strip()] = new.strip()
    return mapping


async def check_agents(mapping: dict[str, str], registry: Path) -> None:
    """Every NEW must be an agent ai_agent has registered: a typo would label rows with a
    name nothing shows."""
    known = {agent.id for agent in await AgentDirectory(registry).all()}
    for old, new in mapping.items():
        if new not in known:
            have = ", ".join(sorted(known)) or "none (is ai_agent running?)"
            raise SystemExit(f"--agent-map {old}={new}: {new!r} is not a registered ember agent. Registered: {have}")


async def run(chat_app: Path, apply: bool, agent_map: dict[str, str] | None = None) -> ImportReport:
    settings = load_settings()
    await check_agents(agent_map or {}, settings.agents_registry_path)
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
            return await ChatAppImporter(session, ChatAppSource(data_dir), agent_map).run(apply)
    finally:
        await database.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--chat-app", type=Path, required=True, help="the chat_app folder (holds data/)")
    parser.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    parser.add_argument(
        "--agent-map", action="append", default=[], metavar="OLD=NEW",
        help="rename a chat_app agent name to an ember agent id (repeatable)",
    )
    args = parser.parse_args(argv)
    agent_map = parse_agent_map(args.agent_map)
    print(format_report(asyncio.run(run(args.chat_app, args.apply, agent_map))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
