"""Situation reads: how much danger a Spark is in, how aggressive its enemy has
been and whether it has the upper hand.

Laya answers these as typed questions about a short public-state text. An
engine heuristic computes the same three values, and a read that is uncertain,
invalid, late or missing is replaced by its heuristic value one question at a
time, so the game never depends on the model. Only public information goes in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from src.laya_client import LayaClient, LayaError, noul_question, score_question
from src.sparks.engine import BattleEngine
from src.sparks.models import BattleSetup, BattleState, other
from src.sparks.policy import Situation

DANGER_LEVELS = ["safe", "pressured", "endangered", "critical"]
AGGRESSION_LEVELS = ["passive", "mixed", "aggressive"]
HISTORY_ROUNDS = 6  # keeps the Laya text well inside the 512-token window


@dataclass(frozen=True)
class SituationView:
    """Public state from one Spark's side of the battle."""

    round: int
    own_hp_fraction: float
    enemy_hp_fraction: float
    own_essence: int
    enemy_essence: int
    own_speed: int
    enemy_speed: int
    own_history: tuple[str, ...]  # categories of its own revealed actions, oldest first
    enemy_history: tuple[str, ...]

    def to_text(self) -> str:
        recent = lambda h: ", ".join(h[-HISTORY_ROUNDS:]) or "none"  # noqa: E731
        return (
            f"Round {self.round}. Own HP {self.own_hp_fraction:.0%}, enemy HP {self.enemy_hp_fraction:.0%}. "
            f"ESSENCE own {self.own_essence}, enemy {self.enemy_essence}. "
            f"SPEED own {self.own_speed}, enemy {self.enemy_speed}. "
            f"Enemy recent actions: {recent(self.enemy_history)}. Own recent actions: {recent(self.own_history)}."
        )


@dataclass(frozen=True)
class PartialSituation:
    """Any value may be missing; None means "use the heuristic"."""

    danger: float | None = None
    aggression: float | None = None
    advantage: float | None = None


class SituationViewBuilder:
    def __init__(self, engine: BattleEngine) -> None:
        self._engine = engine

    def build(self, setup: BattleSetup, state: BattleState, side: str) -> SituationView:
        foe = other(side)
        own, enemy = setup.of(side), setup.of(foe)
        own_state, enemy_state = state.of(side), state.of(foe)
        return SituationView(
            round=state.round,
            own_hp_fraction=own_state.hp / own.max_hp,
            enemy_hp_fraction=enemy_state.hp / enemy.max_hp,
            own_essence=self._engine.stat(own, own_state, "essence"),
            enemy_essence=self._engine.stat(enemy, enemy_state, "essence"),
            own_speed=self._engine.stat(own, own_state, "speed"),
            enemy_speed=self._engine.stat(enemy, enemy_state, "speed"),
            own_history=tuple(r.actions[side][1] for r in state.history),
            enemy_history=tuple(r.actions[foe][1] for r in state.history),
        )


class SituationReader(Protocol):
    async def read(self, view: SituationView) -> Situation: ...


class PartialSituationReader(Protocol):
    async def read_partial(self, view: SituationView) -> PartialSituation: ...


class HeuristicSituationReader:
    """The engine's own estimate. Needs no model."""

    def __init__(self, default_aggression: float = 0.5) -> None:
        self._default_aggression = default_aggression

    def compute(self, view: SituationView) -> Situation:
        history = view.enemy_history
        aggression = history.count("ATTACK") / len(history) if history else self._default_aggression
        advantage = 0.5 + 0.5 * (view.own_hp_fraction - view.enemy_hp_fraction)
        return Situation(
            danger=min(1.0, max(0.0, 1 - view.own_hp_fraction)),
            aggression=aggression,
            advantage=min(1.0, max(0.0, advantage)),
        )

    async def read(self, view: SituationView) -> Situation:
        return self.compute(view)


class LayaPartialSituationReader:
    """Asks Laya the three questions in one call. A failed call, or an uncertain
    answer, leaves that value as None."""

    def __init__(self, client: LayaClient) -> None:
        self._client = client

    async def read_partial(self, view: SituationView) -> PartialSituation:
        questions = {
            "danger": score_question("How much danger is this fighter in?", DANGER_LEVELS),
            "advantage": noul_question(
                "Does this fighter have the upper hand?",
                "The fighter is at a disadvantage.", "The fighter has the upper hand.",
            ),
        }
        if view.enemy_history:  # nothing to judge in round 1
            questions["aggression"] = score_question("How aggressively has the enemy acted?", AGGRESSION_LEVELS)
        try:
            answers = await self._client.ask(view.to_text(), questions)
        except LayaError:
            return PartialSituation()

        def value(qid: str, scale: float) -> float | None:
            answer = answers.get(qid)
            return None if answer is None or answer.uncertain else answer.value / scale

        return PartialSituation(
            danger=value("danger", len(DANGER_LEVELS) - 1),
            aggression=value("aggression", len(AGGRESSION_LEVELS) - 1),
            advantage=value("advantage", 1.0),
        )


class FallbackSituationReader:
    """Primary read, with the heuristic filling in each value the primary lacks."""

    def __init__(self, primary: PartialSituationReader, heuristic: HeuristicSituationReader) -> None:
        self._primary, self._heuristic = primary, heuristic

    async def read(self, view: SituationView) -> Situation:
        fallback = self._heuristic.compute(view)
        partial = await self._primary.read_partial(view)
        return Situation(
            danger=fallback.danger if partial.danger is None else partial.danger,
            aggression=fallback.aggression if partial.aggression is None else partial.aggression,
            advantage=fallback.advantage if partial.advantage is None else partial.advantage,
        )
