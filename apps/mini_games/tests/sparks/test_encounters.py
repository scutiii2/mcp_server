import pytest

from src.sparks.encounters import EncounterRoller
from src.sparks.errors import ActiveBattleExists, EncounterCooldown, NotFound, WrongPhase
from src.sparks.runtime import SeededRandom
from tests.sparks.env import CATALOG, COOLDOWN, Env, run
from tests.sparks.helpers import ScriptedRandom, battle_record

roller = EncounterRoller(CATALOG)


def roll(highest, *draws):
    return roller.roll(highest, ScriptedRandom(*draws))


# -- the draws -----------------------------------------------------------------------

@pytest.mark.parametrize("u,tier", [(0.3, "normal"), (0.7, "rare"), (0.9, "legendary"), (0.97, "royalty"), (0.995, "ascended"), (0.9995, "forbidden")])
def test_tier_follows_the_encounter_probabilities(u, tier):
    assert roll(10, u, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0).tier_id == tier


def test_regular_tiers_pick_uniformly_among_the_six_regular_species():
    picked = [roll(10, 0.3, u, 0.0, 0.0, 0.0, 0.0).species_id for u in (0.0, 0.17, 0.34, 0.5, 0.67, 0.99)]
    assert picked == ["guardian", "striker", "scout", "sentinel", "bruiser", "channeler"]


def test_forbidden_tier_is_always_the_forbidden_species_and_uses_one_fewer_draw():
    assert roll(10, 0.9995, 0.0, 0.0, 0.0, 0.0).species_id == "forbidden"


@pytest.mark.parametrize("highest,species_draw,low,high", [
    (10, 0.0, 8, 12),
    (1, 0.0, 1, 3),
    (30, 0.0, 28, 30),
    (50, 0.0, 30, 30),  # a level-50 collection still meets valid regular enemies
])
def test_enemy_level_window_is_clamped_to_the_species_cap(highest, species_draw, low, high):
    levels = {roll(highest, 0.3, species_draw, u, 0.0, 0.0, 0.0).level for u in (0.0, 0.25, 0.5, 0.75, 0.999)}
    assert min(levels) == low and max(levels) == high


def test_forbidden_levels_can_exceed_the_regular_cap():
    assert roll(50, 0.9995, 0.999, 0.0, 0.0, 0.0).level == 50
    assert roll(3, 0.9995, 0.0, 0.0, 0.0, 0.0).level == 1


@pytest.mark.parametrize("count_draw,count", [(0.0, 1), (0.4, 2), (0.9, 3)])
def test_one_to_three_personalities_with_equal_odds(count_draw, count):
    draws = [0.3, 0.0, 0.0, count_draw] + [0.0, 0.0] * 3
    assert len(roll(10, *draws).personalities) == count


def test_personality_type_and_tier_come_from_the_draws():
    rolled = roll(10, 0.3, 0.0, 0.0, 0.0, 0.99, 0.95)  # one instance: last type, tier 3
    [only] = rolled.personalities
    assert (only.type_id, only.tier) == ("DISCIPLINED", 3)
    assert roll(10, 0.3, 0.0, 0.0, 0.0, 0.0, 0.59).personalities[0].tier == 1
    assert roll(10, 0.3, 0.0, 0.0, 0.0, 0.0, 0.7).personalities[0].tier == 2


def test_distribution_over_many_rolls_matches_the_tables():
    rng = SeededRandom(3)
    tiers: dict[str, int] = {}
    instance_tiers = {1: 0, 2: 0, 3: 0}
    n = 20000
    for _ in range(n):
        rolled = roller.roll(10, rng)
        tiers[rolled.tier_id] = tiers.get(rolled.tier_id, 0) + 1
        for instance in rolled.personalities:
            instance_tiers[instance.tier] += 1
    assert tiers["normal"] / n == pytest.approx(0.60, abs=0.02)
    assert tiers["rare"] / n == pytest.approx(0.25, abs=0.02)
    assert tiers["legendary"] / n == pytest.approx(0.10, abs=0.015)
    total = sum(instance_tiers.values())
    assert instance_tiers[1] / total == pytest.approx(0.6, abs=0.02) and instance_tiers[3] / total == pytest.approx(0.1, abs=0.015)


# -- the service ---------------------------------------------------------------------

def test_a_roll_creates_a_preview_without_personalities_and_starts_the_cooldown(tmp_path):
    async def scenario():
        env = Env(tmp_path / "s.sqlite3")
        await env.start_player()
        preview = await env.encounters.roll("ann", "r1")
        profile = await env.collection.profile("ann")
        again = await env.encounters.roll("ann", "r1")  # a retry, not a new roll
        fetched = await env.encounters.get("ann", preview["id"])
        await env.close()
        return preview, profile, again, fetched, env.clock.now()

    preview, profile, again, fetched, now = run(scenario())
    assert set(preview) == {"id", "species_id", "name", "tier_id", "level", "status", "created_at"}
    assert preview == again == fetched and preview["status"] == "pending"
    assert profile["pending_encounter"] == preview["id"] and profile["next_roll_at"] == now + COOLDOWN


def test_a_new_roll_waits_thirty_seconds_from_the_previous_generation(tmp_path):
    async def scenario():
        env = Env(tmp_path / "s.sqlite3")
        await env.start_player()
        first = await env.encounters.roll("ann", "r1")
        env.clock.advance(10)
        with pytest.raises(EncounterCooldown) as early:
            await env.encounters.roll("ann", "r2")
        env.clock.advance(20)
        second = await env.encounters.roll("ann", "r3")
        old = await env.encounters.get("ann", first["id"])
        await env.close()
        return early.value, second, old

    early, second, old = run(scenario())
    assert early.retry_after == pytest.approx(20) and old["status"] == "expired" and second["status"] == "pending"


def test_declining_is_free_and_final(tmp_path):
    async def scenario():
        env = Env(tmp_path / "s.sqlite3")
        await env.start_player()
        preview = await env.encounters.roll("ann", "r1")
        declined = await env.encounters.decline("ann", "d1", preview["id"])
        with pytest.raises(WrongPhase):
            await env.encounters.decline("ann", "d2", preview["id"])
        with pytest.raises(NotFound):
            await env.encounters.decline("ann", "d3", "nope")
        profile = await env.collection.profile("ann")
        await env.close()
        return declined, profile

    declined, profile = run(scenario())
    assert declined["status"] == "declined" and profile["pending_encounter"] is None and profile["insignia"] == 0


def test_encounters_are_owner_safe(tmp_path):
    async def scenario():
        env = Env(tmp_path / "s.sqlite3")
        await env.start_player("ann")
        await env.start_player("bob")
        preview = await env.encounters.roll("ann", "r1")
        with pytest.raises(NotFound):
            await env.encounters.get("bob", preview["id"])
        with pytest.raises(NotFound):
            await env.encounters.decline("bob", "d1", preview["id"])
        await env.close()

    run(scenario())


def test_rolling_needs_a_profile_and_no_active_battle(tmp_path):
    async def scenario():
        env = Env(tmp_path / "s.sqlite3")
        with pytest.raises(NotFound):
            await env.encounters.roll("ann", "r0")
        await env.start_player()
        async with env.repo.transaction() as tx:
            await tx.add_battle(battle_record())
        with pytest.raises(ActiveBattleExists):
            await env.encounters.roll("ann", "r1")
        await env.close()

    run(scenario())
