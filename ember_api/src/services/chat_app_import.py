"""One-off move of chat_app's accounts, chats and token usage into ember_api.

chat_app keeps its data in three SQLite files (`app.db`, `chats.db`,
`usage.db`). `ChatAppSource` reads them read-only; `ChatAppImporter` writes
what is missing into ember_api's database. Re-running is safe: an account
already imported is recognised, and its chats and usage rows are only added
when absent.

Passwords move as they are: both apps store werkzeug hashes.
"""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Account, Chat, Role, UsageRecord
from src.services.chat_service import MAX_CHATS_PER_ACCOUNT, TITLE_MAX, ChatLimitError, _encode

# What ember_api accepts in a chat id (routes/chats.py); chat_app ids can also
# hold "_", which ember_api's routes would refuse.
_CHAT_ID_OK = re.compile(r"^[A-Za-z0-9-]{8,64}$")
_CHAT_ID_BAD_CHARS = re.compile(r"[^A-Za-z0-9-]")


@dataclass(frozen=True)
class SourceAccount:
    username: str
    email: str
    password_hash: str
    is_active: bool
    email_verified: bool
    created_at: datetime
    roles: tuple[str, ...]


@dataclass(frozen=True)
class SourceChat:
    chat_id: str
    username: str
    title: str
    messages_json: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class SourceUsage:
    username: str
    ts: datetime
    tokens: int
    agent: str | None
    model: str | None
    input_tokens: int | None
    output_tokens: int | None
    chat_id: str | None


@dataclass
class SourceData:
    accounts: list[SourceAccount] = field(default_factory=list)
    chats: list[SourceChat] = field(default_factory=list)
    usage: list[SourceUsage] = field(default_factory=list)
    # Files that were not there: the matching part is left out of the import.
    missing: list[str] = field(default_factory=list)


@dataclass
class TableReport:
    imported: int = 0
    skipped: int = 0
    failed: int = 0
    notes: list[str] = field(default_factory=list)


@dataclass
class ImportReport:
    applied: bool = False
    accounts: TableReport = field(default_factory=TableReport)
    chats: TableReport = field(default_factory=TableReport)
    usage: TableReport = field(default_factory=TableReport)
    roles_created: list[str] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)


def to_naive_utc(text: str) -> datetime:
    """chat_app writes ISO text with an offset (chats, usage) or a naive UTC
    time (accounts); ember_api stores naive UTC."""
    value = datetime.fromisoformat(text)
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def ember_chat_id(chat_id: str) -> str | None:
    """The chat_app id in a form ember_api's routes accept, or None."""
    cleaned = _CHAT_ID_BAD_CHARS.sub("-", chat_id)
    return cleaned if _CHAT_ID_OK.match(cleaned) else None


