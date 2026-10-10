"""AI against AI battles, for tuning balance and checking that personalities
change behaviour. The same engine and decider as a real battle, with no database
and no clock. Neither side can collect, so a battle ends by knockout or escape."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.sparks.catalog import Catalog
from src.sparks.decider import ActionDecider
from src.sparks.engine import BattleEngine
from src.sparks.models import PLAYER, SIDES, WILD, BattleSetup, PersonalityInstance
from src.sparks.policy import ActionPolicy, Mood
from src.sparks.runtime import SeededRandom
from src.sparks.situation import SituationReader, SituationView, SituationViewBuilder

WINNER_BY_TERMINAL = {"won": PLAYER, "knocked_out": WILD}


@dataclass(frozen=True)
class Combatant:
    species_id: str
    tier_id: str
    level: int
    personalities: tuple[PersonalityInstance, ...]
    reader: SituationReader


@dataclass(frozen=True)
class SimulationReport:
    winner: str | None  # PLAYER or WILD; None when someone escaped or the round limit hit
    ended_by: str  # won, knocked_out, escaped, wild_escaped or round_limit
    rounds: int
    actions: dict[str, dict[str, int]]  # side -> category -> times chosen
    views: tuple[SituationView, ...] = field(default=(), compare=False)  # the player's view each round

    def share(self, side: str, category: str) -> float:
        counts = self.actions[side]
        total = sum(counts.values())
        return counts.get(category, 0) / total if total else 0.0


class BattleSimulator:
    def __init__(self, catalog: Catalog, engine: BattleEngine | None = None) -> None:
        self._catalog = catalog
        self._engine = engine or BattleEngine(catalog)
        self._policy, self._mood = ActionPolicy(catalog.policy), Mood(catalog)
        self._views = SituationViewBuilder(self._engine)

    async def run(self, player: Combatant, wild: Combatant, seed: int, max_rounds: int = 60) -> SimulationReport:
        setup = BattleSetup(
            self._engine.build_fighter(PLAYER, player.species_id, player.tier_id, player.level),
            self._engine.build_fighter(WILD, wild.species_id, wild.tier_id, wild.level),
        )
        deciders = {
            side: ActionDecider(self._catalog, self._engine, self._policy, self._mood, who.reader, self._views)
            for side, who in ((PLAYER, player), (WILD, wild))
        }
        instances = {PLAYER: player.personalities, WILD: wild.personalities}
        state = self._engine.start_state(setup)
        rng = SeededRandom(seed)
        counts: dict[str, dict[str, int]] = {side: {} for side in SIDES}
        seen: list[SituationView] = []
        for _ in range(max_rounds):
            seen.append(self._views.build(setup, state, PLAYER))
            chosen = {}
            for side in SIDES:
                decision = await deciders[side].decide(setup, state, side, instances[side], rng, can_collect=False)
                chosen[side] = decision.action
                counts[side][decision.action.category] = counts[side].get(decision.action.category, 0) + 1
            outcome = self._engine.resolve_round(setup, state, chosen[PLAYER], chosen[WILD], rng)
            state = outcome.state
            if outcome.terminal:
                return SimulationReport(WINNER_BY_TERMINAL.get(outcome.terminal), outcome.terminal, state.round, counts, tuple(seen))
        return SimulationReport(None, "round_limit", max_rounds, counts, tuple(seen))


def personality_set(catalog: Catalog, *types_and_tiers: tuple[str, int]) -> tuple[PersonalityInstance, ...]:
    """Convenience for tests and tuning: ("AGGRESSIVE", 3) -> a PersonalityInstance."""
    return tuple(PersonalityInstance(f"sim-{i}", type_id, tier) for i, (type_id, tier) in enumerate(types_and_tiers))
