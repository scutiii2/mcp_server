"""Durable storage behind an async interface.

`AscendedRepository.transaction()` yields a `AscendedTransaction`; everything done
inside commits together or not at all. The SQLite implementation uses the
standard-library driver on one shared connection: every call runs in a worker
thread, and a lock admits one transaction at a time, so the event loop never
blocks and a half-finished battle result can never be saved.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from concurrent.futures import Executor, ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncContextManager, AsyncIterator, Protocol

from src.ascension.errors import ActiveBattleExists, BattleAlreadyExists, StaleBattle
from src.ascension.models import BattleSetup, BattleState, PersonalityInstance
from src.ascension.records import (
    BattleRecord,
    EncounterRecord,
    IdempotencyRecord,
    PersonalityRecord,
    PlayerRecord,
    PresetRecord,
    AscendedRecord,
)

SCHEMA_VERSION = 2
SCHEMA = """
CREATE TABLE players (
    owner TEXT PRIMARY KEY, insignia INTEGER NOT NULL CHECK (insignia >= 0),
    last_roll_at REAL, created_at REAL NOT NULL);
CREATE TABLE emblems (
    owner TEXT NOT NULL, tier_id TEXT NOT NULL, count INTEGER NOT NULL CHECK (count >= 0),
    PRIMARY KEY (owner, tier_id));
CREATE TABLE ascendeds (
    owner TEXT NOT NULL, ascended_id TEXT NOT NULL, copies INTEGER NOT NULL CHECK (copies >= 0),
    level INTEGER NOT NULL, xp INTEGER NOT NULL, faint_until REAL,
    PRIMARY KEY (owner, ascended_id));
CREATE TABLE personalities (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE, owner TEXT NOT NULL,
    ascended_id TEXT NOT NULL, type_id TEXT NOT NULL, tier INTEGER NOT NULL, created_at REAL NOT NULL);
CREATE INDEX personalities_by_ascended ON personalities (owner, ascended_id, seq);
CREATE TABLE presets (
    owner TEXT NOT NULL, ascended_id TEXT NOT NULL, slot INTEGER NOT NULL CHECK (slot BETWEEN 1 AND 5),
    instance_ids TEXT NOT NULL, PRIMARY KEY (owner, ascended_id, slot));
CREATE TABLE encounters (
    id TEXT PRIMARY KEY, owner TEXT NOT NULL, ascended_id TEXT NOT NULL, tier_id TEXT NOT NULL,
    level INTEGER NOT NULL, status TEXT NOT NULL, wild_personalities TEXT NOT NULL, created_at REAL NOT NULL);
