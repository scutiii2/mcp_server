import random

import pytest

from src.ascension.models import Action, PersonalityInstance
from src.ascension.policy import ActionPolicy, Mood, PolicyContext, Situation
from tests.ascension.env import CATALOG

policy = ActionPolicy(CATALOG.policy)
mood = Mood(CATALOG)

ATTACK = Action("attack", "ATTACK")
FLEE = Action("flee", "FEAR")
CATCH = Action("catch", "INTERCEPT")
DEFEND = Action("ability", "DEFENSE", "guard", 200)
BUFF = Action("ability", "SUPPORT", "rally", 50)
ACTIONS = [ATTACK, DEFEND, BUFF, FLEE, CATCH]


def ctx(danger=0.3, aggression=0.5, advantage=0.5, weights=None, recent=(), collector=False, enemy_hp=1.0, flee_share=0.1):
    return PolicyContext(Situation(danger, aggression, advantage), enemy_hp, flee_share, collector, tuple(recent), weights or {})


def probs(actions=ACTIONS, **kwargs):
    return dict(zip([a.key for a in actions], policy.probabilities(actions, ctx(**kwargs))))


# -- mood ----------------------------------------------------------------------------

AGGRESSIVE3 = PersonalityInstance("p1", "AGGRESSIVE", 3)
CAUTIOUS2 = PersonalityInstance("p2", "CAUTIOUS", 2)


def test_mood_draw_is_uniform_over_instances():
    assert [Mood.pick(3, u) for u in (0.0, 0.33, 0.34, 0.66, 0.67, 0.999)] == [0, 0, 1, 1, 2, 2]
    assert Mood.pick(1, 0.7) == 0


def test_mood_weights_follow_the_spec_example():
    assert mood.weights([AGGRESSIVE3, CAUTIOUS2], 0) == {"ATTACK": 3, "DEFENSE": 1, "SUPPORT": 0, "FEAR": 1, "INTERCEPT": 0}
    assert mood.weights([AGGRESSIVE3, CAUTIOUS2], 1) == {"ATTACK": 1.5, "DEFENSE": 2, "SUPPORT": 0, "FEAR": 2, "INTERCEPT": 0}


def test_a_single_personality_is_always_the_mood():
    assert mood.weights([AGGRESSIVE3], 0)["ATTACK"] == 3


def test_repeated_types_add():
    three = [PersonalityInstance(f"p{i}", "AGGRESSIVE", 3) for i in range(3)]
    assert mood.weights(three, 0)["ATTACK"] == 3 + 1.5 + 1.5


# -- probabilities -------------------------------------------------------------------

def test_probabilities_sum_to_one_and_cover_every_action():
    p = probs()
    assert sum(p.values()) == pytest.approx(1.0) and set(p) == {"attack", "ability:guard", "ability:rally", "flee", "catch"}


def test_every_legal_action_stays_possible():
    assert all(value > 0 for value in probs(weights={"ATTACK": 9}, danger=0.0, advantage=1.0).values())


def test_personality_weight_raises_its_category_without_forcing_it():
    base, aggressive = probs(), probs(weights={"ATTACK": 3})
    assert aggressive["attack"] > base["attack"] and aggressive["attack"] < 0.9


def test_low_hp_still_raises_defense_and_flee_for_an_aggressive_ascended():
    safe = probs(weights={"ATTACK": 3}, danger=0.0, advantage=0.5)
    critical = probs(weights={"ATTACK": 3}, danger=1.0, advantage=0.1)
    assert critical["ability:guard"] > safe["ability:guard"] and critical["flee"] > safe["flee"]
    assert critical["attack"] < safe["attack"]


def test_each_repeat_halves_an_actions_weight_until_another_action_breaks_the_run():
    ratio = lambda p: p["attack"] / p["ability:guard"]  # noqa: E731  (the guard weight is never repeated here)
    base = ratio(probs())
    assert ratio(probs(recent=["attack"])) == pytest.approx(base * 0.5)
    assert ratio(probs(recent=["attack", "attack"])) == pytest.approx(base * 0.25)
    assert ratio(probs(recent=["attack", "attack", "flee"])) == pytest.approx(base)  # the run ended at flee


def test_stronger_abilities_are_preferred_within_a_category():
    weak, strong = Action("ability", "ATTACK", "weak", 100), Action("ability", "ATTACK", "strong", 200)
    p = probs([weak, strong, FLEE])
    assert p["ability:strong"] == pytest.approx(2 * p["ability:weak"])


def test_a_lone_action_in_its_category_has_unit_potency():
    p1 = probs([ATTACK, FLEE])
    assert p1["attack"] > p1["flee"]


def test_collector_catch_grows_as_the_enemy_weakens():
    healthy = probs(collector=True, enemy_hp=1.0)["catch"]
    weak = probs(collector=True, enemy_hp=0.1)["catch"]
    assert weak > healthy


def test_wild_catch_follows_the_enemys_flee_share():
    low = probs(collector=False, flee_share=0.1)["catch"]
    high = probs(collector=False, flee_share=0.9)["catch"]
    assert high > low


def test_no_actions_is_an_error():
    with pytest.raises(ValueError):
        policy.probabilities([], ctx())


# -- choosing ------------------------------------------------------------------------

def test_choose_walks_the_cumulative_distribution():
    p = policy.probabilities(ACTIONS, ctx())
    assert policy.choose(ACTIONS, ctx(), 0.0).action == ATTACK
    assert policy.choose(ACTIONS, ctx(), p[0] + 1e-6).action == DEFEND
    assert policy.choose(ACTIONS, ctx(), 0.999999).action == CATCH
    assert policy.choose(ACTIONS, ctx(), 0.0).probabilities == tuple(p)


def sample(weights, n=4000, **kwargs):
    rng = random.Random(7)
    counts: dict[str, int] = {}
    for _ in range(n):
        key = policy.choose(ACTIONS, ctx(weights=weights, **kwargs), rng.random()).action.key
        counts[key] = counts.get(key, 0) + 1
    return {k: v / n for k, v in counts.items()}


def test_aggressive_attacks_more_and_coward_flees_more_over_many_draws():
    aggressive = sample(mood.weights([AGGRESSIVE3], 0))
    coward = sample(mood.weights([PersonalityInstance("c", "COWARD", 3)], 0))
    neutral = sample({})
    assert aggressive["attack"] > neutral["attack"] > coward["attack"]
    assert coward["flee"] > neutral["flee"] > aggressive["flee"]


def test_no_personality_picks_one_action_every_time():
    freq = sample(mood.weights([AGGRESSIVE3], 0), danger=0.2, advantage=0.8)
    assert max(freq.values()) < 0.8 and len(freq) == len(ACTIONS)
