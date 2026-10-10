import pytest

import src.sparks.coordinator as coordinator_module
from src.sparks.errors import InvalidRequest, NotFound
from tests.sparks.env import Env, run
from tests.sparks.test_coordinator import begin, encounter


@pytest.fixture(autouse=True)
def fixed_seed(monkeypatch):
    monkeypatch.setattr(coordinator_module, "new_seed", lambda: 7)


@pytest.mark.parametrize("slot", [0, 6, -1, 2**63])
def test_start_rejects_an_out_of_range_preset_slot(tmp_path, slot):
    async def scenario():
        env = Env(tmp_path / "s.sqlite3")
        coord = env.coordinator()
        await env.start_player()
        eid = await encounter(env)
        with pytest.raises(InvalidRequest, match="preset slot"):
            await coord.start("ann", env.key(), encounter_id=eid, species_id="guardian", preset_slot=slot,
                              mode="manual", emblem_limit=None)
        await env.close()

    run(scenario())


def test_lock_table_does_not_grow_for_unknown_battle_ids(tmp_path):
    async def scenario():
        env = Env(tmp_path / "s.sqlite3")
        coord = env.coordinator()
        await env.start_player()
        for i in range(5):
            bid = f"nope-{i}"
            with pytest.raises(NotFound):
                await coord.advance("ann", env.key(), bid, round=1, revision=1)
            with pytest.raises(NotFound):
                await coord.submit_action("ann", env.key(), bid, round=1, revision=1, action={"kind": "attack"})
            with pytest.raises(NotFound):
                await coord.forfeit("ann", env.key(), bid)
            with pytest.raises(NotFound):
                await coord.set_mode("ann", env.key(), bid, round=1, revision=1, mode="manual", emblem_limit=None)
            with pytest.raises(NotFound):
                await coord.answer_emblem("ann", env.key(), bid, round=1, revision=1, tier="normal")
        assert coord._locks == {}
        await env.close()

    run(scenario())


def test_a_foreign_or_finished_battle_leaves_no_lock_entry(tmp_path):
    async def scenario():
        env = Env(tmp_path / "s.sqlite3")
        coord = env.coordinator()
        await env.start_player()
        view = await begin(env, coord)
        with pytest.raises(NotFound):
            await coord.forfeit("mallory", env.key(), view["id"])
        await coord.forfeit("ann", env.key(), view["id"])
        assert coord._locks == {}
        from src.sparks.errors import BattleFinished
        with pytest.raises(BattleFinished):
            await coord.forfeit("ann", env.key(), view["id"])
        assert coord._locks == {}
        await env.close()

    run(scenario())


def test_a_probe_queued_behind_a_busy_battle_leaves_nothing_behind(tmp_path):
    import asyncio

    async def scenario():
        env = Env(tmp_path / "s.sqlite3")
        coord = env.coordinator()
        await env.start_player()
        view = await begin(env, coord)
        holder_in, release = asyncio.Event(), asyncio.Event()

        async def holder():
            async with coord._serialized(view["id"]):
                holder_in.set()
                await release.wait()

        task = asyncio.create_task(holder())
        await holder_in.wait()
        lock = coord._locks[view["id"]]
        probe = asyncio.create_task(coord.forfeit("mallory", env.key(), view["id"]))  # queues behind the holder
        await asyncio.sleep(0.05)
        assert coord._users[view["id"]] == 2 and coord._locks[view["id"]] is lock
        release.set()
        with pytest.raises(NotFound):
            await probe
        await task
        assert coord._locks == {} and coord._users == {}  # all users gone: nothing left behind
        await env.close()

    asyncio.run(scenario())
