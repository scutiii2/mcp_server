import asyncio
import sqlite3
from dataclasses import replace

import pytest

from src.sparks.errors import ActiveBattleExists, StaleBattle
from src.sparks.models import PersonalityInstance
from src.sparks.records import EncounterRecord, PersonalityRecord, PresetRecord, SparkRecord
from src.sparks.repository import SqliteSparkRepository
from tests.sparks.helpers import battle_record


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "data" / "sparks.sqlite3"


def test_players_and_wallet(db_path):
    async def scenario():
        repo = SqliteSparkRepository(db_path)
        async with repo.transaction() as tx:
            assert await tx.get_player("ann") is None
            await tx.create_player("ann", 5.0)
            await tx.add_insignia("ann", 30)
            await tx.set_last_roll("ann", 9.0)
            player = await tx.get_player("ann")
        assert (player.insignia, player.last_roll_at, player.created_at) == (30, 9.0, 5.0)
        with pytest.raises(sqlite3.IntegrityError):
            async with repo.transaction() as tx:
                await tx.add_insignia("ann", -31)
        await repo.close()

    run(scenario())


def test_emblems_accumulate_and_cannot_go_negative(db_path):
    async def scenario():
        repo = SqliteSparkRepository(db_path)
        async with repo.transaction() as tx:
            await tx.add_emblems("ann", "common", 5)
            await tx.add_emblems("ann", "common", -2)
            await tx.add_emblems("ann", "rare", 1)
            await tx.add_emblems("ann", "rare", -1)
            counts = await tx.emblem_counts("ann")
        assert counts == {"common": 3}
        with pytest.raises(sqlite3.IntegrityError):
            async with repo.transaction() as tx:
                await tx.add_emblems("ann", "common", -4)
        await repo.close()

    run(scenario())


def test_sparks_upsert_and_list(db_path):
    async def scenario():
        repo = SqliteSparkRepository(db_path)
        async with repo.transaction() as tx:
            await tx.put_spark(SparkRecord("ann", "guardian", 0, 1, 0))
            await tx.put_spark(SparkRecord("ann", "guardian", 3, 4, 50, faint_until=99.0))
            await tx.put_spark(SparkRecord("bob", "guardian", 0, 1, 0))
            mine = await tx.list_sparks("ann")
            one = await tx.get_spark("ann", "guardian")
            missing = await tx.get_spark("ann", "scout")
        assert mine == [one] and one == SparkRecord("ann", "guardian", 3, 4, 50, 99.0) and missing is None
        await repo.close()

    run(scenario())


def test_personalities_are_scoped_and_paginated(db_path):
    async def scenario():
        repo = SqliteSparkRepository(db_path)
        async with repo.transaction() as tx:
            for i in range(5):
                await tx.add_personality(PersonalityRecord(f"p{i}", "ann", "guardian", "AGGRESSIVE", 1, float(i)))
            await tx.add_personality(PersonalityRecord("other", "ann", "scout", "COWARD", 2, 9.0))
            await tx.add_personality(PersonalityRecord("bobs", "bob", "guardian", "COWARD", 2, 9.0))
            first = await tx.list_personalities("ann", "guardian", 2, 0)
            second = await tx.list_personalities("ann", "guardian", 2, first[-1].seq)
            picked = await tx.get_personalities("ann", "guardian", ["p1", "other", "bobs", "p9"])
            nothing = await tx.get_personalities("ann", "guardian", [])
        assert [p.id for p in first] == ["p0", "p1"] and [p.id for p in second] == ["p2", "p3"]
        assert [p.id for p in picked] == ["p1"] and nothing == []
        assert first[0].instance() == PersonalityInstance("p0", "AGGRESSIVE", 1)
        await repo.close()

    run(scenario())


def test_presets_hold_five_slots(db_path):
    async def scenario():
        repo = SqliteSparkRepository(db_path)
        async with repo.transaction() as tx:
            await tx.put_preset(PresetRecord("ann", "guardian", 1, ("a", "b")))
            await tx.put_preset(PresetRecord("ann", "guardian", 1, ("c",)))
            await tx.put_preset(PresetRecord("ann", "guardian", 2, ()))
            one = await tx.get_preset("ann", "guardian", 1)
            every = await tx.list_presets("ann", "guardian")
            nothing = await tx.get_preset("ann", "guardian", 3)
        assert one.instance_ids == ("c",) and [p.slot for p in every] == [1, 2] and nothing is None
        with pytest.raises(sqlite3.IntegrityError):
            async with repo.transaction() as tx:
                await tx.put_preset(PresetRecord("ann", "guardian", 6, ()))
        await repo.close()

    run(scenario())


def test_encounters_are_owner_safe_and_one_pending_at_a_time_is_read(db_path):
    async def scenario():
        repo = SqliteSparkRepository(db_path)
        wild = (PersonalityInstance("w1", "COWARD", 2),)
        async with repo.transaction() as tx:
            await tx.add_encounter(EncounterRecord("e1", "ann", "scout", "rare", 7, "pending", wild, 1.0))
            await tx.add_encounter(EncounterRecord("e2", "ann", "scout", "common", 3, "pending", wild, 2.0))
            newest = await tx.pending_encounter("ann")
            await tx.set_encounter_status("e2", "declined")
            after = await tx.pending_encounter("ann")
            mine = await tx.get_encounter("ann", "e1")
            foreign = await tx.get_encounter("bob", "e1")
        assert newest.id == "e2" and after.id == "e1" and mine.wild_personalities == wild and foreign is None
        await repo.close()

    run(scenario())


