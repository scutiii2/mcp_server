from dataclasses import replace

import pytest

from src.sparks.engine import ActionError, BattleEngine
from src.sparks.models import PLAYER, WILD, Action, BattleSetup, BattleState, Buff, FighterState, PassiveSpec
from tests.sparks.helpers import ScriptedRandom, ability, fighter, setup
from tests.sparks.env import CATALOG

engine = BattleEngine(CATALOG)

ATTACK = Action("attack", "ATTACK")
FLEE = Action("flee", "FEAR")
CATCH_WILD = Action("catch", "INTERCEPT")


def catch(tier="common"):
    return Action("catch", "INTERCEPT", emblem_tier=tier)


def use(spec):
    return Action("ability", spec.category, spec.id, spec.percentage)


def play(s, pa, wa, *draws, state=None):
    return engine.resolve_round(s, state or engine.start_state(s), pa, wa, ScriptedRandom(*draws))


# -- setup ---------------------------------------------------------------------------

def test_build_fighter_unlocks_abilities_by_level():
    assert len(engine.build_fighter(PLAYER, "guardian", "common", 1).abilities) == 1
    assert len(engine.build_fighter(PLAYER, "guardian", "common", 10).abilities) == 2
    assert len(engine.build_fighter(PLAYER, "guardian", "common", 20).abilities) == 3


def test_build_fighter_applies_tier_to_stats():
    f = engine.build_fighter(WILD, "forbidden", "forbidden", 1)
    assert (f.max_hp, f.essence, f.speed) == (800, 160, 120)


def test_scout_starts_with_a_speed_buff_from_unbuffed_essence():
    s = BattleSetup(engine.build_fighter(PLAYER, "scout", "common", 1), engine.build_fighter(WILD, "guardian", "common", 1))
    state = engine.start_state(s)
    assert engine.stat(s.player, state.player, "speed") == 35 + 11  # 50% of 22 ESSENCE
    assert engine.stat(s.wild, state.wild, "speed") == 15 and state.round == 1


# -- legal actions -------------------------------------------------------------------

def test_legal_actions_include_basic_actions_and_abilities():
    s = setup(fighter(abilities=(ability("hit"),)))
    keys = [a.key for a in engine.legal_actions(s, engine.start_state(s), PLAYER, can_collect=True)]
    assert keys == ["attack", "ability:hit", "flee", "catch"]


def test_collector_needs_an_emblem_to_catch_but_wild_does_not():
    s = setup()
    state = engine.start_state(s)
    assert "catch" not in [a.key for a in engine.legal_actions(s, state, PLAYER, can_collect=False)]
    assert "catch" in [a.key for a in engine.legal_actions(s, state, WILD, can_collect=False)]


@pytest.mark.parametrize("cooldown,blocked,available", [(1, [2], 3), (2, [2, 3], 4)])
def test_cooldown_blocks_exactly_the_following_rounds(cooldown, blocked, available):
    spec = ability("hit", cooldown=cooldown)
    s = setup(fighter(abilities=(spec,)))
    state = play(s, use(spec), FLEE, 0.5, 0.99).state
    for rnd in blocked + [available]:
        at = replace(state, round=rnd)
        keys = [a.key for a in engine.legal_actions(s, at, PLAYER, can_collect=False)]
        assert ("ability:hit" in keys) == (rnd == available)


def test_forbidden_passive_shortens_cooldowns_to_a_minimum_of_one():
    spec = ability("ruin", cooldown=2)
    s = setup(fighter(abilities=(spec,), passive=PassiveSpec("cooldown_reduction", {"rounds": 1, "minimum": 1})))
    state = play(s, use(spec), FLEE, 0.5, 0.99).state
    assert dict(state.player.cooldowns)["ruin"] == 3  # used round 1 + cooldown 1 + 1


def test_resolve_action_matches_payloads():
    s = setup(fighter(abilities=(ability("hit"),)))
    legal = engine.legal_actions(s, engine.start_state(s), PLAYER, can_collect=True)
    assert engine.resolve_action(legal, {"kind": "attack"}).key == "attack"
    assert engine.resolve_action(legal, {"kind": "ability", "ability_id": "hit"}).percentage == 150
    assert engine.resolve_action(legal, {"kind": "catch", "emblem_tier": "rare"}).emblem_tier == "rare"
    for bad in [{"kind": "ability", "ability_id": "nope"}, {"kind": "dance"}, {"kind": "catch"}, {"kind": "catch", "emblem_tier": "gold"}]:
        with pytest.raises((ActionError, ValueError)):
            engine.resolve_action(legal, bad)


# -- attack and defense --------------------------------------------------------------

def test_basic_attack_is_one_hundred_percent_of_essence():
    out = play(setup(), ATTACK, FLEE, 0.1, 0.99)  # player first; wild flee fails
    assert out.state.wild.hp == 60 and out.state.round == 2


