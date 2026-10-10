import asyncio

import pytest

from src.ascension.errors import IdempotencyConflict, InvalidRequest
from src.ascension.idempotency import IdempotentWriter
from src.ascension.repository import SqliteAscendedRepository
from tests.ascension.helpers import FixedClock


def run(coro):
    return asyncio.run(coro)


def make(tmp_path):
    repo = SqliteAscendedRepository(tmp_path / "s.sqlite3")
    return repo, IdempotentWriter(repo, FixedClock())


def test_a_retry_returns_the_original_response_without_rerunning(tmp_path):
    async def scenario():
        repo, writer = make(tmp_path)
        calls = []

        async def work(tx):
            calls.append(1)
            await tx.create_player("ann", 1.0)
            return {"n": len(calls)}

        first = await writer.commit("ann", "k", "init", {"a": 1}, work)
        second = await writer.commit("ann", "k", "init", {"a": 1}, work)
        await repo.close()
        return first, second, calls

    first, second, calls = run(scenario())
    assert first == second == {"n": 1} and calls == [1]


def test_the_same_key_with_a_different_payload_conflicts(tmp_path):
    async def scenario():
        repo, writer = make(tmp_path)

        async def work(tx):
            return {}

        await writer.commit("ann", "k", "init", {"a": 1}, work)
        with pytest.raises(IdempotencyConflict):
            await writer.commit("ann", "k", "init", {"a": 2}, work)
        with pytest.raises(IdempotencyConflict):
            await writer.commit("ann", "k", "other-operation", {"a": 1}, work)
        await repo.close()

    run(scenario())


def test_keys_are_per_owner(tmp_path):
    async def scenario():
        repo, writer = make(tmp_path)

        async def work(tx):
            return {"who": "x"}

        await writer.commit("ann", "k", "op", {}, work)
        again = await writer.commit("bob", "k", "op", {}, work)
        await repo.close()
        return again

    assert run(scenario()) == {"who": "x"}


def test_a_failed_change_stores_nothing_so_the_retry_runs(tmp_path):
    async def scenario():
        repo, writer = make(tmp_path)

        async def failing(tx):
            await tx.create_player("ann", 1.0)
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await writer.commit("ann", "k", "op", {}, failing)

        async def fine(tx):
            await tx.create_player("ann", 2.0)
            return {"ok": True}

        result = await writer.commit("ann", "k", "op", {}, fine)
        await repo.close()
        return result

    assert run(scenario()) == {"ok": True}


def test_lookup_finds_a_stored_response_and_checks_the_payload(tmp_path):
    async def scenario():
        repo, writer = make(tmp_path)

        async def work(tx):
            return {"done": 1}

        assert await writer.lookup("ann", "k", "op", {"a": 1}) is None
        await writer.commit("ann", "k", "op", {"a": 1}, work)
        found = await writer.lookup("ann", "k", "op", {"a": 1})
        with pytest.raises(IdempotencyConflict):
            await writer.lookup("ann", "k", "op", {"a": 2})
        await repo.close()
        return found

    assert run(scenario()) == {"done": 1}


@pytest.mark.parametrize("key", ["", "x" * 201])
def test_bad_keys_are_rejected(tmp_path, key):
    async def scenario():
        repo, writer = make(tmp_path)
        with pytest.raises(InvalidRequest):
            await writer.lookup("ann", key, "op", {})
        await repo.close()

    run(scenario())
