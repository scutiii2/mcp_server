"""One-off move of chat_app's accounts, chats, token usage, activity log and
known devices into ember_api.

chat_app keeps its data in three SQLite files (`app.db`, `chats.db`,
`usage.db`). `ChatAppSource` reads them read-only; `ChatAppImporter` writes
what is missing into ember_api's database. Re-running is safe: an account
already imported is recognised, and its chats, usage rows, log entries and
devices are only added when absent.

`agent_map` renames chat_app's agent names (its provider names) to ember agent
ids, for rows being imported and for rows imported earlier under the old name.

Passwords move as they are: both apps store werkzeug hashes.
"""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Account, Chat, KnownDevice, LogEntry, Role, UsageRecord
from src.services.chat_service import MAX_CHATS_PER_ACCOUNT, TITLE_MAX, ChatLimitError, _encode

# What ember_api accepts in a chat id (routes/chats.py); chat_app ids can also
# hold "_", which ember_api's routes would refuse.
_CHAT_ID_OK = re.compile(r"^[A-Za-z0-9-]{8,64}$")
_CHAT_ID_BAD_CHARS = re.compile(r"[^A-Za-z0-9-]")
_FINGERPRINT = re.compile(r"[0-9a-f]{64}")
LOG_MESSAGE_MAX = 500


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


@dataclass(frozen=True)
class SourceLog:
    # None: the entry belongs to no account (or to one chat_app no longer has).
    username: str | None
    kind: str
    source: str
    message: str
    details: str | None
    created_at: datetime


@dataclass(frozen=True)
class SourceDevice:
    username: str
    fingerprint_hash: str
    first_seen_at: datetime
    last_seen_at: datetime


@dataclass
class SourceData:
    accounts: list[SourceAccount] = field(default_factory=list)
    chats: list[SourceChat] = field(default_factory=list)
    usage: list[SourceUsage] = field(default_factory=list)
    logs: list[SourceLog] = field(default_factory=list)
    devices: list[SourceDevice] = field(default_factory=list)
    # Files that were not there: the matching part is left out of the import.
    missing: list[str] = field(default_factory=list)


@dataclass
class TableReport:
    imported: int = 0
    skipped: int = 0
    failed: int = 0
    # Rows imported earlier under an old agent name, now given the mapped one.
    relabelled: int = 0
    notes: list[str] = field(default_factory=list)


@dataclass
class ImportReport:
    applied: bool = False
    accounts: TableReport = field(default_factory=TableReport)
    chats: TableReport = field(default_factory=TableReport)
    usage: TableReport = field(default_factory=TableReport)
    logs: TableReport = field(default_factory=TableReport)
    devices: TableReport = field(default_factory=TableReport)
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


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone()
    return row is not None


