import asyncio
import sqlite3
import time
from dataclasses import replace

import pytest

from src.sparks.errors import ActiveBattleExists, BattleAlreadyExists
from src.sparks.records import EncounterRecord
from src.sparks.repository import SqliteSparkRepository
from tests.sparks.helpers import battle_record


def run(coro):
    return asyncio.run(coro)


class ConnProxy:
    """Wraps the real connection so tests can fail or slow chosen statements."""

    def __init__(self, conn, fail_on=None, delay_on=None, events=None):
        self._conn, self.fail_on, self.delay_on, self.events = conn, fail_on, delay_on, events if events is not None else []

    def execute(self, sql, *args):
        self.events.append(("start", sql))
        if self.delay_on == sql:
            time.sleep(0.3)
        try:
            if self.fail_on == sql:
                raise sqlite3.OperationalError(f"injected failure on {sql}")
            return self._conn.execute(sql, *args)
        finally:
            self.events.append(("end", sql))

    def __getattr__(self, name):
        return getattr(self._conn, name)


async def _repo_with_proxy(tmp_path, **kwargs):
    repo = SqliteSparkRepository(tmp_path / "s.sqlite3")
    async with repo.transaction():
        pass
    repo._conn = ConnProxy(repo._conn, **kwargs)
    return repo


def test_failing_commit_rolls_back_and_next_transaction_works(tmp_path):
    async def scenario():
        repo = await _repo_with_proxy(tmp_path, fail_on="COMMIT")
        with pytest.raises(sqlite3.OperationalError, match="injected"):
            async with repo.transaction() as tx:
                await tx.create_player("ann", 1.0)
        assert not repo._conn.in_transaction
        repo._conn.fail_on = None
        async with repo.transaction() as tx:
            assert await tx.get_player("ann") is None  # the failed commit was rolled back
            await tx.create_player("ann", 2.0)
        await repo.close()

    run(scenario())


def test_failing_rollback_does_not_mask_the_original_error(tmp_path):
    async def scenario():
        repo = await _repo_with_proxy(tmp_path, fail_on="ROLLBACK")
        with pytest.raises(ValueError, match="boom"):
            async with repo.transaction():
                raise ValueError("boom")
        await repo.close()

    run(scenario())


def test_cancel_during_commit_keeps_the_lock_until_the_worker_is_done(tmp_path):
    async def scenario():
        repo = await _repo_with_proxy(tmp_path, delay_on="COMMIT")

        async def writer():
            async with repo.transaction() as tx:
                await tx.create_player("ann", 1.0)

        task = asyncio.create_task(writer())
        await asyncio.sleep(0.1)  # now inside the slow COMMIT worker
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        async with asyncio.timeout(5):
            async with repo.transaction() as tx:
                await tx.get_player("ann")
        events = repo._conn.events
        commit_end = events.index(("end", "COMMIT"))
        later_begin = max(i for i, e in enumerate(events) if e == ("start", "BEGIN IMMEDIATE"))
        assert later_begin > commit_end
        await repo.close()

    run(scenario())


def test_cancel_inside_the_body_does_not_wedge_the_repository(tmp_path):
    async def scenario():
        repo = SqliteSparkRepository(tmp_path / "s.sqlite3")

        async def hang():
            async with repo.transaction() as tx:
                await tx.create_player("ann", 1.0)
                await asyncio.sleep(30)

        task = asyncio.create_task(hang())
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        async with asyncio.timeout(5):
            async with repo.transaction() as tx:
                assert await tx.get_player("ann") is None
        await repo.close()

    run(scenario())


def test_battle_errors_are_distinguished(tmp_path):
    async def scenario():
        repo = SqliteSparkRepository(tmp_path / "s.sqlite3")
        async with repo.transaction() as tx:
            await tx.add_battle(battle_record("ann", "b1", "e1"))
        with pytest.raises(ActiveBattleExists):
            async with repo.transaction() as tx:
                await tx.add_battle(battle_record("ann", "b2", "e2"))
        with pytest.raises(BattleAlreadyExists):  # other owner, so only the id collides
            async with repo.transaction() as tx:
                await tx.add_battle(battle_record("bob", "b1", "e3"))
        with pytest.raises(BattleAlreadyExists):  # other owner, reused encounter id
            async with repo.transaction() as tx:
                await tx.add_battle(battle_record("bob", "b9", "e1"))
        await repo.close()

    run(scenario())