def test_minimum_damage_is_one():
    s = setup(fighter(essence=0))
    assert play(s, ATTACK, FLEE, 0.1, 0.99).state.wild.hp == 99


def test_defense_uses_diminishing_returns_and_protects_one_attack():
    guard = ability("guard", "DEFENSE", 250)  # rating 40 * 2.5 = 100 -> halves damage
    s = setup(wild=fighter(WILD, abilities=(guard,)))
    out = play(s, ATTACK, use(guard), 0.1)
    assert out.state.wild.hp == 80  # 40 * 100 / 200 = 20
    assert out.state.wild.defense is None  # expired at round end


def test_defense_protects_only_its_allowed_attacks():
    guard = ability("guard", "DEFENSE", 250)
    passive = PassiveSpec("defense_extension", {"protected_attacks": 2, "rounds": 2})
    s = setup(player=fighter(PLAYER, speed=1000), wild=fighter(WILD, essence=40, abilities=(guard,), passive=passive))
    r1 = play(s, ATTACK, use(guard), 0.1)
    assert r1.state.wild.hp == 80 and r1.state.wild.defense.attacks_left == 1 and r1.state.wild.defense.rounds_left == 1
    r2 = engine.resolve_round(s, r1.state, ATTACK, ATTACK, ScriptedRandom(0.1))
    assert r2.state.wild.hp == 60  # second protected attack: 20 more damage
    assert r2.state.wild.defense is None  # attacks exhausted


def test_defense_refresh_keeps_the_strongest_rating_and_resets_limits():
    weak, strong = ability("weak", "DEFENSE", 100), ability("strong", "DEFENSE", 300)
    passive = PassiveSpec("defense_extension", {"protected_attacks": 2, "rounds": 2})
    s = setup(wild=fighter(WILD, abilities=(weak, strong), passive=passive))
    r1 = play(s, FLEE, use(strong), 0.5, 0.99)
    assert r1.state.wild.defense.rating == 120 and r1.state.wild.defense.rounds_left == 1
    r2 = engine.resolve_round(s, r1.state, FLEE, use(weak), ScriptedRandom(0.5, 0.99))
    assert r2.state.wild.defense is None or r2.state.wild.defense.rating == 120


def test_defense_refresh_restores_allowance_without_banking():
    guard = ability("guard", "DEFENSE", 100)
    passive = PassiveSpec("defense_extension", {"protected_attacks": 2, "rounds": 2})
    s = setup(wild=fighter(WILD, abilities=(guard,), passive=passive))
    r1 = play(s, FLEE, use(guard), 0.5, 0.99)
    spent = replace(r1.state, wild=replace(r1.state.wild, defense=replace(r1.state.wild.defense, attacks_left=1, rounds_left=1)))
    refreshed = engine.resolve_round(s, spent, FLEE, use(guard), ScriptedRandom(0.5, 0.99))
    assert (refreshed.state.wild.defense.attacks_left, refreshed.state.wild.defense.rounds_left) == (2, 1)


def test_sentinel_adds_unbuffed_essence_share_to_defense_rating():
    guard = ability("guard", "DEFENSE", 100)
    passive = PassiveSpec("defense_rating_bonus", {"essence_fraction": 0.5})
    s = setup(wild=fighter(WILD, essence=40, abilities=(guard,), passive=passive))
    event = next(e for e in play(s, FLEE, use(guard), 0.5, 0.99).events if e["type"] == "defense")
    assert event["rating"] == 60  # 40 + 20


def test_striker_bonus_below_half_hp_and_bruiser_bonus_against_defense():
    low = PassiveSpec("low_hp_attack_bonus", {"hp_below": 0.5, "essence_fraction": 0.5})
    s = setup(player=fighter(PLAYER, essence=40, passive=low))
    hurt = BattleState(1, FighterState(hp=40), FighterState(hp=100))
    assert play(s, ATTACK, FLEE, 0.1, 0.99, state=hurt).state.wild.hp == 40  # 40 + 20 raw
    guard = ability("guard", "DEFENSE", 0)
    bruise = PassiveSpec("attack_bonus_vs_defense", {"essence_fraction": 0.5})
    s2 = setup(player=fighter(PLAYER, essence=40, passive=bruise), wild=fighter(WILD, abilities=(guard,)))
    assert play(s2, ATTACK, use(guard), 0.1).state.wild.hp == 40  # 60 raw, defense rating ~0


def test_knockout_ends_the_round_and_skips_later_actions():
    s = setup(player=fighter(PLAYER, essence=200, speed=1000), wild=fighter(WILD, hp=50))
    out = play(s, ATTACK, ATTACK, 0.1)
    assert out.terminal == "won" and out.state.round == 1
    assert out.state.player.hp == 100  # the wild's attack never ran
    assert len(out.draws) == 1 and out.emblem_consumed is None