class ChatAppSource:
    """Reads chat_app's data folder without ever writing to it."""

    def __init__(self, data_dir: Path) -> None:
        self._dir = data_dir

    async def load(self) -> SourceData:
        return await asyncio.to_thread(self._load)

    def _load(self) -> SourceData:
        data = SourceData()
        for name, readers in (
            ("app.db", (self._read_accounts, self._read_logs, self._read_devices)),
            ("chats.db", (self._read_chats,)),
            ("usage.db", (self._read_usage,)),
        ):
            path = self._dir / name
            if not path.is_file():
                data.missing.append(name)
                continue
            conn = _read_only(path)
            try:
                for read in readers:
                    read(conn, data)
            finally:
                conn.close()
        return data

    @staticmethod
    def _usernames(conn: sqlite3.Connection) -> dict[int, str]:
        return {row["id"]: row["username"] for row in conn.execute("SELECT id, username FROM accounts")}

    @classmethod
    def _read_logs(cls, conn: sqlite3.Connection, data: SourceData) -> None:
        if not _has_table(conn, "log_entries"):
            data.missing.append("app.db: log_entries")
            return
        names = cls._usernames(conn)
        for row in conn.execute("SELECT * FROM log_entries ORDER BY created_at, id"):
            data.logs.append(
                SourceLog(
                    username=names.get(row["account_id"]),
                    kind=row["kind"],
                    source=row["source"],
                    message=row["message"],
                    details=row["details"],
                    created_at=to_naive_utc(row["created_at"]),
                )
            )

    @classmethod
    def _read_devices(cls, conn: sqlite3.Connection, data: SourceData) -> None:
        if not _has_table(conn, "device_fingerprints"):
            data.missing.append("app.db: device_fingerprints")
            return
        names = cls._usernames(conn)
        for row in conn.execute("SELECT * FROM device_fingerprints ORDER BY id"):
            username = names.get(row["account_id"])
            if username is None:
                continue
            data.devices.append(
                SourceDevice(
                    username=username,
                    fingerprint_hash=row["fingerprint_hash"],
                    first_seen_at=to_naive_utc(row["first_seen_at"]),
                    last_seen_at=to_naive_utc(row["last_seen_at"]),
                )
            )

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

    def __init__(
        self, session: AsyncSession, source: ChatAppSource, agent_map: dict[str, str] | None = None
    ) -> None:
        self._session = session
        self._source = source
        self._agent_map = dict(agent_map or {})

    def _mapped(self, agent: str | None) -> str | None:
        return self._agent_map.get(agent, agent) if agent else agent

    async def run(self, apply: bool) -> ImportReport:
        data = await self._source.load()
        report = ImportReport(applied=apply, missing_files=list(data.missing))
        try:
            owners = await self._import_accounts(data, report)
            await self._import_chats(data, owners, report)
            await self._import_usage(data, owners, report)
            await self._import_logs(data, owners, report)
            await self._import_devices(data, owners, report)
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
        have: dict[int, dict[str, str | None]] = {}
        for account in owners.values():
            rows = await self._session.execute(select(Chat.chat_id, Chat.agent_id).where(Chat.account_id == account.id))
            have[account.id] = {chat_id: agent for chat_id, agent in rows}

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
                old = agents.get(source.chat_id)
                new = self._mapped(old)
                # Only a chat still carrying the old name from chat_app is renamed.
                if new != old and ids[chat_id] == old:
                    await self._session.execute(
                        update(Chat).where(Chat.account_id == account.id, Chat.chat_id == chat_id).values(agent_id=new)
                    )
                    ids[chat_id] = new
                    table.relabelled += 1
                else:
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
                    agent_id=self._mapped(agents.get(source.chat_id)),
                    messages=text,
                    message_count=len(messages),
                    created_at=source.created_at,
                    updated_at=source.updated_at,
                )
            )
            ids[chat_id] = self._mapped(agents.get(source.chat_id))
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
        # The rows already there, by (time, tokens, agent, chat) -> their ids. A row
        # of chat_app is matched with one of them, so two identical turns stay two.
        seen: dict[int, dict[tuple, list[int]]] = {}
        for account in owners.values():
            rows = await self._session.execute(
                select(
                    UsageRecord.id, UsageRecord.created_at, UsageRecord.total_tokens, UsageRecord.agent, UsageRecord.chat_id
                ).where(UsageRecord.account_id == account.id)
            )
            by_key: dict[tuple, list[int]] = {}
            for row_id, *key in rows:
                by_key.setdefault(tuple(key), []).append(row_id)
            seen[account.id] = by_key
        turns: dict[tuple[int, datetime], str] = {}

        for source in data.usage:
            account = owners.get(source.username)
            if account is None or source.tokens <= 0:
                table.skipped += 1
                continue
            chat_id = ember_chat_id(source.chat_id) if source.chat_id else None
            agent = self._mapped(source.agent)
            there = seen[account.id]
            old_ids = there.get((source.ts, source.tokens, source.agent, chat_id))
            new_ids = there.get((source.ts, source.tokens, agent, chat_id))
            # Rows imported earlier under the old agent name get the mapped one.
            if agent != source.agent and old_ids:
                await self._session.execute(update(UsageRecord).where(UsageRecord.id == old_ids.pop()).values(agent=agent))
                table.relabelled += 1
                continue
            # Only rows already in ember_api count: two identical rows in chat_app are
            # two real turns, and a re-run finds both already there.
            if new_ids:
                new_ids.pop()
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
                    agent=agent,
                    model=source.model,
                    input_tokens=source.input_tokens,
                    output_tokens=source.output_tokens,
                    total_tokens=source.tokens,
                    created_at=source.ts,
                )
            )
            table.imported += 1
        await self._session.flush()

    async def _import_logs(self, data: SourceData, owners: dict[str, Account], report: ImportReport) -> None:
        """chat_app's activity log. An entry of an account that was not imported
        (ember_api has its own with that name) is kept with no account and the
        chat_app name added to its message; it is never attached to another person."""
        table = report.logs
        if not data.logs:
            return
        first = min(row.created_at for row in data.logs)
        last = max(row.created_at for row in data.logs)
        rows = await self._session.execute(
            select(LogEntry.kind, LogEntry.account_id, LogEntry.source, LogEntry.message, LogEntry.created_at).where(
                LogEntry.created_at >= first, LogEntry.created_at <= last
            )
        )
        there = Counter(tuple(row) for row in rows)
        for source in data.logs:
            account = owners.get(source.username) if source.username else None
            message = source.message
            if source.username and account is None:
                message = _with_origin(message, source.username)
            account_id = account.id if account else None
            key = (source.kind, account_id, source.source, message, source.created_at)
            # One-to-one, like usage rows: a re-run finds each already there.
            if there[key] > 0:
                there[key] -= 1
                table.skipped += 1
                continue
            self._session.add(
                LogEntry(
                    kind=source.kind,
                    account_id=account_id,
                    source=source.source,
                    message=message,
                    details=source.details,
                    created_at=source.created_at,
                )
            )
            table.imported += 1
        await self._session.flush()

    async def _import_devices(self, data: SourceData, owners: dict[str, Account], report: ImportReport) -> None:
        """Devices an imported account logged in from. chat_app and ember_api hash
        the same signals the same way, so a login from the same browser and
        network is not reported as a new device. The browser and network were
        never stored, so they show as unknown."""
        table = report.devices
        have: set[tuple[int, str]] = set()
        for account in owners.values():
            have.update(
                (account.id, h)
                for h in await self._session.scalars(
                    select(KnownDevice.fingerprint_hash).where(KnownDevice.account_id == account.id)
                )
            )
        for source in data.devices:
            account = owners.get(source.username)
            if account is None:
                table.skipped += 1
                continue
            if not _FINGERPRINT.fullmatch(source.fingerprint_hash):
                table.failed += 1
                table.notes.append(f"{source.username}: a device fingerprint is not a SHA-256 hash, left out")
                continue
            if (account.id, source.fingerprint_hash) in have:
                table.skipped += 1
                continue
            self._session.add(
                KnownDevice(
                    account_id=account.id,
                    fingerprint_hash=source.fingerprint_hash,
                    first_seen_at=source.first_seen_at,
                    last_seen_at=source.last_seen_at,
                )
            )
            have.add((account.id, source.fingerprint_hash))
            table.imported += 1
        await self._session.flush()


def _with_origin(message: str, username: str) -> str:
    """`message` with the chat_app account named at its end, within the column's size."""
    suffix = f" [chat_app: {username}]"
    room = LOG_MESSAGE_MAX - len(suffix)
    if len(message) > room:
        message = message[: room - 1] + "\u2026"
    return message + suffix
