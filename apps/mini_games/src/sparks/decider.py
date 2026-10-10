"""Turns a battle's public state into one Spark's action: situation read,
mood draw, personality weights, probabilities, seeded draw."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from src.sparks.catalog import Catalog
from src.sparks.engine import BattleEngine
from src.sparks.models import PLAYER, Action, BattleSetup, BattleState, PersonalityInstance
from src.sparks.policy import ActionPolicy, Mood, PolicyContext
from src.sparks.runtime import RandomSource
from src.sparks.situation import SituationReader, SituationViewBuilder


@dataclass(frozen=True)
class Decision:
    action: Action
    audit: dict[str, Any]  # kept privately with the round; never in a public view


class ActionDecider:
    def __init__(self, catalog: Catalog, engine: BattleEngine, policy: ActionPolicy, mood: Mood,
                 reader: SituationReader, views: SituationViewBuilder) -> None:
        self._catalog, self._engine, self._policy, self._mood = catalog, engine, policy, mood
        self._reader, self._views = reader, views

    async def decide(
        self, setup: BattleSetup, state: BattleState, side: str, instances: Sequence[PersonalityInstance],
        rng: RandomSource, *, can_collect: bool,
    ) -> Decision:
        """Pick `side`'s action from public state, its own personalities and its own history.
        Nothing about the opponent's pending choice is available here."""
        view = self._views.build(setup, state, side)
        situation = await self._reader.read(view)
        legal = self._engine.legal_actions(setup, state, side, can_collect=can_collect)
        lead = Mood.pick(len(instances), rng.next()) if instances else None
        weights = self._mood.weights(instances, lead) if instances else {}
        history = view.enemy_history
        flee_share = history.count("FEAR") / len(history) if history else self._catalog.policy.default_flee_share
        context = PolicyContext(
            situation=situation, enemy_hp_fraction=view.enemy_hp_fraction, enemy_flee_share=flee_share,
            collector=side == PLAYER, recent_keys=tuple(r.actions[side][0] for r in state.history), weights=weights,
        )
        decision = self._policy.choose(legal, context, rng.next())
        audit = {
            "side": side, "mood": instances[lead].id if instances else None,
            "situation": {"danger": situation.danger, "aggression": situation.aggression, "advantage": situation.advantage},
            "probabilities": {a.key: round(p, 4) for a, p in zip(legal, decision.probabilities)},
            "chosen": decision.action.key,
        }
        return Decision(decision.action, audit)
