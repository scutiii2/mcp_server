"""The public JSON view of a battle.

Only public information: both Ascended' stats and effects, revealed history, the
player's legal actions and any EMBLEM prompt. Never the wild Ascended's
personalities, its pending action, the mood draw or action probabilities. A
finished battle adds its result, which reveals the source personalities only
after a capture.
"""

from __future__ import annotations

from typing import Any

from src.ascension.catalog import Catalog
from src.ascension.engine import BattleEngine
from src.ascension.models import PLAYER, WILD
from src.ascension.records import BattleRecord


class BattleViewBuilder:
    def __init__(self, engine: BattleEngine, catalog: Catalog) -> None:
        self._engine, self._catalog = engine, catalog

    def tiers_up_to(self, limit: str | None) -> list[str]:
        """Tier ids from the weakest up to and including `limit`."""
        if limit is None:
            return []
        ids = [t.id for t in self._catalog.tiers]
        return ids[: ids.index(self._catalog.tier(limit).id) + 1]

    def permitted_tiers(self, emblems: dict[str, int], limit: str | None) -> list[str]:
        """Owned EMBLEM tiers an autonomous Ascended may use."""
        return [tier for tier in self.tiers_up_to(limit) if emblems.get(tier, 0) > 0]

    def _fighter(self, record: BattleRecord, side: str) -> dict[str, Any]:
        fighter, state = record.setup.of(side), record.state.of(side)
        ready = dict(state.cooldowns)
        return {
            "ascended_id": fighter.ascended_id, "name": self._catalog.ascended(fighter.ascended_id).name,
            "tier_id": fighter.tier_id, "level": fighter.level, "hp": state.hp, "max_hp": fighter.max_hp,
            "essence": self._engine.stat(fighter, state, "essence"), "speed": self._engine.stat(fighter, state, "speed"),
            "buffs": [b.to_dict() for b in state.buffs],
            "defense": state.defense.to_dict() if state.defense else None,
            "abilities": [
                {"id": a.id, "name": a.name, "category": a.category, "percentage": a.percentage,
                 "cooldown": a.cooldown, "ready": record.state.round >= ready.get(a.id, 0)}
                for a in fighter.abilities
            ],
        }

    def build(self, record: BattleRecord, emblems: dict[str, int], now: float) -> dict[str, Any]:
        finished = record.status != "active"
        actions: list[dict[str, Any]] = []
        if not finished:
            names = {a.id: a.name for a in record.setup.player.abilities}
            for action in self._engine.legal_actions(record.setup, record.state, PLAYER, can_collect=bool(emblems)):
                actions.append({"kind": action.kind, "category": action.category, "ability_id": action.ability_id,
                                "name": names.get(action.ability_id), "percentage": action.percentage})
        prompt = None
        if record.phase == "awaiting_emblem" and record.pending:
            deadline = record.pending["deadline"]
            prompt = {"deadline": deadline, "seconds_left": max(0.0, deadline - now),
                      "permitted_tiers": self.permitted_tiers(emblems, record.emblem_limit), "owned": emblems}
        return {
            "id": record.id, "status": record.status, "phase": record.phase, "mode": record.mode,
            "round": record.state.round, "revision": record.revision, "emblem_limit": record.emblem_limit,
            "player": self._fighter(record, PLAYER), "wild": self._fighter(record, WILD),
            "actions": actions, "emblems": emblems, "prompt": prompt,
            "history": [h.to_dict() for h in record.state.history], "result": record.result,
        }
