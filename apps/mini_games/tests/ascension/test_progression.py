import asyncio
from dataclasses import replace

import pytest

from src.ascension.engine import BattleEngine
from src.ascension.models import PLAYER, WILD, BattleSetup, PersonalityInstance
from src.ascension.progression import ProgressionService
from src.ascension.records import AscendedRecord
from src.ascension.repository import SqliteAscendedRepository
from tests.ascension.helpers import FixedClock, ScriptedRandom, battle_record
from tests.ascension.env import CATALOG

engine = BattleEngine(CATALOG)
clock = FixedClock(1000.0)
progression = ProgressionService(CATALOG, clock, faint_seconds=300)


def run(coro):
    return asyncio.run(coro)


# -- pure rules ----------------------------------------------------------------------

@pytest.mark.parametrize("level,xp,gained,expected", [
    (1, 0, 99, (1, 99)),
    (1, 0, 100, (2, 0)),
    (1, 50, 400, (3, 150)),  # 450 - 100 -> level 2; 350 - 200 -> level 3 with 150 left
    (29, 2899, 1, (30, 0)),  # reaching the cap drops the remainder
    (30, 0, 5000, (30, 0)),  # no XP at the cap
])
def test_xp_carries_through_level_ups_and_stops_at_the_cap(level, xp, gained, expected):
    assert progression.add_xp("guardian", level, xp, gained) == expected


def test_forbidden_levels_to_fifty():
    assert progression.add_xp("forbidden", 49, 0, 4900) == (50, 0)
    assert progression.add_xp("forbidden", 30, 0, 100) == (30, 100)


@pytest.mark.parametrize("level,tier,xp,insignia", [(10, "common", 200, 100), (10, "unique", 300, 150), (1, "rare", 25, 12), (30, "forbidden", 2400, 1200)])
def test_reward_formulas(level, tier, xp, insignia):
    assert progression.rewards_for(level, tier) == (xp, insignia)


def test_forbidden_copies_cap_at_one_hundred():
    assert progression.add_copies("forbidden", 99, 1) == 100 and progression.add_copies("forbidden", 100, 1) == 100
    assert progression.add_copies("guardian", 500, 5) == 505


# -- applying a terminal result ------------------------------------------------------

def build_battle(player_ascended="guardian", wild_ascended="scout", wild_tier="common", wild_level=10, wild_instances=None):
    setup = BattleSetup(
        engine.build_fighter(PLAYER, player_ascended, "common", 5),
        engine.build_fighter(WILD, wild_ascended, wild_tier, wild_level),
    )
    record = battle_record()
    instances = wild_instances or (PersonalityInstance("w1", "COWARD", 2), PersonalityInstance("w2", "BOLD", 3), PersonalityInstance("w3", "AGGRESSIVE", 1))
    return replace(record, setup=setup, wild_personalities=instances)


async def apply(terminal, battle, ascended, *draws, others=()):
    repo = SqliteAscendedRepository(":memory:")
    async with repo.transaction() as tx:
        await tx.create_player("ann", 1.0)
        await tx.put_ascended(ascended)
        for other in others:
            await tx.put_ascended(other)
        result = await progression.apply_terminal(tx, battle, terminal, ScriptedRandom(*draws))
        after = {s.ascended_id: s for s in await tx.list_ascendeds("ann")}
        player = await tx.get_player("ann")
        personalities = {s: await tx.list_personalities("ann", s, 50, 0) for s in after}
    await repo.close()
    return result, after, player, personalities


FIGHTER = AscendedRecord("ann", "guardian", 7, 5, 30)


def test_a_win_pays_xp_and_insignia_to_the_fighter_only():
    result, ascendeds, player, _ = run(apply("won", build_battle(), FIGHTER))
    assert (result["xp"], result["insignia"]) == (200, 100)
    assert (ascendeds["guardian"].level, ascendeds["guardian"].xp) == (5, 230)  # 30 + 200, below the 500 needed at level 5
    assert player.insignia == 100 and ascendeds["guardian"].copies == 7 and ascendeds["guardian"].faint_until is None
    assert set(ascendeds) == {"guardian"}


def test_a_win_levels_up_with_carry():
    ascended = replace(FIGHTER, level=1, xp=0)
    result, ascendeds, _, _ = run(apply("won", build_battle(wild_level=10), ascended))  # 200 XP -> level 2 (100) -> level 3 needs 200
    assert (ascendeds["guardian"].level, ascendeds["guardian"].xp) == (2, 100)
    assert result["level_before"] == 1 and result["level_after"] == 2