def test_bad_phase_is_rejected_by_the_schema(tmp_path):
    async def scenario():
        repo = SqliteSparkRepository(tmp_path / "s.sqlite3")
        with pytest.raises(sqlite3.IntegrityError):
            async with repo.transaction() as tx:
                await tx.add_battle(replace(battle_record(), phase="nonsense"))
        await repo.close()

    run(scenario())


def test_failed_schema_creation_closes_the_connection(tmp_path, monkeypatch):
    opened = []
    real_connect = sqlite3.connect

    class Spy:
        def __init__(self, conn):
            self.conn, self.closed = conn, False

        def execute(self, sql, *args):
            if sql.startswith("PRAGMA user_version") and "=" not in sql:
                raise sqlite3.OperationalError("disk I/O error")
            return self.conn.execute(sql, *args)

        def close(self):
            self.closed = True
            self.conn.close()

        def __setattr__(self, name, value):
            if name in ("conn", "closed"):
                object.__setattr__(self, name, value)
            else:
                setattr(self.conn, name, value)

    def connect(*args, **kwargs):
        spy = Spy(real_connect(*args, **kwargs))
        opened.append(spy)
        return spy

    monkeypatch.setattr(sqlite3, "connect", connect)
    repo = SqliteSparkRepository(tmp_path / "s.sqlite3")
    with pytest.raises(sqlite3.OperationalError):
        repo._open()
    assert opened and opened[0].closed


def test_pending_encounter_ties_break_on_insertion_order(tmp_path):
    async def scenario():
        repo = SqliteSparkRepository(tmp_path / "s.sqlite3")
        async with repo.transaction() as tx:
            for eid in ("e1", "e2", "e3"):
                await tx.add_encounter(EncounterRecord(eid, "ann", "guardian", "common", 1, "pending", (), 5.0))
            assert (await tx.pending_encounter("ann")).id == "e3"
        await repo.close()

    run(scenario())


def test_cancel_during_begin_does_not_leave_the_connection_in_a_transaction(tmp_path):
    async def scenario():
        repo = await _repo_with_proxy(tmp_path, delay_on="BEGIN IMMEDIATE")

        async def writer():
            async with repo.transaction() as tx:
                await tx.create_player("ann", 1.0)

        task = asyncio.create_task(writer())
        await asyncio.sleep(0.1)  # inside the slow BEGIN worker
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not repo._conn.in_transaction
        repo._conn.delay_on = None
        async with asyncio.timeout(5):
            async with repo.transaction() as tx:
                assert await tx.get_player("ann") is None
        await repo.close()

    run(scenario())


def test_a_stray_open_transaction_is_rolled_back_at_the_next_start(tmp_path):
    async def scenario():
        repo = await _repo_with_proxy(tmp_path)
        repo._conn.execute("BEGIN IMMEDIATE")
        async with repo.transaction() as tx:
            await tx.create_player("ann", 1.0)
        await repo.close()

    run(scenario())


def test_cancel_during_open_does_not_leak_the_connection(tmp_path, monkeypatch):
    opened = []
    real_connect = sqlite3.connect

    def slow_connect(*args, **kwargs):
        time.sleep(0.3)
        conn = real_connect(*args, **kwargs)
        opened.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", slow_connect)

    async def scenario():
        repo = SqliteSparkRepository(tmp_path / "s.sqlite3")

        async def writer():
            async with repo.transaction():
                pass

        task = asyncio.create_task(writer())
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(opened) == 1 and repo._conn is not None  # the new connection is kept, not orphaned
        async with repo.transaction():
            pass
        assert len(opened) == 1
        await repo.close()
        with pytest.raises(sqlite3.ProgrammingError):
            opened[0].execute("SELECT 1")  # closed

    run(scenario())
