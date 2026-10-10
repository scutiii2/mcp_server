import asyncio
from pathlib import Path

import pytest

from src.sparks.catalog import Catalog
from src.sparks.models import PLAYER, WILD
from src.sparks.simulation import BattleSimulator, Combatant, personality_set
from src.sparks.situation import HeuristicSituationReader

CATALOG = Catalog.load(Path(__file__).resolve().parents[2] / "configs" / "spark_catalog.json")
sim = BattleSimulator(CATALOG)
reader = HeuristicSituationReader(CATALOG.policy.default_aggression)


def spark(species="striker", level=5, personalities=(), tier="normal"):
    return Combatant(species, tier, level, personality_set(CATALOG, *personalities), reader)


def run(coro):
    return asyncio.run(coro)


def test_a_battle_finishes_and_the_same_seed_replays_exactly():
    a, b = spark(personalities=[("AGGRESSIVE", 2)]), spark("bruiser", personalities=[("BOLD", 2)])
    first, second = run(sim.run(a, b, seed=4)), run(sim.run(a, b, seed=4))
    assert first == second and first.ended_by != "round_limit" and first.rounds >= 1
    assert sum(first.actions[PLAYER].values()) == len(first.views)


def test_a_much_stronger_spark_wins():
    strong = spark("forbidden", level=40, tier="forbidden", personalities=[("AGGRESSIVE", 3)])
    weak = spark("guardian", level=1, personalities=[("AGGRESSIVE", 3)])
    results = [run(sim.run(strong, weak, seed=s)).winner for s in range(10)]
    assert WILD not in results and results.count(PLAYER) >= 8  # the weak side may escape, but never wins


def shares(personality, category, side, battles=120):
    me = spark(personalities=[personality])
    other = spark("guardian", personalities=[("DEFENSIVE", 1)])
    reports = [run(sim.run(me, other, seed=s, max_rounds=30)) for s in range(battles)]
    return sum(r.share(side, category) for r in reports) / battles


def test_aggressive_attacks_more_often_than_coward_and_coward_flees_more_often():
    aggressive_attack = shares(("AGGRESSIVE", 3), "ATTACK", PLAYER)
    coward_attack = shares(("COWARD", 3), "ATTACK", PLAYER)
    aggressive_flee = shares(("AGGRESSIVE", 3), "FEAR", PLAYER)
    coward_flee = shares(("COWARD", 3), "FEAR", PLAYER)
    assert aggressive_attack > coward_attack
    assert coward_flee > aggressive_flee


def test_neither_personality_collapses_to_one_action():
    """Evenly matched, durable Sparks fight for many rounds; no personality repeats one category."""
    for personality in ("AGGRESSIVE", "COWARD", "DEFENSIVE"):
        mine = spark("sentinel", level=20, personalities=[(personality, 3)])
        reports = [run(sim.run(mine, spark("sentinel", level=20, personalities=[("DISCIPLINED", 2)]), seed=s, max_rounds=30))
                   for s in range(40)]
        totals: dict[str, int] = {}
        for r in reports:
            for category, n in r.actions[PLAYER].items():
                totals[category] = totals.get(category, 0) + n
        assert sum(totals.values()) > 200 and max(totals.values()) / sum(totals.values()) < 0.85, (personality, totals)


def test_low_hp_makes_every_personality_more_defensive_or_fearful():
    low, high = _situation_probabilities(0.1), _situation_probabilities(1.0)
    assert low["DEFENSE"] + low["FEAR"] > high["DEFENSE"] + high["FEAR"]


def _situation_probabilities(own_hp_fraction):
    from src.sparks.models import Action
    from src.sparks.policy import ActionPolicy, PolicyContext
    from src.sparks.situation import SituationView

    view = SituationView(3, own_hp_fraction, 0.8, 40, 40, 20, 20, ("ATTACK",), ("ATTACK",))
    situation = reader.compute(view)
    actions = [Action("attack", "ATTACK"), Action("ability", "DEFENSE", "g", 150), Action("ability", "SUPPORT", "s", 50),
               Action("flee", "FEAR"), Action("catch", "INTERCEPT")]
    ctx = PolicyContext(situation, 0.8, 0.1, True, (), {"ATTACK": 3.0})  # an aggressive personality
    p = ActionPolicy(CATALOG.policy).probabilities(actions, ctx)
    return {"DEFENSE": p[1], "FEAR": p[3]}


def test_neither_side_can_collect_in_a_simulation():
    report = run(sim.run(spark(), spark("sentinel"), seed=2, max_rounds=40))
    assert "captured" != report.ended_by and "INTERCEPT" not in report.actions[PLAYER]


@pytest.mark.parametrize("max_rounds", [1, 2])
def test_the_round_limit_stops_a_long_battle(max_rounds):
    tank_a, tank_b = spark("sentinel", level=30, personalities=[("DEFENSIVE", 3)]), spark("sentinel", level=30, personalities=[("DEFENSIVE", 3)])
    report = run(sim.run(tank_a, tank_b, seed=1, max_rounds=max_rounds))
    assert report.rounds <= max_rounds