def test_player_knocked_out():
    s = setup(player=fighter(PLAYER, hp=10, speed=1), wild=fighter(WILD, essence=200, speed=1000))
    assert play(s, ATTACK, ATTACK, 0.99).terminal == "knocked_out"


# -- support and buffs ---------------------------------------------------------------

def test_support_buff_applies_to_this_rounds_attack_and_lasts_its_duration():
    focus = ability("focus", "SUPPORT", 50, stat="essence", duration=2)
    s = setup(player=fighter(PLAYER, essence=40, abilities=(focus,)))
    r1 = play(s, use(focus), FLEE, 0.1, 0.99)
    assert r1.state.player.buffs[0].amount == 20 and r1.state.player.buffs[0].rounds_left == 1
    r2 = engine.resolve_round(s, r1.state, ATTACK, FLEE, ScriptedRandom(0.1, 0.99))
    assert r2.state.wild.hp == 40  # attack uses 60 ESSENCE
    assert r2.state.player.buffs == ()  # expired after its second round


def test_reusing_a_support_refreshes_without_stacking_and_different_buffs_add():
    a = ability("a", "SUPPORT", 50, stat="essence", duration=2)
    b = ability("b", "SUPPORT", 25, stat="essence", duration=3)
    s = setup(player=fighter(PLAYER, essence=40, abilities=(a, b)))
    running = replace(engine.start_state(s), player=FighterState(hp=100, buffs=(Buff("a", "essence", 20, 2),)))
    refreshed = engine.resolve_round(s, running, use(a), FLEE, ScriptedRandom(0.1, 0.99)).state
    assert [(x.source, x.amount, x.rounds_left) for x in refreshed.player.buffs] == [("a", 20, 1)]  # one copy, restarted
    added = engine.resolve_round(s, running, use(b), FLEE, ScriptedRandom(0.1, 0.99)).state
    assert sum(x.amount for x in added.player.buffs) == 30  # 20 + 10, added


def test_channeler_passive_extends_support_duration():
    focus = ability("focus", "SUPPORT", 50, stat="essence", duration=2)
    s = setup(player=fighter(PLAYER, abilities=(focus,), passive=PassiveSpec("support_duration_bonus", {"rounds": 1})))
    assert play(s, use(focus), FLEE, 0.1, 0.99).state.player.buffs[0].rounds_left == 2  # 3 total, 1 spent


def test_speed_buff_changes_this_rounds_order_roll():
    quick = ability("quick", "SUPPORT", 100, stat="speed", duration=2)
    s = setup(player=fighter(PLAYER, essence=30, speed=10, abilities=(quick,)), wild=fighter(WILD, speed=40))
    out = play(s, use(quick), FLEE, 0.5, 0.99)
    order = next(e for e in out.events if e["type"] == "order")
    assert order["chance_player_first"] == pytest.approx(40 / 80, abs=1e-4)  # speed 10 + 30 against 40


# -- order ---------------------------------------------------------------------------

@pytest.mark.parametrize("draw,first", [(0.59, PLAYER), (0.61, WILD)])
def test_order_roll_uses_speed_probability(draw, first):
    s = setup(player=fighter(PLAYER, speed=60), wild=fighter(WILD, speed=40))
    out = play(s, ATTACK, ATTACK, draw)
    assert next(e for e in out.events if e["type"] == "order")["first"] == first


def test_exactly_one_order_roll_even_when_nothing_needs_ordering():
    guard = ability("guard", "DEFENSE", 100)
    s = setup(player=fighter(PLAYER, abilities=(guard,)), wild=fighter(WILD, abilities=(guard,)))
    out = play(s, use(guard), use(guard), 0.5)
    assert len(out.draws) == 1


# -- flee and catch ------------------------------------------------------------------

def test_flee_chance_formula_and_success():
    s = setup(player=fighter(PLAYER, essence=100, speed=1000))
    out = play(s, FLEE, ATTACK, 0.1, 0.49)  # 100 / 200 * full HP = 0.5
    assert out.terminal == "escaped"
    flee = next(e for e in out.events if e["type"] == "flee")
    assert flee["chance"] == pytest.approx(0.5) and flee["success"] is True


def test_flee_chance_scales_with_remaining_hp():
    s = setup(player=fighter(PLAYER, essence=100, speed=1000))
    hurt = BattleState(1, FighterState(hp=50), FighterState(hp=100))
    flee = next(e for e in play(s, FLEE, ATTACK, 0.1, 0.99, state=hurt).events if e["type"] == "flee")
    assert flee["chance"] == pytest.approx(0.25)