def test_battles_round_trip_and_enforce_one_active_per_owner(db_path):
    async def scenario():
        repo = SqliteSparkRepository(db_path)
        record = replace(battle_record(), pending={"wild_action": {"kind": "flee"}}, emblem_limit="rare")
        async with repo.transaction() as tx:
            await tx.add_battle(record)
            loaded = await tx.get_battle("ann", "b1")
            active = await tx.active_battle("ann")
            foreign = await tx.get_battle("bob", "b1")
        assert loaded == record and active == record and foreign is None
        with pytest.raises(ActiveBattleExists):
            async with repo.transaction() as tx:
                await tx.add_battle(battle_record(battle_id="b2", encounter_id="e2"))
        async with repo.transaction() as tx:
            await tx.save_battle(replace(record, status="terminal", phase="terminal", revision=2, result={"kind": "won"}), 1)
            await tx.add_battle(battle_record(battle_id="b3", encounter_id="e3"))  # the finished one no longer blocks
            assert (await tx.get_battle("ann", "b1")).result == {"kind": "won"}
            assert (await tx.active_battle("ann")).id == "b3"
        await repo.close()

    run(scenario())


def test_saving_with_a_stale_revision_is_rejected(db_path):
    async def scenario():
        repo = SqliteSparkRepository(db_path)
        record = battle_record()
        async with repo.transaction() as tx:
            await tx.add_battle(record)
            await tx.save_battle(replace(record, revision=2), 1)
        with pytest.raises(StaleBattle):
            async with repo.transaction() as tx:
                await tx.save_battle(replace(record, revision=2, rng_counter=9), 1)
        await repo.close()

    run(scenario())


def test_rounds_are_stored_and_replaced(db_path):
    async def scenario():
        repo = SqliteSparkRepository(db_path)
        async with repo.transaction() as tx:
            await tx.add_round("b1", 1, {"mood": 0})
            await tx.add_round("b1", 1, {"mood": 1})
            rows = await tx._run("SELECT record FROM rounds WHERE battle_id = 'b1'", (), "all")
        assert [r["record"] for r in rows] == ['{"mood":1}']
        await repo.close()

    run(scenario())


def test_idempotency_records_are_unique_per_owner_and_key(db_path):
    async def scenario():
        repo = SqliteSparkRepository(db_path)
        async with repo.transaction() as tx:
            await tx.put_idempotent("ann", "k1", "hash", {"ok": True}, 1.0)
            await tx.put_idempotent("bob", "k1", "other", {"ok": False}, 1.0)
            ann = await tx.get_idempotent("ann", "k1")
            missing = await tx.get_idempotent("ann", "k2")
        assert (ann.request_hash, ann.response) == ("hash", {"ok": True}) and missing is None
        with pytest.raises(sqlite3.IntegrityError):
            async with repo.transaction() as tx:
                await tx.put_idempotent("ann", "k1", "hash", {}, 2.0)
        await repo.close()

    run(scenario())


def test_a_failed_transaction_rolls_back_everything(db_path):
    async def scenario():
        repo = SqliteSparkRepository(db_path)
        with pytest.raises(RuntimeError):
            async with repo.transaction() as tx:
                await tx.create_player("ann", 1.0)
                await tx.add_emblems("ann", "common", 5)
                raise RuntimeError("boom")
        async with repo.transaction() as tx:
            assert await tx.get_player("ann") is None and await tx.emblem_counts("ann") == {}
        await repo.close()

    run(scenario())


def test_data_survives_a_restart(db_path):
    async def first():
        repo = SqliteSparkRepository(db_path)
        async with repo.transaction() as tx:
            await tx.create_player("ann", 1.0)
            await tx.add_battle(battle_record())
        await repo.close()

    async def second():
        repo = SqliteSparkRepository(db_path)
        async with repo.transaction() as tx:
            return await tx.get_player("ann"), await tx.active_battle("ann")

    run(first())
    player, battle = run(second())
    assert player.owner == "ann" and battle.id == "b1"


def test_transactions_run_one_at_a_time(db_path):
    async def scenario():
        repo = SqliteSparkRepository(db_path)
        async with repo.transaction() as tx:
            await tx.create_player("ann", 1.0)

        async def bump():
            async with repo.transaction() as tx:
                before = (await tx.get_player("ann")).insignia
                await asyncio.sleep(0.01)
                await tx.add_insignia("ann", 1)
                return before

        seen = await asyncio.gather(*(bump() for _ in range(5)))
        async with repo.transaction() as tx:
            total = (await tx.get_player("ann")).insignia
        await repo.close()
        return sorted(seen), total

    seen, total = run(scenario())
    assert seen == [0, 1, 2, 3, 4] and total == 5


def test_unsupported_schema_version_is_refused(db_path):
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA user_version = 99")
    conn.commit()
    conn.close()

    async def scenario():
        repo = SqliteSparkRepository(db_path)
        async with repo.transaction():
            pass

    with pytest.raises(RuntimeError, match="schema version 99"):
        run(scenario())