def test_capturing_an_unowned_ascended_starts_it_at_level_one_with_the_tiers_copies():
    battle = build_battle(wild_ascended="channeler", wild_tier="rare")
    result, ascendeds, player, personalities = run(apply("captured", battle, FIGHTER, 0.5))
    new = ascendeds["channeler"]
    assert (new.level, new.xp, new.copies) == (1, 0, 2)  # Rare grants 2 copies
    assert result["copies_granted"] == 2 and result["tier_id"] == "common"
    assert player.insignia == 125  # Rare level 10: 10 * 10 * 1.25
    assert [p.type_id for p in personalities["channeler"]] == ["BOLD"]  # draw 0.5 of 3 -> index 1
    assert result["awarded_personality"]["type"] == "BOLD"
    assert [p["type"] for p in result["revealed_personalities"]] == ["COWARD", "BOLD", "AGGRESSIVE"]
    assert (ascendeds["guardian"].level, ascendeds["guardian"].xp) == (5, 280)  # 20 * 10 * 1.25 = 250 XP


def test_capture_adds_copies_to_an_owned_ascended_and_tier_follows_the_count():
    owned = AscendedRecord("ann", "scout", 8, 12, 40)
    battle = build_battle(wild_ascended="scout", wild_tier="rare")
    result, ascendeds, _, _ = run(apply("captured", battle, FIGHTER, 0.0, others=(owned,)))
    assert (ascendeds["scout"].copies, ascendeds["scout"].level) == (10, 12) and result["tier_id"] == "rare"


@pytest.mark.parametrize("draw,index", [(0.0, 0), (0.33, 0), (0.34, 1), (0.99, 2)])
def test_every_source_personality_is_equally_likely_to_be_awarded(draw, index):
    battle = build_battle(wild_ascended="channeler")
    result, _, _, _ = run(apply("captured", battle, FIGHTER, draw))
    assert result["awarded_personality"]["type"] == ["COWARD", "BOLD", "AGGRESSIVE"][index]


def test_identical_personalities_stay_distinct_instances():
    same = (PersonalityInstance("a", "BOLD", 2), PersonalityInstance("b", "BOLD", 2))
    owned = AscendedRecord("ann", "channeler", 1, 3, 0)
    battle = build_battle(wild_ascended="channeler", wild_instances=same)

    async def twice():
        repo = SqliteAscendedRepository(":memory:")
        async with repo.transaction() as tx:
            await tx.create_player("ann", 1.0)
            await tx.put_ascended(FIGHTER)
            await tx.put_ascended(owned)
            await progression.apply_terminal(tx, battle, "captured", ScriptedRandom(0.0))
            await progression.apply_terminal(tx, battle, "captured", ScriptedRandom(0.0))
            found = await tx.list_personalities("ann", "channeler", 50, 0)
        await repo.close()
        return found

    found = run(twice())
    assert len(found) == 2 and found[0].id != found[1].id


def test_a_capped_forbidden_capture_still_pays_xp_insignia_and_a_personality():
    capped = AscendedRecord("ann", "forbidden", 100, 40, 0)
    battle = build_battle(wild_ascended="forbidden", wild_tier="forbidden", wild_level=20)
    result, ascendeds, player, personalities = run(apply("captured", battle, FIGHTER, 0.0, others=(capped,)))
    assert ascendeds["forbidden"].copies == 100 and result["copies_granted"] == 0
    assert player.insignia == 800 and len(personalities["forbidden"]) == 1


def test_a_first_forbidden_capture_grants_one_copy():
    battle = build_battle(wild_ascended="forbidden", wild_tier="forbidden", wild_level=3)
    result, ascendeds, _, _ = run(apply("captured", battle, FIGHTER, 0.0))
    assert (ascendeds["forbidden"].copies, ascendeds["forbidden"].level, result["tier_id"]) == (1, 1, "forbidden")


@pytest.mark.parametrize("terminal", ["knocked_out", "forfeited"])
def test_losing_faints_the_fighter_for_five_minutes_without_losing_copies(terminal):
    result, ascendeds, player, _ = run(apply(terminal, build_battle(), FIGHTER))
    assert ascendeds["guardian"].faint_until == 1300.0 and result["faint_until"] == 1300.0
    assert ascendeds["guardian"].copies == 7 and player.insignia == 0 and "xp" not in result


@pytest.mark.parametrize("terminal", ["escaped", "wild_escaped"])
def test_escapes_change_nothing(terminal):
    result, ascendeds, player, _ = run(apply(terminal, build_battle(), FIGHTER))
    assert ascendeds["guardian"] == FIGHTER and player.insignia == 0 and result == {"kind": terminal}


def test_the_whole_result_is_atomic():
    async def scenario():
        repo = SqliteAscendedRepository(":memory:")
        async with repo.transaction() as tx:
            await tx.create_player("ann", 1.0)
            await tx.put_ascended(FIGHTER)
        with pytest.raises(RuntimeError):
            async with repo.transaction() as tx:
                await progression.apply_terminal(tx, build_battle(), "won", ScriptedRandom())
                raise RuntimeError("crash before commit")
        async with repo.transaction() as tx:
            ascended, player = await tx.get_ascended("ann", "guardian"), await tx.get_player("ann")
        await repo.close()
        return ascended, player

    ascended, player = run(scenario())
    assert ascended == FIGHTER and player.insignia == 0