def _read_only(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


class ChatAppSource:
    """Reads chat_app's data folder without ever writing to it."""

    def __init__(self, data_dir: Path) -> None:
        self._dir = data_dir

    async def load(self) -> SourceData:
        return await asyncio.to_thread(self._load)

    def _load(self) -> SourceData:
        data = SourceData()
        for name, read in (
            ("app.db", self._read_accounts),
            ("chats.db", self._read_chats),
            ("usage.db", self._read_usage),
        ):
            path = self._dir / name
            if not path.is_file():
                data.missing.append(name)
                continue
            conn = _read_only(path)
            try:
                read(conn, data)
            finally:
                conn.close()
        return data

    @staticmethod
    def _read_accounts(conn: sqlite3.Connection, data: SourceData) -> None:
        roles: dict[int, list[str]] = {}
        for row in conn.execute(
            "SELECT ar.account_id AS account_id, r.name AS name FROM account_roles ar "
            "JOIN roles r ON r.id = ar.role_id ORDER BY r.name"
        ):
            roles.setdefault(row["account_id"], []).append(row["name"])
        for row in conn.execute("SELECT * FROM accounts ORDER BY id"):
            data.accounts.append(
                SourceAccount(
                    username=row["username"],
                    email=row["email"],
                    password_hash=row["password_hash"],
                    is_active=bool(row["is_active"]),
                    email_verified=bool(row["email_verified"]),
                    created_at=to_naive_utc(row["created_at"]),
                    roles=tuple(roles.get(row["id"], ())),
                )
            )

    @staticmethod
    def _read_chats(conn: sqlite3.Connection, data: SourceData) -> None:
        for row in conn.execute("SELECT * FROM chats ORDER BY created_at"):
            data.chats.append(
                SourceChat(
                    chat_id=row["id"],
                    username=row["username"],
                    title=row["title"],
                    messages_json=row["messages"],
                    created_at=to_naive_utc(row["created_at"]),
                    updated_at=to_naive_utc(row["updated_at"]),
                )
            )

    @staticmethod
    def _read_usage(conn: sqlite3.Connection, data: SourceData) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(token_usage)")}

        def optional(row: sqlite3.Row, name: str) -> Any:
            return row[name] if name in columns else None

        for row in conn.execute("SELECT * FROM token_usage ORDER BY ts, rowid"):
            data.usage.append(
                SourceUsage(
                    username=row["username"],
                    ts=to_naive_utc(row["ts"]),
                    tokens=int(row["tokens"]),
                    agent=optional(row, "agent"),
                    model=optional(row, "model"),
                    input_tokens=optional(row, "input_tokens"),
                    output_tokens=optional(row, "output_tokens"),
                    chat_id=optional(row, "chat_id"),
                )
            )


class ChatAppImporter:
    """Copies what ember_api lacks. With `apply` False everything is worked out
    in a transaction that is rolled back, so the report is exactly what an
    apply would do."""

    def __init__(self, session: AsyncSession, source: ChatAppSource) -> None:
        self._session = session
        self._source = source

    async def run(self, apply: bool) -> ImportReport:
        data = await self._source.load()
        report = ImportReport(applied=apply, missing_files=list(data.missing))
        try:
            owners = await self._import_accounts(data, report)
            await self._import_chats(data, owners, report)
            await self._import_usage(data, owners, report)
            if apply:
                await self._session.commit()
            else:
                await self._session.rollback()
        except BaseException:
            await self._session.rollback()
            raise
        return report

    async def _import_accounts(self, data: SourceData, report: ImportReport) -> dict[str, Account]:
        """Returns the ember_api account for each chat_app username whose data
        may follow: a new account, or one that is the same person already
        imported (same username, email and password hash)."""
        existing = list(await self._session.scalars(select(Account)))
        by_username = {a.username: a for a in existing}
        by_email = {a.email.lower(): a for a in existing}
        roles = {r.name: r for r in await self._session.scalars(select(Role))}
        owners: dict[str, Account] = {}
        table = report.accounts

        for source in data.accounts:
            same_name = by_username.get(source.username)
            same_mail = by_email.get(source.email.lower())
            if same_name is not None and same_name is same_mail and same_name.password_hash == source.password_hash:
                owners[source.username] = same_name
                table.skipped += 1
                table.notes.append(f"{source.username}: already imported")
                continue
            if same_name is not None or same_mail is not None:
                taken = "username" if same_name is not None else "email"
                table.skipped += 1
                table.notes.append(f"{source.username}: {taken} already used by another account; its chats and usage are skipped")
                continue

            account_roles = []
            for name in source.roles:
                if name not in roles:
                    roles[name] = Role(name=name, description="Created by the chat_app import; has no permissions")
                    self._session.add(roles[name])
                    report.roles_created.append(name)
                account_roles.append(roles[name])
            account = Account(
                username=source.username,
                email=source.email,
                password_hash=source.password_hash,
                # ember_api has its own protected bootstrap admin.
                is_protected=False,
                is_active=source.is_active,
                email_verified=source.email_verified,
                created_at=source.created_at,
                roles=account_roles,
            )
            self._session.add(account)
            by_username[account.username] = account
            by_email[account.email.lower()] = account
            owners[source.username] = account
            table.imported += 1
        await self._session.flush()
        return owners

    async def _import_chats(self, data: SourceData, owners: dict[str, Account], report: ImportReport) -> None:
        table = report.chats
        agents = self._latest_agents(data)
        have: dict[int, set[str]] = {}
        for account in owners.values():
            have[account.id] = set(
                await self._session.scalars(select(Chat.chat_id).where(Chat.account_id == account.id))
            )

        for source in data.chats:
            account = owners.get(source.username)
            if account is None:
                table.skipped += 1
                continue
            chat_id = ember_chat_id(source.chat_id)
            if chat_id is None:
                table.failed += 1
                table.notes.append(f"{source.username}: chat id {source.chat_id!r} cannot be used")
                continue
            ids = have[account.id]
            if chat_id in ids:
                table.skipped += 1
                continue
            if len(ids) >= MAX_CHATS_PER_ACCOUNT:
                table.failed += 1
                table.notes.append(f"{source.username}: over {MAX_CHATS_PER_ACCOUNT} chats, {chat_id} left out")
                continue
            try:
                messages = json.loads(source.messages_json)
                if not isinstance(messages, list):
                    raise ValueError("messages is not a list")
                text = _encode(messages)
            except (ValueError, ChatLimitError) as error:
                table.failed += 1
                table.notes.append(f"{source.username}: chat {chat_id} not imported ({error})")
                continue
            title = " ".join(source.title.split()) or "Imported chat"
            if len(title) > TITLE_MAX:
                title = title[: TITLE_MAX - 1] + "…"
            self._session.add(
                Chat(
                    account_id=account.id,
                    chat_id=chat_id,
                    title=title,
                    agent_id=agents.get(source.chat_id),
                    messages=text,
                    message_count=len(messages),
                    created_at=source.created_at,
                    updated_at=source.updated_at,
                )
            )
            ids.add(chat_id)
            table.imported += 1
        await self._session.flush()

    @staticmethod
    def _latest_agents(data: SourceData) -> dict[str, str]:
        """The agent a chat last used, from its usage rows (chat_app did not
        store one on the chat)."""
        latest: dict[str, str] = {}
        for row in data.usage:  # in time order, so the last one wins
            if row.chat_id and row.agent:
                latest[row.chat_id] = row.agent
        return latest

    async def _import_usage(self, data: SourceData, owners: dict[str, Account], report: ImportReport) -> None:
        table = report.usage
        seen: dict[int, set[tuple]] = {}
        for account in owners.values():
            rows = await self._session.execute(
                select(
                    UsageRecord.created_at, UsageRecord.total_tokens, UsageRecord.agent, UsageRecord.chat_id
                ).where(UsageRecord.account_id == account.id)
            )
            seen[account.id] = {tuple(row) for row in rows}
        turns: dict[tuple[int, datetime], str] = {}

        for source in data.usage:
            account = owners.get(source.username)
            if account is None or source.tokens <= 0:
                table.skipped += 1
                continue
            chat_id = ember_chat_id(source.chat_id) if source.chat_id else None
            key = (source.ts, source.tokens, source.agent, chat_id)
            # Only rows already in ember_api count: two identical rows in chat_app are
            # two real turns, and a re-run finds both already there.
            if key in seen[account.id]:
                table.skipped += 1
                continue
            # Rows of one turn share a timestamp in chat_app; keep them one turn.
            turn_id = turns.setdefault((account.id, source.ts), uuid.uuid4().hex)
            self._session.add(
                UsageRecord(
                    account_id=account.id,
                    turn_id=turn_id,
                    kind="chat",
                    chat_id=chat_id,
                    agent=source.agent,
                    model=source.model,
                    input_tokens=source.input_tokens,
                    output_tokens=source.output_tokens,
                    total_tokens=source.tokens,
                    created_at=source.ts,
                )
            )
            table.imported += 1
        await self._session.flush()