def test_flee_uses_the_hp_left_when_the_attempt_resolves():
    # The wild Spark acts first and halves the player's HP, so the escape chance is 0.5 * 0.5.
    s = setup(player=fighter(PLAYER, hp=100, essence=100, speed=1), wild=fighter(WILD, essence=50, speed=1000))
    out = play(s, FLEE, ATTACK, 0.99, 0.99)
    flee = next(e for e in out.events if e["type"] == "flee")
    assert flee["chance"] == pytest.approx(0.25) and out.state.player.hp == 50


def test_the_order_roll_follows_the_speed_ratio_over_many_rounds():
    from src.sparks.runtime import SeededRandom

    s = setup(player=fighter(PLAYER, speed=60), wild=fighter(WILD, speed=40))
    state, rng, first = engine.start_state(s), SeededRandom(9), 0
    for _ in range(4000):
        out = engine.resolve_round(s, state, FLEE, FLEE, rng)
        first += next(e for e in out.events if e["type"] == "order")["first"] == PLAYER
    assert first / 4000 == pytest.approx(0.6, abs=0.03)


@pytest.mark.parametrize("draw", [0.01, 0.99])  # the order roll must not matter
def test_catch_counters_flee_whatever_the_order(draw):
    s = setup(player=fighter(PLAYER, essence=100), wild=fighter(WILD, essence=100))
    out = play(s, FLEE, CATCH_WILD, draw, 0.2)
    flee = next(e for e in out.events if e["type"] == "flee")
    assert flee["chance"] == pytest.approx(0.25)  # 0.5 * 100 / 200
    assert out.emblem_consumed is None


def test_player_catch_against_flee_makes_no_collection_attempt():
    s = setup(player=fighter(PLAYER, essence=100), wild=fighter(WILD, essence=100))
    out = play(s, catch(), FLEE, 0.01, 0.99)
    assert out.emblem_consumed is None and out.terminal is None
    assert next(e for e in out.events if e["type"] == "flee")["chance"] == pytest.approx(0.25)


def test_capture_chance_matches_the_formula():
    s = setup(wild=fighter(WILD, hp=100, tier_id="rare"))
    state = engine.start_state(s)
    # resistance = 100 * 2 * (0.2 + 0.8 * 1) = 200; Rare EMBLEM strength 200
    assert engine.capture_chance("rare", s.wild, state.wild) == pytest.approx(0.5)
    half = FighterState(hp=50)
    assert engine.capture_chance("rare", s.wild, half) == pytest.approx(200 / (200 + 200 * 0.6))


def test_forbidden_keeps_most_of_its_resistance_at_low_hp():
    s = setup(wild=fighter(WILD, hp=100, tier_id="forbidden"))
    nearly_dead = FighterState(hp=1)
    chance = engine.capture_chance("forbidden", s.wild, nearly_dead)
    assert chance == pytest.approx(3200 / (3200 + 12800 * (0.8 + 0.2 * 0.01)))


@pytest.mark.parametrize("draw,captured", [(0.4, True), (0.6, False)])
def test_collection_consumes_the_emblem_win_or_lose(draw, captured):
    s = setup(wild=fighter(WILD, tier_id="rare"))
    out = play(s, catch("rare"), ATTACK, 0.1, draw)  # player acts first; chance 0.5
    assert out.emblem_consumed == "rare"
    assert (out.terminal == "captured") is captured


def test_wild_catch_against_a_non_flee_action_does_nothing():
    out = play(setup(), ATTACK, CATCH_WILD, 0.1)
    assert out.terminal is None and out.emblem_consumed is None


def test_terminal_result_preempts_a_later_collection_attempt():
    s = setup(player=fighter(PLAYER, speed=1), wild=fighter(WILD, essence=500, speed=1000))
    out = play(s, catch(), ATTACK, 0.99)  # wild acts first and knocks the player out
    assert out.terminal == "knocked_out" and out.emblem_consumed is None


# -- history and serialization -------------------------------------------------------

def test_history_records_revealed_actions_and_round_advances():
    out = play(setup(), ATTACK, FLEE, 0.1, 0.99)
    revealed = out.state.history[0]
    assert revealed.round == 1 and revealed.actions == {PLAYER: ("attack", "ATTACK"), WILD: ("flee", "FEAR")}


def test_battle_state_and_setup_round_trip_through_json():
    import json

    s = BattleSetup(engine.build_fighter(PLAYER, "scout", "rare", 12), engine.build_fighter(WILD, "forbidden", "forbidden", 5))
    out = play(s, ATTACK, FLEE, 0.1, 0.99)
    assert BattleSetup.from_dict(json.loads(json.dumps(s.to_dict()))) == s
    assert BattleState.from_dict(json.loads(json.dumps(out.state.to_dict()))) == out.state
