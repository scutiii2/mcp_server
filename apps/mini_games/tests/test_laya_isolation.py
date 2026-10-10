import asyncio
import sys
import time
import types

import pytest

from src.laya_client import LayaClient, LayaError, LayaUnavailable, noul_question
from src.ascension.repository import SqliteAscendedRepository
from tests.fake_laya import FakeEngine

Q = {"yes": noul_question("Is it so?", "No.", "Yes.")}


def test_second_ask_while_the_first_is_stuck_fails_fast_without_a_new_thread():
    async def scenario():
        client = LayaClient(FakeEngine(delay=0.6), timeout=0.1)
        with pytest.raises(LayaError, match="timed out"):
            await client.ask("Text.", Q)
        before = len(client._executor._threads)
        started = time.monotonic()
        with pytest.raises(LayaError, match="busy"):
            await client.ask("Text.", Q)
        assert time.monotonic() - started < 0.05
        assert len(client._executor._threads) == before == 1
        await asyncio.sleep(0.8)  # the stuck call ends; the client recovers
        client._engine.delay = 0.0
        assert (await client.ask("Text.", Q))["yes"].kind == "noul"
        client.close()

    asyncio.run(scenario())


def test_a_failed_load_is_attempted_once(monkeypatch):
    attempts = []

    def load(name):
        attempts.append(name)
        raise OSError("no weights")

    monkeypatch.setitem(sys.modules, "laya", types.SimpleNamespace(load=load))
    client = LayaClient()
    with pytest.raises(LayaError):
        client.prepare()
    for _ in range(2):
        with pytest.raises(LayaUnavailable):
            asyncio.run(client.ask("Text.", Q))
    with pytest.raises(LayaUnavailable):
        client.prepare()
    assert len(attempts) == 1
    client.close()


def test_the_repository_works_while_laya_is_stuck(tmp_path):
    async def scenario():
        client = LayaClient(FakeEngine(delay=0.8), timeout=0.1)
        repo = SqliteAscendedRepository(tmp_path / "s.sqlite3")
        with pytest.raises(LayaError):
            await client.ask("Text.", Q)
        async with asyncio.timeout(0.5):
            async with repo.transaction() as tx:
                await tx.create_player("ann", 1.0)
        await repo.close()
        client.close()

    asyncio.run(scenario())


def test_repository_close_shuts_its_worker_down(tmp_path):
    async def scenario():
        repo = SqliteAscendedRepository(tmp_path / "s.sqlite3")
        async with repo.transaction():
            pass
        pool = repo._executor
        assert len(pool._threads) == 1
        await repo.close()
        assert repo._executor is None and not any(t.is_alive() for t in pool._threads)

    asyncio.run(scenario())
