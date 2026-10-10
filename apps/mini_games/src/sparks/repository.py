"""Durable storage behind an async interface.

`SparkRepository.transaction()` yields a `SparkTransaction`; everything done
inside commits together or not at all. The SQLite implementation uses the
standard-library driver on one shared connection: every call runs in a worker
thread, and a lock admits one transaction at a time, so the event loop never
blocks and a half-finished battle result can never be saved.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncContextManager, AsyncIterator, Protocol

from src.sparks.errors import ActiveBattleExists, BattleAlreadyExists, StaleBattle
from src.sparks.models import BattleSetup, BattleState, PersonalityInstance
from src.sparks.records import (
    BattleRecord,
    EncounterRecord,
    IdempotencyRecord,
    PersonalityRecord,
    PlayerRecord,
    PresetRecord,
    SparkRecord,
)

SCHEMA_VERSION = 1
SCHEMA = """
CREATE TABLE players (
    owner TEXT PRIMARY KEY, insignia INTEGER NOT NULL CHECK (insignia >= 0),
    last_roll_at REAL, created_at REAL NOT NULL);
CREATE TABLE emblems (
    owner TEXT NOT NULL, tier_id TEXT NOT NULL, count INTEGER NOT NULL CHECK (count >= 0),
    PRIMARY KEY (owner, tier_id));
CREATE TABLE sparks (
    owner TEXT NOT NULL, species_id TEXT NOT NULL, copies INTEGER NOT NULL CHECK (copies >= 0),
    level INTEGER NOT NULL, xp INTEGER NOT NULL, faint_until REAL,
    PRIMARY KEY (owner, species_id));
CREATE TABLE personalities (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE, owner TEXT NOT NULL,
    species_id TEXT NOT NULL, type_id TEXT NOT NULL, tier INTEGER NOT NULL, created_at REAL NOT NULL);
CREATE INDEX personalities_by_species ON personalities (owner, species_id, seq);
CREATE TABLE presets (
    owner TEXT NOT NULL, species_id TEXT NOT NULL, slot INTEGER NOT NULL CHECK (slot BETWEEN 1 AND 5),
    instance_ids TEXT NOT NULL, PRIMARY KEY (owner, species_id, slot));
