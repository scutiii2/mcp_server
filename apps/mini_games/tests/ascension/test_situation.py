import asyncio

import pytest

from src.laya_client import LayaClient
from src.ascension.engine import BattleEngine
from src.ascension.models import PLAYER, WILD, Action
from src.ascension.situation import (
    FallbackSituationReader,
    HeuristicSituationReader,
    LayaPartialSituationReader,
    SituationView,
    SituationViewBuilder,
)
from tests.fake_laya import FakeEngine
from tests.ascension.helpers import ScriptedRandom, fighter, setup
from tests.ascension.env import CATALOG

engine = BattleEngine(CATALOG)
heuristic = HeuristicSituationReader()


def view(**changes) -> SituationView:
    base = dict(round=3, own_hp_fraction=0.5, enemy_hp_fraction=0.8, own_essence=52, enemy_essence=40,
                own_speed=30, enemy_speed=25, own_history=("ATTACK", "FEAR"), enemy_history=("ATTACK", "ATTACK", "DEFENSE"))
    base.update(changes)
    return SituationView(**base)


def run(coro):
    return asyncio.run(coro)


# -- view ----------------------------------------------------------------------------

def test_text_is_compact_and_public():
    text = view().to_text()
    assert text == ("Round 3. Own HP 50%, enemy HP 80%. ESSENCE own 52, enemy 40. SPEED own 30, enemy 25. "
                    "Enemy recent actions: ATTACK, ATTACK, DEFENSE. Own recent actions: ATTACK, FEAR.")


def test_text_keeps_only_recent_history_and_handles_none():
    long = view(enemy_history=tuple(["ATTACK"] * 20), own_history=())
    assert long.to_text().count("ATTACK") == 6 and "Own recent actions: none." in long.to_text()


def test_builder_reads_public_state_from_each_side():
    s = setup(fighter(PLAYER, hp=100, essence=40, speed=20), fighter(WILD, hp=200, essence=30, speed=10))
    state = engine.start_state(s)
    out = engine.resolve_round(s, state, Action("attack", "ATTACK"), Action("flee", "FEAR"), ScriptedRandom(0.1, 0.99))
    mine = SituationViewBuilder(engine).build(s, out.state, PLAYER)
    theirs = SituationViewBuilder(engine).build(s, out.state, WILD)
    assert (mine.own_hp_fraction, mine.enemy_hp_fraction) == (1.0, 0.8)
    assert mine.own_history == ("ATTACK",) and mine.enemy_history == ("FEAR",)
    assert theirs.own_history == ("FEAR",) and theirs.enemy_essence == 40


# -- heuristic -----------------------------------------------------------------------

def test_heuristic_values():
    s = heuristic.compute(view())
    assert s.danger == pytest.approx(0.5)
    assert s.aggression == pytest.approx(2 / 3)
    assert s.advantage == pytest.approx(0.5 + 0.5 * (0.5 - 0.8))


def test_heuristic_defaults_before_any_history_and_clamps():
    s = heuristic.compute(view(round=1, enemy_history=(), own_hp_fraction=1.0, enemy_hp_fraction=0.0))
    assert (s.danger, s.aggression, s.advantage) == (0.0, 0.5, 1.0)
    assert heuristic.compute(view(own_hp_fraction=0.0, enemy_hp_fraction=1.0)).advantage == 0.0


def test_heuristic_reader_is_a_reader():
    assert run(heuristic.read(view())) == heuristic.compute(view())


# -- laya ----------------------------------------------------------------------------

def laya_reader(**kwargs):
    return LayaPartialSituationReader(LayaClient(FakeEngine(**kwargs)))


def test_laya_values_are_normalised():
    p = run(laya_reader(scores={"danger": 3.0, "aggression": 1.0}, noul={"advantage": 0.25}).read_partial(view()))
    assert (p.danger, p.aggression, p.advantage) == (1.0, 0.5, 0.25)


def test_round_one_does_not_ask_about_enemy_aggression():
    engine_ = FakeEngine()
    p = run(LayaPartialSituationReader(LayaClient(engine_)).read_partial(view(round=1, enemy_history=())))
    assert set(engine_.calls[0][1]) == {"danger", "advantage"} and p.aggression is None


def test_question_text_is_the_public_view_only():
    engine_ = FakeEngine()
    run(LayaPartialSituationReader(LayaClient(engine_)).read_partial(view()))
    assert engine_.calls[0][0] == view().to_text()


def test_uncertain_answers_are_dropped():
    assert run(laya_reader(confidence=0.4).read_partial(view())) == run(laya_reader(fail=True).read_partial(view()))


def test_laya_failure_returns_nothing():
    p = run(laya_reader(fail=True).read_partial(view()))
    assert (p.danger, p.aggression, p.advantage) == (None, None, None)


# -- fallback ------------------------------------------------------------------------

def test_fallback_uses_laya_where_it_answered():
    reader = FallbackSituationReader(laya_reader(scores={"danger": 0.0, "aggression": 2.0}, noul={"advantage": 1.0}), heuristic)
    s = run(reader.read(view()))
    assert (s.danger, s.aggression, s.advantage) == (0.0, 1.0, 1.0)


def test_fallback_fills_each_missing_value_from_the_heuristic():
    class OneAnswer:
        async def read_partial(self, v):
            from src.ascension.situation import PartialSituation

            return PartialSituation(danger=0.9)

    s = run(FallbackSituationReader(OneAnswer(), heuristic).read(view()))
    base = heuristic.compute(view())
    assert (s.danger, s.aggression, s.advantage) == (0.9, base.aggression, base.advantage)


def test_without_laya_everything_is_heuristic():
    reader = FallbackSituationReader(laya_reader(fail=True), heuristic)
    assert run(reader.read(view())) == heuristic.compute(view())
