"""The action policy: how a Spark picks its action when it plays on its own.

Pure and synchronous. Situation values (from Laya or heuristics), the round's
personality weights, a potency term and a repeat penalty become action
probabilities; the engine's seeded random draw picks one. A fixed personality
therefore biases behaviour without making it predictable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from src.sparks.catalog import Catalog, PolicySpec
from src.sparks.models import CATEGORIES, Action, PersonalityInstance


@dataclass(frozen=True)
class Situation:
    """Each value is 0 to 1."""

    danger: float
    aggression: float  # how aggressively the enemy has acted
    advantage: float  # does this Spark have the upper hand


@dataclass(frozen=True)
class PolicyContext:
    situation: Situation
    enemy_hp_fraction: float
    enemy_flee_share: float  # share of revealed rounds the enemy chose FLEE
    collector: bool  # True for the player's Spark: CATCH can collect
    recent_keys: tuple[str, ...]  # this Spark's own previous action keys, oldest first
    weights: Mapping[str, float]  # round personality weights per category


@dataclass(frozen=True)
class PolicyDecision:
    action: Action
    probabilities: tuple[float, ...]  # same order as the actions passed in


class Mood:
    """Which equipped personality leads this round, and the resulting weights."""

    def __init__(self, catalog: Catalog) -> None:
        self._catalog = catalog
        self._off = catalog.policy.off_mood_factor

    @staticmethod
    def pick(count: int, u: float) -> int:
        """Uniform index of the leading instance for one draw u in [0, 1)."""
        return min(int(u * count), count - 1)

    def weights(self, instances: Sequence[PersonalityInstance], lead: int) -> dict[str, float]:
        """The lead instance counts fully, the others at the off-mood factor;
        weights add per category. A personality gives its tier as the weight for
        each of its categories."""
        totals = {category: 0.0 for category in CATEGORIES}
        for index, instance in enumerate(instances):
            factor = 1.0 if index == lead else self._off
            for category in self._catalog.personalities[instance.type_id].categories:
                totals[category] += instance.tier * factor
        return totals


class ActionPolicy:
    def __init__(self, spec: PolicySpec) -> None:
        self._spec = spec

    def situation_value(self, category: str, ctx: PolicyContext) -> float:
        s, c = ctx.situation, self._spec.coefficients[category]
        if category == "ATTACK":
            value = c["base"] + c["advantage"] * s.advantage + c["safety"] * (1 - s.danger)
        elif category == "DEFENSE":
            value = c["base"] + c["danger"] * s.danger + c["aggression"] * s.aggression
        elif category == "SUPPORT":
            value = c["base"] + c["safety"] * (1 - s.danger) + c["passivity"] * (1 - s.aggression)
        elif category == "FEAR":
            value = c["base"] + c["escape_pressure"] * s.danger * (1 - s.advantage)
        elif ctx.collector:
            value = c["collector_base"] + c["collector_weakness"] * (1 - ctx.enemy_hp_fraction) * (1 - s.danger)
        else:
            value = c["wild_base"] + c["wild_flee_share"] * ctx.enemy_flee_share
        return max(value, self._spec.floor)

    def probabilities(self, actions: Sequence[Action], ctx: PolicyContext) -> list[float]:
        if not actions:
            raise ValueError("no legal actions to choose from")
        mean_percentage: dict[str, float] = {}
        for category in CATEGORIES:
            members = [a.percentage for a in actions if a.category == category]
            if members:
                mean_percentage[category] = sum(members) / len(members)
        weights = []
        for action in actions:
            potency = 1.0
            if action.kind in ("attack", "ability") and mean_percentage[action.category] > 0:
                potency = action.percentage / mean_percentage[action.category]
            repeats = 0
            for key in reversed(ctx.recent_keys):
                if key != action.key:
                    break
                repeats += 1
            weights.append(
                self.situation_value(action.category, ctx)
                * (1 + self._spec.gain * ctx.weights.get(action.category, 0.0))
                * potency
                * self._spec.repeat_factor ** repeats
            )
        total = sum(weights)
        return [w / total for w in weights]

    def choose(self, actions: Sequence[Action], ctx: PolicyContext, u: float) -> PolicyDecision:
        probabilities = self.probabilities(actions, ctx)
        cumulative = 0.0
        for action, probability in zip(actions, probabilities):
            cumulative += probability
            if u < cumulative:
                return PolicyDecision(action, tuple(probabilities))
        return PolicyDecision(actions[-1], tuple(probabilities))  # u rounding past the last bucket
