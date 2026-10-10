import pytest

from src.ascension.errors import AlreadyInitialized, IdempotencyConflict, InvalidRequest, NotFound
from tests.ascension.env import Env, run
from tests.ascension.helpers import ScriptedRandom


def make(tmp_path, *draws):
    return Env(tmp_path / "s.sqlite3", ScriptedRandom(*draws) if draws else None)


def test_initialize_creates_the_starter_setup(tmp_path):
    async def scenario():
        env = make(tmp_path, 0.0)  # first personality type: AGGRESSIVE
        profile = await env.start_player("ann", "scout")
        presets = await env.collection.get_preset("ann", "scout", 1)
        pool = await env.collection.personalities("ann", "scout", None, 0)
        await env.close()
        return profile, presets, pool

    profile, preset, pool = run(scenario())
    assert profile["insignia"] == 0 and profile["emblems"] == {"common": 5}
    [ascended] = profile["ascendeds"]
    assert (ascended["ascended_id"], ascended["level"], ascended["copies"], ascended["tier_id"]) == ("scout", 1, 0, "common")
    assert pool["items"][0]["type"] == "AGGRESSIVE" and pool["items"][0]["tier"] == 1
    assert preset["instance_ids"] == [pool["items"][0]["id"]]


@pytest.mark.parametrize("draw,expected", [(0.0, "AGGRESSIVE"), (0.99, "DISCIPLINED")])
def test_the_starter_personality_is_uniform_over_the_eight_types(tmp_path, draw, expected):
    async def scenario():
        env = make(tmp_path, draw)
        await env.start_player()
        pool = await env.collection.personalities("ann", "guardian", None, 0)
        await env.close()
        return pool

    assert run(scenario())["items"][0]["type"] == expected


def test_only_the_three_starters_can_be_chosen(tmp_path):
    async def scenario():
        env = make(tmp_path)
        with pytest.raises(InvalidRequest, match="guardian, scout, striker"):
            await env.collection.initialize("ann", "k", "sentinel")
        await env.close()

    run(scenario())


def test_initialization_happens_once_and_retries_return_the_same_result(tmp_path):
    async def scenario():
        env = make(tmp_path)
        first = await env.collection.initialize("ann", "k1", "guardian")
        again = await env.collection.initialize("ann", "k1", "guardian")
        with pytest.raises(AlreadyInitialized):
            await env.collection.initialize("ann", "k2", "striker")
        with pytest.raises(IdempotencyConflict):
            await env.collection.initialize("ann", "k1", "striker")
        await env.close()
        return first, again

    first, again = run(scenario())
    assert first == again


def test_profiles_are_isolated_between_owners(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player("ann")
        with pytest.raises(NotFound):
            await env.collection.profile("bob")
        with pytest.raises(NotFound):
            await env.collection.get_preset("bob", "guardian", 1)
        await env.close()

    run(scenario())


def test_profile_reports_xp_needed_faint_and_timers(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        from src.ascension.records import AscendedRecord

        await env.give(guardian=AscendedRecord("ann", "guardian", 12, 30, 0, faint_until=env.clock.now() + 60))
        profile = await env.collection.profile("ann")
        await env.close()
        return profile["ascendeds"][0]

    ascended = run(scenario())
    assert ascended["fainted"] is True and ascended["xp_needed"] is None and ascended["tier_id"] == "rare"


def test_presets_hold_up_to_three_distinct_collected_instances(tmp_path):
    async def scenario():
        env = make(tmp_path, 0.0)
        await env.start_player()
        from src.ascension.records import PersonalityRecord

        async with env.repo.transaction() as tx:
            for name in ("b", "c", "d"):
                await tx.add_personality(PersonalityRecord(name, "ann", "guardian", "COWARD", 2, 1.0))
            await tx.add_personality(PersonalityRecord("other", "ann", "scout", "COWARD", 2, 1.0))
        ok = await env.collection.put_preset("ann", "k1", "guardian", 2, ["b", "c", "d"])
        again = await env.collection.put_preset("ann", "k2", "guardian", 3, ["b"])  # the same instance in two presets
        for bad in (["b", "b"], ["b", "c", "d", "x"], ["nope"], ["other"]):
            with pytest.raises(InvalidRequest):
                await env.collection.put_preset("ann", env.key(), "guardian", 4, bad)
        for slot in (0, 6):
            with pytest.raises(InvalidRequest):
                await env.collection.put_preset("ann", env.key(), "guardian", slot, [])
        stored = await env.collection.get_preset("ann", "guardian", 2)
        empty = await env.collection.get_preset("ann", "guardian", 5)
        await env.close()
        return ok, again, stored, empty

    ok, again, stored, empty = run(scenario())
    assert ok["instance_ids"] == ["b", "c", "d"] == stored["instance_ids"] and again["instance_ids"] == ["b"] and empty["instance_ids"] == []


def test_a_preset_cannot_use_someone_elses_instances_or_an_unowned_ascended(tmp_path):
    async def scenario():
        env = make(tmp_path, 0.0, 0.0)
        await env.start_player("ann")
        await env.start_player("bob")
        bobs = (await env.collection.personalities("bob", "guardian", None, 0))["items"][0]["id"]
        with pytest.raises(InvalidRequest):
            await env.collection.put_preset("ann", "k", "guardian", 2, [bobs])
        with pytest.raises(NotFound):
            await env.collection.put_preset("ann", "k2", "scout", 2, [])
        await env.close()

    run(scenario())


def test_personality_pages_default_to_fifty_and_cap_at_one_hundred(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        from src.ascension.records import PersonalityRecord

        async with env.repo.transaction() as tx:
            for i in range(120):
                await tx.add_personality(PersonalityRecord(f"p{i:03}", "ann", "guardian", "BOLD", 1, 1.0))
        first = await env.collection.personalities("ann", "guardian", None, 0)
        cursor, seen = first["next_cursor"], len(first["items"])
        while cursor:
            page = await env.collection.personalities("ann", "guardian", 100, cursor)
            seen += len(page["items"])
            cursor = page["next_cursor"]
        for bad in (0, 101):
            with pytest.raises(InvalidRequest):
                await env.collection.personalities("ann", "guardian", bad, 0)
        await env.close()
        return len(first["items"]), seen

    first, seen = run(scenario())
    assert first == 50 and seen == 121  # 120 added plus the starter's own