CREATE INDEX encounters_by_owner ON encounters (owner, status);
CREATE TABLE battles (
    id TEXT PRIMARY KEY, owner TEXT NOT NULL, encounter_id TEXT NOT NULL UNIQUE, status TEXT NOT NULL,
    phase TEXT NOT NULL CHECK (phase IN ('choosing', 'awaiting_emblem', 'terminal')), mode TEXT NOT NULL, revision INTEGER NOT NULL, setup TEXT NOT NULL, state TEXT NOT NULL,
    player_personalities TEXT NOT NULL, wild_personalities TEXT NOT NULL, emblem_limit TEXT,
    rng_seed INTEGER NOT NULL, rng_counter INTEGER NOT NULL, pending TEXT, result TEXT,
    created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE UNIQUE INDEX one_active_battle ON battles (owner) WHERE status = 'active';
CREATE TABLE rounds (
    battle_id TEXT NOT NULL, round_number INTEGER NOT NULL, record TEXT NOT NULL,
    PRIMARY KEY (battle_id, round_number));
CREATE TABLE idempotency (
    owner TEXT NOT NULL, key TEXT NOT NULL, request_hash TEXT NOT NULL, response TEXT NOT NULL,
    created_at REAL NOT NULL, PRIMARY KEY (owner, key));
"""


class AscendedTransaction(Protocol):
    """Everything a service may read or write inside one transaction."""

    async def get_player(self, owner: str) -> PlayerRecord | None: ...
    async def create_player(self, owner: str, now: float) -> None: ...
    async def add_insignia(self, owner: str, delta: int) -> None: ...
    async def set_last_roll(self, owner: str, when: float) -> None: ...
    async def emblem_counts(self, owner: str) -> dict[str, int]: ...
    async def add_emblems(self, owner: str, tier_id: str, delta: int) -> None: ...
    async def get_ascended(self, owner: str, ascended_id: str) -> AscendedRecord | None: ...
    async def list_ascendeds(self, owner: str) -> list[AscendedRecord]: ...
    async def put_ascended(self, record: AscendedRecord) -> None: ...
    async def add_personality(self, record: PersonalityRecord) -> None: ...
    async def list_personalities(self, owner: str, ascended_id: str, limit: int, after_seq: int) -> list[PersonalityRecord]: ...
    async def get_personalities(self, owner: str, ascended_id: str, ids: list[str]) -> list[PersonalityRecord]: ...
    async def get_preset(self, owner: str, ascended_id: str, slot: int) -> PresetRecord | None: ...
    async def list_presets(self, owner: str, ascended_id: str) -> list[PresetRecord]: ...
    async def put_preset(self, record: PresetRecord) -> None: ...
    async def add_encounter(self, record: EncounterRecord) -> None: ...
    async def get_encounter(self, owner: str, encounter_id: str) -> EncounterRecord | None: ...
    async def pending_encounter(self, owner: str) -> EncounterRecord | None: ...
    async def set_encounter_status(self, encounter_id: str, status: str) -> None: ...
    async def add_battle(self, record: BattleRecord) -> None: ...
    async def get_battle(self, owner: str, battle_id: str) -> BattleRecord | None: ...
    async def active_battle(self, owner: str) -> BattleRecord | None: ...
    async def save_battle(self, record: BattleRecord, expected_revision: int) -> None: ...
    async def add_round(self, battle_id: str, round_number: int, record: dict[str, Any]) -> None: ...
    async def get_idempotent(self, owner: str, key: str) -> IdempotencyRecord | None: ...
    async def put_idempotent(self, owner: str, key: str, request_hash: str, response: dict[str, Any], now: float) -> None: ...
    async def delete_player_data(self, owner: str) -> None: ...


class AscendedRepository(Protocol):
    def transaction(self) -> AsyncContextManager[AscendedTransaction]: ...


async def _in_thread(executor: Executor, fn: Any, *args: Any) -> Any:
    """Run blocking `fn` on the repository's own worker and, if the caller is cancelled
    meanwhile, still wait for it to finish before re-raising, so the shared connection is
    never used by a worker after its owner (and the transaction lock) has moved on."""
    task = asyncio.ensure_future(asyncio.get_running_loop().run_in_executor(executor, fn, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.wait([task])
            except asyncio.CancelledError:
                pass
        raise


def _dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))


def _instances(raw: str) -> tuple[PersonalityInstance, ...]:
    return tuple(PersonalityInstance.from_dict(i) for i in json.loads(raw))


class _SqliteTransaction:
    def __init__(self, conn: sqlite3.Connection, executor: Executor) -> None:
        self._conn = conn
        self._executor = executor

    async def _run(self, sql: str, params: tuple = (), mode: str = "none") -> Any:
        def work() -> Any:
            cursor = self._conn.execute(sql, params)
            if mode == "one":
                return cursor.fetchone()
            if mode == "all":
                return cursor.fetchall()
            return cursor.rowcount

        return await _in_thread(self._executor, work)

    # -- players and wallet --------------------------------------------------------

    async def get_player(self, owner: str) -> PlayerRecord | None:
        row = await self._run("SELECT * FROM players WHERE owner = ?", (owner,), "one")
        return PlayerRecord(row["owner"], row["insignia"], row["last_roll_at"], row["created_at"]) if row else None

    async def create_player(self, owner: str, now: float) -> None:
        await self._run("INSERT INTO players (owner, insignia, created_at) VALUES (?, 0, ?)", (owner, now))

    async def add_insignia(self, owner: str, delta: int) -> None:
        await self._run("UPDATE players SET insignia = insignia + ? WHERE owner = ?", (delta, owner))

    async def set_last_roll(self, owner: str, when: float) -> None:
        await self._run("UPDATE players SET last_roll_at = ? WHERE owner = ?", (when, owner))

    async def emblem_counts(self, owner: str) -> dict[str, int]:
        rows = await self._run("SELECT tier_id, count FROM emblems WHERE owner = ? AND count > 0", (owner,), "all")
        return {row["tier_id"]: row["count"] for row in rows}

    async def add_emblems(self, owner: str, tier_id: str, delta: int) -> None:
        # Update first: an upsert would check the raw delta against count >= 0 even for an existing row.
        changed = await self._run("UPDATE emblems SET count = count + ? WHERE owner = ? AND tier_id = ?", (delta, owner, tier_id))
        if changed == 0:
            await self._run("INSERT INTO emblems (owner, tier_id, count) VALUES (?, ?, ?)", (owner, tier_id, delta))

    # -- Ascended, personalities, presets --------------------------------------------

    @staticmethod
    def _ascended(row: sqlite3.Row) -> AscendedRecord:
        return AscendedRecord(row["owner"], row["ascended_id"], row["copies"], row["level"], row["xp"], row["faint_until"])

    async def get_ascended(self, owner: str, ascended_id: str) -> AscendedRecord | None:
        row = await self._run("SELECT * FROM ascendeds WHERE owner = ? AND ascended_id = ?", (owner, ascended_id), "one")
        return self._ascended(row) if row else None

    async def list_ascendeds(self, owner: str) -> list[AscendedRecord]:
        rows = await self._run("SELECT * FROM ascendeds WHERE owner = ? ORDER BY ascended_id", (owner,), "all")
        return [self._ascended(r) for r in rows]

    async def put_ascended(self, record: AscendedRecord) -> None:
        await self._run(
            "INSERT INTO ascendeds (owner, ascended_id, copies, level, xp, faint_until) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (owner, ascended_id) DO UPDATE SET copies = excluded.copies, level = excluded.level, "
            "xp = excluded.xp, faint_until = excluded.faint_until",
            (record.owner, record.ascended_id, record.copies, record.level, record.xp, record.faint_until),
        )

    @staticmethod
    def _personality(row: sqlite3.Row) -> PersonalityRecord:
        return PersonalityRecord(row["id"], row["owner"], row["ascended_id"], row["type_id"], row["tier"],
                                 row["created_at"], row["seq"])

    async def add_personality(self, record: PersonalityRecord) -> None:
        await self._run(
            "INSERT INTO personalities (id, owner, ascended_id, type_id, tier, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (record.id, record.owner, record.ascended_id, record.type_id, record.tier, record.created_at),
        )

    async def list_personalities(self, owner: str, ascended_id: str, limit: int, after_seq: int) -> list[PersonalityRecord]:
        rows = await self._run(
            "SELECT * FROM personalities WHERE owner = ? AND ascended_id = ? AND seq > ? ORDER BY seq LIMIT ?",
            (owner, ascended_id, after_seq, limit), "all",
        )
        return [self._personality(r) for r in rows]

    async def get_personalities(self, owner: str, ascended_id: str, ids: list[str]) -> list[PersonalityRecord]:
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        rows = await self._run(
            f"SELECT * FROM personalities WHERE owner = ? AND ascended_id = ? AND id IN ({marks})",
            (owner, ascended_id, *ids), "all",
        )
        return [self._personality(r) for r in rows]

    async def get_preset(self, owner: str, ascended_id: str, slot: int) -> PresetRecord | None:
        row = await self._run(
            "SELECT * FROM presets WHERE owner = ? AND ascended_id = ? AND slot = ?", (owner, ascended_id, slot), "one")
        return PresetRecord(owner, ascended_id, slot, tuple(json.loads(row["instance_ids"]))) if row else None

    async def list_presets(self, owner: str, ascended_id: str) -> list[PresetRecord]:
        rows = await self._run(
            "SELECT * FROM presets WHERE owner = ? AND ascended_id = ? ORDER BY slot", (owner, ascended_id), "all")
        return [PresetRecord(owner, ascended_id, r["slot"], tuple(json.loads(r["instance_ids"]))) for r in rows]

    async def put_preset(self, record: PresetRecord) -> None:
        await self._run(
            "INSERT INTO presets (owner, ascended_id, slot, instance_ids) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (owner, ascended_id, slot) DO UPDATE SET instance_ids = excluded.instance_ids",
            (record.owner, record.ascended_id, record.slot, _dumps(list(record.instance_ids))),
        )

    # -- encounters ----------------------------------------------------------------

    @staticmethod
    def _encounter(row: sqlite3.Row) -> EncounterRecord:
        return EncounterRecord(row["id"], row["owner"], row["ascended_id"], row["tier_id"], row["level"], row["status"],
                               _instances(row["wild_personalities"]), row["created_at"])

    async def add_encounter(self, record: EncounterRecord) -> None:
        await self._run(
            "INSERT INTO encounters (id, owner, ascended_id, tier_id, level, status, wild_personalities, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (record.id, record.owner, record.ascended_id, record.tier_id, record.level, record.status,
             _dumps([i.to_dict() for i in record.wild_personalities]), record.created_at),
        )

    async def get_encounter(self, owner: str, encounter_id: str) -> EncounterRecord | None:
        row = await self._run("SELECT * FROM encounters WHERE owner = ? AND id = ?", (owner, encounter_id), "one")
        return self._encounter(row) if row else None

    async def pending_encounter(self, owner: str) -> EncounterRecord | None:
        row = await self._run(
            "SELECT * FROM encounters WHERE owner = ? AND status = 'pending' ORDER BY created_at DESC, rowid DESC LIMIT 1", (owner,), "one")
        return self._encounter(row) if row else None

    async def set_encounter_status(self, encounter_id: str, status: str) -> None:
        await self._run("UPDATE encounters SET status = ? WHERE id = ?", (status, encounter_id))

    # -- battles -------------------------------------------------------------------

    @staticmethod
    def _battle(row: sqlite3.Row) -> BattleRecord:
        return BattleRecord(
            id=row["id"], owner=row["owner"], encounter_id=row["encounter_id"], status=row["status"], phase=row["phase"],
            mode=row["mode"], revision=row["revision"], setup=BattleSetup.from_dict(json.loads(row["setup"])),
            state=BattleState.from_dict(json.loads(row["state"])),
            player_personalities=_instances(row["player_personalities"]), wild_personalities=_instances(row["wild_personalities"]),
            emblem_limit=row["emblem_limit"], rng_seed=row["rng_seed"], rng_counter=row["rng_counter"],
            created_at=row["created_at"], updated_at=row["updated_at"],
            pending=json.loads(row["pending"]) if row["pending"] else None,
            result=json.loads(row["result"]) if row["result"] else None,
        )

    @staticmethod
    def _battle_values(r: BattleRecord) -> tuple:
        return (
            r.status, r.phase, r.mode, r.revision, _dumps(r.setup.to_dict()), _dumps(r.state.to_dict()),
            _dumps([i.to_dict() for i in r.player_personalities]), _dumps([i.to_dict() for i in r.wild_personalities]),
            r.emblem_limit, r.rng_seed, r.rng_counter, _dumps(r.pending) if r.pending is not None else None,
            _dumps(r.result) if r.result is not None else None, r.updated_at,
        )

    async def add_battle(self, record: BattleRecord) -> None:
        try:
            await self._run(
                "INSERT INTO battles (id, owner, encounter_id, created_at, status, phase, mode, revision, setup, state, "
                "player_personalities, wild_personalities, emblem_limit, rng_seed, rng_counter, pending, result, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (record.id, record.owner, record.encounter_id, record.created_at, *self._battle_values(record)),
            )
        except sqlite3.IntegrityError as error:
            message = str(error)
            if "battles.owner" in message:  # the one_active_battle partial unique index
                raise ActiveBattleExists("finish or forfeit the active battle first") from error
            if "battles.id" in message or "battles.encounter_id" in message:
                raise BattleAlreadyExists("a battle already exists for this id or encounter") from error
            raise

    async def get_battle(self, owner: str, battle_id: str) -> BattleRecord | None:
        row = await self._run("SELECT * FROM battles WHERE owner = ? AND id = ?", (owner, battle_id), "one")
        return self._battle(row) if row else None

    async def active_battle(self, owner: str) -> BattleRecord | None:
        row = await self._run("SELECT * FROM battles WHERE owner = ? AND status = 'active'", (owner,), "one")
        return self._battle(row) if row else None

    async def save_battle(self, record: BattleRecord, expected_revision: int) -> None:
        changed = await self._run(
            "UPDATE battles SET status = ?, phase = ?, mode = ?, revision = ?, setup = ?, state = ?, "
            "player_personalities = ?, wild_personalities = ?, emblem_limit = ?, rng_seed = ?, rng_counter = ?, "
            "pending = ?, result = ?, updated_at = ? WHERE id = ? AND revision = ?",
            (*self._battle_values(record), record.id, expected_revision),
        )
        if changed != 1:
            raise StaleBattle("the battle changed; reload it and try again")

    async def add_round(self, battle_id: str, round_number: int, record: dict[str, Any]) -> None:
        await self._run(
            "INSERT OR REPLACE INTO rounds (battle_id, round_number, record) VALUES (?, ?, ?)",
            (battle_id, round_number, _dumps(record)),
        )

    # -- idempotency ---------------------------------------------------------------

    async def get_idempotent(self, owner: str, key: str) -> IdempotencyRecord | None:
        row = await self._run("SELECT * FROM idempotency WHERE owner = ? AND key = ?", (owner, key), "one")
        return IdempotencyRecord(row["request_hash"], json.loads(row["response"])) if row else None

    async def put_idempotent(self, owner: str, key: str, request_hash: str, response: dict[str, Any], now: float) -> None:
        await self._run(
            "INSERT INTO idempotency (owner, key, request_hash, response, created_at) VALUES (?, ?, ?, ?, ?)",
            (owner, key, request_hash, _dumps(response), now),
        )

    # -- reset ---------------------------------------------------------------------

    async def delete_player_data(self, owner: str) -> None:
        # Rounds carry no owner, so they go first, through the owner's battle ids.
        await self._run("DELETE FROM rounds WHERE battle_id IN (SELECT id FROM battles WHERE owner = ?)", (owner,))
        await self._run("DELETE FROM battles WHERE owner = ?", (owner,))
        await self._run("DELETE FROM encounters WHERE owner = ?", (owner,))
        await self._run("DELETE FROM presets WHERE owner = ?", (owner,))
        await self._run("DELETE FROM personalities WHERE owner = ?", (owner,))
        await self._run("DELETE FROM ascendeds WHERE owner = ?", (owner,))
        await self._run("DELETE FROM emblems WHERE owner = ?", (owner,))
        await self._run("DELETE FROM players WHERE owner = ?", (owner,))
        await self._run("DELETE FROM idempotency WHERE owner = ?", (owner,))


class SqliteAscendedRepository:
    def __init__(self, path: Path | str) -> None:
        self._path = str(path)
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()
        self._executor: ThreadPoolExecutor | None = None

    def _pool(self) -> ThreadPoolExecutor:
        """One worker, like the one connection: other pools (Laya's, the default) can never starve it."""
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ascendeds-sqlite")
        return self._executor

    def _open(self) -> sqlite3.Connection:
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                conn.executescript(f"BEGIN; {SCHEMA} PRAGMA user_version = {SCHEMA_VERSION}; COMMIT;")
            elif version != SCHEMA_VERSION:
                raise RuntimeError(f"database schema version {version} is not supported (expected {SCHEMA_VERSION})")
        except BaseException:
            conn.close()
            raise
        return conn

    @staticmethod
    def _rollback(conn: sqlite3.Connection) -> None:
        # Best effort: a failed rollback must not mask the error that caused it.
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass

    @staticmethod
    def _commit(conn: sqlite3.Connection) -> None:
        try:
            conn.execute("COMMIT")
        except BaseException:
            SqliteAscendedRepository._rollback(conn)
            raise

    def _connect(self) -> None:
        # Stores the connection from inside the worker, so a caller cancelled mid-open
        # cannot orphan it: close() always finds and closes it.
        self._conn = self._open()

    @staticmethod
    def _begin(conn: sqlite3.Connection) -> None:
        if conn.in_transaction:  # a stray transaction from an interrupted caller
            SqliteAscendedRepository._rollback(conn)
        conn.execute("BEGIN IMMEDIATE")

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AscendedTransaction]:
        async with self._lock:
            if self._conn is None:
                await _in_thread(self._pool(), self._connect)
            conn = self._conn
            try:
                await _in_thread(self._pool(), self._begin, conn)
                yield _SqliteTransaction(conn, self._pool())
            except BaseException:
                await _in_thread(self._pool(), self._rollback, conn)
                raise
            else:
                # Commit or roll back as one step the lock outlives, even if the caller is cancelled.
                await _in_thread(self._pool(), self._commit, conn)

    async def close(self) -> None:
        async with self._lock:
            if self._conn is not None:
                await _in_thread(self._pool(), self._conn.close)
                self._conn = None
            if self._executor is not None:
                self._executor.shutdown(wait=True)
                self._executor = None
