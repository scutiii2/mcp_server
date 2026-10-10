import pytest

from src.ascension.models import PassiveSpec
from src.ascension.passives import Passive, PassiveFactory

factory = PassiveFactory()


def make(kind, **params):
    return factory.create(PassiveSpec(kind, params))


def test_neutral_passive_changes_nothing():
    p = make("none")
    assert p.start_buffs(40) == [] and p.defense_limits() == (1, 1) and p.defense_rating_bonus(40) == 0
    assert p.support_extra_rounds() == 0 and p.attack_bonus(40, 10, 100, True) == 0 and p.cooldown(2) == 2


def test_defense_extension_sets_limits():
    assert make("defense_extension", protected_attacks=2, rounds=2).defense_limits() == (2, 2)


def test_low_hp_bonus_applies_strictly_below_half():
    p = make("low_hp_attack_bonus", hp_below=0.5, essence_fraction=0.2)
    assert p.attack_bonus(50, 49, 100, False) == pytest.approx(10)
    assert p.attack_bonus(50, 50, 100, False) == 0
    assert p.attack_bonus(50, 100, 100, False) == 0


def test_scout_start_speed_uses_unbuffed_essence_floor():
    assert make("battle_start_speed", essence_fraction=0.5).start_buffs(25) == [("speed", 12)]


def test_sentinel_adds_defense_rating():
    assert make("defense_rating_bonus", essence_fraction=0.5).defense_rating_bonus(30) == 15


def test_bruiser_bonus_only_against_defense():
    p = make("attack_bonus_vs_defense", essence_fraction=0.25)
    assert p.attack_bonus(40, 100, 100, True) == 10 and p.attack_bonus(40, 100, 100, False) == 0


def test_channeler_extends_support():
    assert make("support_duration_bonus", rounds=1).support_extra_rounds() == 1


@pytest.mark.parametrize("base,expected", [(2, 1), (3, 2), (1, 1)])
def test_forbidden_cooldown_reduction_has_a_floor(base, expected):
    assert make("cooldown_reduction", rounds=1, minimum=1).cooldown(base) == expected


def test_unknown_kind_is_rejected():
    with pytest.raises(ValueError, match="unknown passive"):
        make("teleport")


def test_new_kinds_can_be_registered():
    custom = PassiveFactory()
    custom.register("echo", lambda: Passive())
    assert isinstance(custom.create(PassiveSpec("echo")), Passive)