CREATE TABLE encounters (
    id TEXT PRIMARY KEY, owner TEXT NOT NULL, species_id TEXT NOT NULL, tier_id TEXT NOT NULL,
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


class SparkTransaction(Protocol):
    """Everything a service may read or write inside one transaction."""

    async def get_player(self, owner: str) -> PlayerRecord | None: ...
    async def create_player(self, owner: str, now: float) -> None: ...
    async def add_insignia(self, owner: str, delta: int) -> None: ...
    async def set_last_roll(self, owner: str, when: float) -> None: ...
    async def emblem_counts(self, owner: str) -> dict[str, int]: ...
    async def add_emblems(self, owner: str, tier_id: str, delta: int) -> None: ...
    async def get_spark(self, owner: str, species_id: str) -> SparkRecord | None: ...
    async def list_sparks(self, owner: str) -> list[SparkRecord]: ...
    async def put_spark(self, record: SparkRecord) -> None: ...
    async def add_personality(self, record: PersonalityRecord) -> None: ...
    async def list_personalities(self, owner: str, species_id: str, limit: int, after_seq: int) -> list[PersonalityRecord]: ...
    async def get_personalities(self, owner: str, species_id: str, ids: list[str]) -> list[PersonalityRecord]: ...
    async def get_preset(self, owner: str, species_id: str, slot: int) -> PresetRecord | None: ...
    async def list_presets(self, owner: str, species_id: str) -> list[PresetRecord]: ...
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


class SparkRepository(Protocol):
    def transaction(self) -> AsyncContextManager[SparkTransaction]: ...


async def _in_thread(fn: Any, *args: Any) -> Any:
    """Run blocking `fn` in a worker thread and, if the caller is cancelled meanwhile,
    still wait for the thread to finish before re-raising, so the shared connection is
    never used by a worker after its owner (and the transaction lock) has moved on."""
    task = asyncio.ensure_future(asyncio.to_thread(fn, *args))
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
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    async def _run(self, sql: str, params: tuple = (), mode: str = "none") -> Any:
        def work() -> Any:
            cursor = self._conn.execute(sql, params)
            if mode == "one":
                return cursor.fetchone()
            if mode == "all":
                return cursor.fetchall()
            return cursor.rowcount

        return await _in_thread(work)

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

    # -- sparks, personalities, presets --------------------------------------------

    @staticmethod
    def _spark(row: sqlite3.Row) -> SparkRecord:
        return SparkRecord(row["owner"], row["species_id"], row["copies"], row["level"], row["xp"], row["faint_until"])

    async def get_spark(self, owner: str, species_id: str) -> SparkRecord | None:
        row = await self._run("SELECT * FROM sparks WHERE owner = ? AND species_id = ?", (owner, species_id), "one")
        return self._spark(row) if row else None

    async def list_sparks(self, owner: str) -> list[SparkRecord]:
        rows = await self._run("SELECT * FROM sparks WHERE owner = ? ORDER BY species_id", (owner,), "all")
        return [self._spark(r) for r in rows]

    async def put_spark(self, record: SparkRecord) -> None:
        await self._run(
            "INSERT INTO sparks (owner, species_id, copies, level, xp, faint_until) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (owner, species_id) DO UPDATE SET copies = excluded.copies, level = excluded.level, "
            "xp = excluded.xp, faint_until = excluded.faint_until",
            (record.owner, record.species_id, record.copies, record.level, record.xp, record.faint_until),
        )

    @staticmethod
    def _personality(row: sqlite3.Row) -> PersonalityRecord:
        return PersonalityRecord(row["id"], row["owner"], row["species_id"], row["type_id"], row["tier"],
                                 row["created_at"], row["seq"])

    async def add_personality(self, record: PersonalityRecord) -> None:
        await self._run(
            "INSERT INTO personalities (id, owner, species_id, type_id, tier, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (record.id, record.owner, record.species_id, record.type_id, record.tier, record.created_at),
        )

    async def list_personalities(self, owner: str, species_id: str, limit: int, after_seq: int) -> list[PersonalityRecord]:
        rows = await self._run(
            "SELECT * FROM personalities WHERE owner = ? AND species_id = ? AND seq > ? ORDER BY seq LIMIT ?",
            (owner, species_id, after_seq, limit), "all",
        )
        return [self._personality(r) for r in rows]

    async def get_personalities(self, owner: str, species_id: str, ids: list[str]) -> list[PersonalityRecord]:
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        rows = await self._run(
            f"SELECT * FROM personalities WHERE owner = ? AND species_id = ? AND id IN ({marks})",
            (owner, species_id, *ids), "all",
        )
        return [self._personality(r) for r in rows]

    async def get_preset(self, owner: str, species_id: str, slot: int) -> PresetRecord | None:
        row = await self._run(
            "SELECT * FROM presets WHERE owner = ? AND species_id = ? AND slot = ?", (owner, species_id, slot), "one")
        return PresetRecord(owner, species_id, slot, tuple(json.loads(row["instance_ids"]))) if row else None

    async def list_presets(self, owner: str, species_id: str) -> list[PresetRecord]:
        rows = await self._run(
            "SELECT * FROM presets WHERE owner = ? AND species_id = ? ORDER BY slot", (owner, species_id), "all")
        return [PresetRecord(owner, species_id, r["slot"], tuple(json.loads(r["instance_ids"]))) for r in rows]

    async def put_preset(self, record: PresetRecord) -> None:
        await self._run(
            "INSERT INTO presets (owner, species_id, slot, instance_ids) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (owner, species_id, slot) DO UPDATE SET instance_ids = excluded.instance_ids",
            (record.owner, record.species_id, record.slot, _dumps(list(record.instance_ids))),
        )

    # -- encounters ----------------------------------------------------------------

    @staticmethod
    def _encounter(row: sqlite3.Row) -> EncounterRecord:
        return EncounterRecord(row["id"], row["owner"], row["species_id"], row["tier_id"], row["level"], row["status"],
                               _instances(row["wild_personalities"]), row["created_at"])

    async def add_encounter(self, record: EncounterRecord) -> None:
        await self._run(
            "INSERT INTO encounters (id, owner, species_id, tier_id, level, status, wild_personalities, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (record.id, record.owner, record.species_id, record.tier_id, record.level, record.status,
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


class SqliteSparkRepository:
    def __init__(self, path: Path | str) -> None:
        self._path = str(path)
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

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
            SqliteSparkRepository._rollback(conn)
            raise

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[SparkTransaction]:
        async with self._lock:
            if self._conn is None:
                self._conn = await _in_thread(self._open)
            conn = self._conn
            await _in_thread(conn.execute, "BEGIN IMMEDIATE")
            try:
                yield _SqliteTransaction(conn)
            except BaseException:
                await _in_thread(self._rollback, conn)
                raise
            else:
                # Commit or roll back as one step the lock outlives, even if the caller is cancelled.
                await _in_thread(self._commit, conn)

    async def close(self) -> None:
        async with self._lock:
            if self._conn is not None:
                await _in_thread(self._conn.close)
                self._conn = None
