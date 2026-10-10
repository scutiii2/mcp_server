import sqlite3

import pytest

from src.sparks.errors import Conflict, NotFound
from src.sparks.models import PersonalityInstance
from src.sparks.records import EncounterRecord
from tests.sparks.env import Env, run
from tests.sparks.helpers import battle_record

OWNED = ("players", "emblems", "sparks", "personalities", "presets", "encounters", "battles", "idempotency")


def make(tmp_path):
    return Env(tmp_path / "s.sqlite3")


async def populate(env, owner, suffix):
    """A profile plus a pending encounter, a finished battle and one of its rounds."""
    await env.start_player(owner)
    wild = (PersonalityInstance("w1", "COWARD", 2),)
    async with env.repo.transaction() as tx:
        await tx.add_encounter(EncounterRecord(f"e-{suffix}", owner, "scout", "common", 3, "pending", wild, 1.0))
        await tx.add_encounter(EncounterRecord(f"e-done-{suffix}", owner, "scout", "common", 3, "consumed", wild, 1.0))
        await tx.add_battle(battle_record(owner, f"b-{suffix}", f"e-done-{suffix}", status="terminal"))
        await tx.add_round(f"b-{suffix}", 1, {"n": 1})


def counts(tmp_path, owner):
    conn = sqlite3.connect(tmp_path / "s.sqlite3")
    try:
        result = {t: conn.execute(f"SELECT COUNT(*) FROM {t} WHERE owner = ?", (owner,)).fetchone()[0] for t in OWNED}
        result["rounds"] = conn.execute(
            "SELECT COUNT(*) FROM rounds WHERE battle_id IN (SELECT id FROM battles WHERE owner = ?)", (owner,)).fetchone()[0]
        return result
    finally:
        conn.close()


def test_reset_removes_everything_the_owner_has(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await populate(env, "ann", "a")
        before = counts(tmp_path, "ann")
        response = await env.collection.reset("ann", "r1")
        fresh = await env.collection.initialize("ann", "r2", "striker")
        await env.close()
        return before, response, fresh

    before, response, fresh = run(scenario())
    assert all(before[t] > 0 for t in (*OWNED[:-1], "rounds"))
    assert response == {"reset": True}
    assert [s["spark_id"] for s in fresh["sparks"]] == ["striker"] and fresh["pending_encounter"] is None
    after = counts(tmp_path, "ann")
    assert after["encounters"] == after["battles"] == after["rounds"] == 0 and after["sparks"] == 1


def test_reset_leaves_other_owners_untouched(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await populate(env, "ann", "a")
        await populate(env, "bob", "b")
        before = counts(tmp_path, "bob")
        await env.collection.reset("ann", "r1")
        await env.close()
        return before

    before = run(scenario())
    assert counts(tmp_path, "bob") == before and all(n > 0 for n in before.values())
    assert sum(counts(tmp_path, "ann").values()) == 1  # only the reset's own idempotency row


def test_reset_without_a_profile_is_not_found(tmp_path):
    async def scenario():
        env = make(tmp_path)
        try:
            with pytest.raises(NotFound):
                await env.collection.reset("ann", "r1")
        finally:
            await env.close()

    run(scenario())


def test_reset_is_refused_during_an_active_battle_and_deletes_nothing(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await populate(env, "ann", "a")
        async with env.repo.transaction() as tx:
            await tx.add_battle(battle_record("ann", "b-live", "e-a"))
        before = counts(tmp_path, "ann")
        try:
            with pytest.raises(Conflict, match="forfeit"):
                await env.collection.reset("ann", "r1")
        finally:
            await env.close()
        return before

    before = run(scenario())
    assert counts(tmp_path, "ann") == before


def test_a_retry_with_the_same_key_returns_the_stored_response(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player("ann")
        first = await env.collection.reset("ann", "r1")
        again = await env.collection.reset("ann", "r1")
        await env.close()
        return first, again

    assert run(scenario()) == ({"reset": True}, {"reset": True})
