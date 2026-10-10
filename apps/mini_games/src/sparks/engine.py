"""The battle rules. Pure: no database, HTTP, clock or model.

One round, in order: lock both actions, apply SUPPORT then DEFENSE, settle
CATCH-versus-FLEE, roll the action order once from the updated SPEED, resolve
ATTACK / CATCH / FLEE in that order, stop at the first terminal result, then
expire end-of-round effects.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

from src.sparks.catalog import Catalog
from src.sparks.models import (
    PLAYER,
    SIDES,
    WILD,
    AbilitySpec,
    Action,
    BattleSetup,
    BattleState,
    Buff,
    DefenseEffect,
    Fighter,
    FighterState,
    RevealedRound,
    RoundOutcome,
    other,
)
from src.sparks.passives import Passive, PassiveFactory
from src.sparks.runtime import RandomSource, RecordingRandom

_EPS = 1e-9


class ActionError(ValueError):
    """The chosen action is not legal this round."""


class _Side:
    """Mutable working copy of one fighter while a round resolves."""

    def __init__(self, side: str, fighter: Fighter, fstate: FighterState, passive: Passive) -> None:
        self.side, self.fighter, self.passive = side, fighter, passive
        self.hp = fstate.hp
        self.buffs = list(fstate.buffs)
        self.defense = fstate.defense
        self.cooldowns = dict(fstate.cooldowns)

    def stat(self, name: str) -> int:
        return getattr(self.fighter, name) + sum(b.amount for b in self.buffs if b.stat == name)

    def freeze(self) -> FighterState:
        return FighterState(self.hp, tuple(self.buffs), self.defense, tuple(sorted(self.cooldowns.items())))


class BattleEngine:
    def __init__(self, catalog: Catalog, passives: PassiveFactory | None = None) -> None:
        self._catalog = catalog
        self._passives = passives or PassiveFactory()

    # -- setup ---------------------------------------------------------------------

    def build_fighter(self, side: str, species_id: str, tier_id: str, level: int) -> Fighter:
        species = self._catalog.species(species_id)
        stat = lambda name: self._catalog.stat_value(species_id, level, tier_id, name)  # noqa: E731
        return Fighter(
            side=side, species_id=species_id, tier_id=tier_id, level=level,
            max_hp=stat("hp"), essence=stat("essence"), speed=stat("speed"),
            abilities=tuple(a for a in species.abilities if a.unlock_level <= level), passive=species.passive,
        )

    def start_state(self, setup: BattleSetup) -> BattleState:
        def fresh(fighter: Fighter) -> FighterState:
            kind = fighter.passive.kind
            buffs = tuple(Buff(f"passive:{kind}", stat, amount, None)
                          for stat, amount in self._passives.create(fighter.passive).start_buffs(fighter.essence))
            return FighterState(hp=fighter.max_hp, buffs=buffs)

        return BattleState(round=1, player=fresh(setup.player), wild=fresh(setup.wild))

    def stat(self, fighter: Fighter, fstate: FighterState, name: str) -> int:
        """Current ESSENCE or SPEED including temporary buffs."""
        return getattr(fighter, name) + sum(b.amount for b in fstate.buffs if b.stat == name)

    # -- legal actions -------------------------------------------------------------

    def legal_actions(self, setup: BattleSetup, state: BattleState, side: str, *, can_collect: bool) -> list[Action]:
        """Every action `side` may choose this round. `can_collect` says whether
        the collecting side owns an EMBLEM; a wild Spark may always CATCH (it
        only counters FLEE)."""
        fighter, fstate = setup.of(side), state.of(side)
        ready = dict(fstate.cooldowns)
        actions = [Action("attack", "ATTACK")]
        for ability in fighter.abilities:
            if state.round >= ready.get(ability.id, 0):
                actions.append(Action("ability", ability.category, ability.id, ability.percentage))
        actions.append(Action("flee", "FEAR"))
        if side == WILD or can_collect:
            actions.append(Action("catch", "INTERCEPT"))
        return actions

    def resolve_action(self, legal: list[Action], payload: dict[str, Any]) -> Action:
        """Match a client payload ({kind, ability_id?, emblem_tier?}) to a legal action."""
        kind, ability_id = payload.get("kind"), payload.get("ability_id")
        for action in legal:
            if action.kind == kind and action.ability_id == (ability_id if kind == "ability" else None):
                if kind != "catch":
                    return action
                tier = payload.get("emblem_tier")
                if not isinstance(tier, str):
                    raise ActionError("CATCH needs an emblem_tier")
                self._catalog.tier(tier)
                return replace(action, emblem_tier=tier)
        raise ActionError("that action is not available this round")

    # -- chances -------------------------------------------------------------------

    def capture_chance(self, emblem_tier: str, target: Fighter, target_state: FighterState) -> float:
        tier = self._catalog.tier(target.tier_id)
        resistance = (
            self._catalog.economy.base_capture_resistance * tier.capture_multiplier
            * (tier.hp_floor + (1 - tier.hp_floor) * target_state.hp / target.max_hp)
        )
        strength = self._catalog.tier(emblem_tier).emblem_strength
        return strength / (strength + resistance)

    # -- one round -----------------------------------------------------------------

    def resolve_round(
        self, setup: BattleSetup, state: BattleState, player_action: Action, wild_action: Action, rng: RandomSource
    ) -> RoundOutcome:
        rec = RecordingRandom(rng)
        sides = {s: _Side(s, setup.of(s), state.of(s), self._passives.create(setup.of(s).passive)) for s in SIDES}
        actions = {PLAYER: player_action, WILD: wild_action}
        events: list[dict[str, Any]] = []
        rnd = state.round

        for side, action in actions.items():  # cooldowns start when the action is revealed
            if action.kind == "ability":
                ability = self._ability(sides[side].fighter, action.ability_id)
                sides[side].cooldowns[ability.id] = rnd + sides[side].passive.cooldown(ability.cooldown) + 1
        for side in SIDES:  # SUPPORT first, so DEFENSE sees this round's ESSENCE buffs
            if actions[side].category == "SUPPORT":
                self._support(sides[side], self._ability(sides[side].fighter, actions[side].ability_id), events)
        for side in SIDES:
            if actions[side].category == "DEFENSE":
                self._defense(sides[side], self._ability(sides[side].fighter, actions[side].ability_id), events)

        catchers: dict[str, int | None] = {}
        for side in SIDES:  # CATCH reduces FLEE whatever the action order; settled before any escape roll
            if actions[side].kind == "flee":
                foe = sides[other(side)]
                catchers[side] = foe.stat("essence") if actions[other(side)].kind == "catch" else None
                if catchers[side] is not None:
                    events.append({"type": "catch_counters_flee", "side": other(side), "target": side})

        speed = {s: sides[s].stat("speed") for s in SIDES}
        chance_player_first = speed[PLAYER] / (speed[PLAYER] + speed[WILD])
        order = [PLAYER, WILD] if rec.next() < chance_player_first else [WILD, PLAYER]
        events.append({"type": "order", "first": order[0], "chance_player_first": round(chance_player_first, 4)})

        terminal: str | None = None
        emblem: str | None = None
        for side in order:
            if terminal:
                break
            action = actions[side]
            if action.category == "ATTACK":
                terminal = self._attack(sides, actions, side, events)
            elif action.kind == "catch":
                terminal, spent = self._catch(setup, sides, actions, side, rec, events)
                emblem = spent or emblem
            elif action.kind == "flee":
                chance = self._flee(sides[side], catchers[side])  # uses HP as it is when the attempt resolves
                succeeded = rec.next() < chance
                events.append({"type": "flee", "side": side, "chance": round(chance, 4), "success": succeeded})
                if succeeded:
                    terminal = "escaped" if side == PLAYER else "wild_escaped"

        revealed = RevealedRound(rnd, {s: (actions[s].key, actions[s].category) for s in SIDES}, tuple(events))
        if not terminal:
            for side_obj in sides.values():
                self._expire(side_obj)
        new_state = BattleState(
            round=rnd if terminal else rnd + 1,
            player=sides[PLAYER].freeze(), wild=sides[WILD].freeze(), history=state.history + (revealed,),
        )
        return RoundOutcome(new_state, tuple(events), terminal, emblem, tuple(rec.draws))

    # -- parts of a round ----------------------------------------------------------

    @staticmethod
    def _ability(fighter: Fighter, ability_id: str | None) -> AbilitySpec:
        for ability in fighter.abilities:
            if ability.id == ability_id:
                return ability
        raise ActionError(f"unknown ability {ability_id!r}")

    @staticmethod
    def _support(me: _Side, ability: AbilitySpec, events: list) -> None:
        amount = math.floor(me.fighter.essence * ability.percentage / 100 + _EPS)  # unbuffed ESSENCE
        duration = ability.duration + me.passive.support_extra_rounds()
        me.buffs = [b for b in me.buffs if b.source != ability.id]  # reuse refreshes, never stacks
        me.buffs.append(Buff(ability.id, ability.stat, amount, duration))
        events.append({"type": "support", "side": me.side, "ability": ability.id, "stat": ability.stat, "amount": amount})

    @staticmethod
    def _defense(me: _Side, ability: AbilitySpec, events: list) -> None:
        rating = me.stat("essence") * ability.percentage / 100 + me.passive.defense_rating_bonus(me.fighter.essence)
        attacks, rounds = me.passive.defense_limits()
        if me.defense:
            rating = max(rating, me.defense.rating)  # overlapping defenses keep the strongest rating
        me.defense = DefenseEffect(rating, attacks, rounds)  # refresh resets the limits, nothing is banked
        events.append({"type": "defense", "side": me.side, "ability": ability.id, "rating": round(rating, 2)})

    @staticmethod
    def _flee(me: _Side, catcher_essence: int | None) -> float:
        essence = me.stat("essence")
        chance = essence / (100 + essence) * me.hp / me.fighter.max_hp
        return chance * 100 / (100 + catcher_essence) if catcher_essence is not None else chance

    @staticmethod
    def _attack(sides: dict[str, _Side], actions: dict[str, Action], attacker: str, events: list) -> str | None:
        me, foe = sides[attacker], sides[other(attacker)]
        essence = me.stat("essence")
        raw = essence * actions[attacker].percentage / 100 + me.passive.attack_bonus(
            essence, me.hp, me.fighter.max_hp, actions[foe.side].category == "DEFENSE"
        )
        protected = bool(foe.defense and foe.defense.attacks_left > 0)
        if protected:
            damage = math.floor(raw * 100 / (100 + foe.defense.rating) + _EPS)
            foe.defense = replace(foe.defense, attacks_left=foe.defense.attacks_left - 1)
        else:
            damage = math.floor(raw + _EPS)
        damage = max(1, damage)
        foe.hp = max(0, foe.hp - damage)
        events.append({"type": "attack", "side": attacker, "damage": damage, "protected": protected, "target_hp": foe.hp})
        if foe.hp == 0:
            return "won" if foe.side == WILD else "knocked_out"
        return None

    def _catch(self, setup: BattleSetup, sides: dict[str, _Side], actions: dict[str, Action], catcher: str,
               rec: RecordingRandom, events: list) -> tuple[str | None, str | None]:
        foe = other(catcher)
        if actions[foe].kind == "flee":  # already counted against the escape; no collection, no EMBLEM
            return None, None
        if catcher == WILD:
            events.append({"type": "catch_ignored", "side": WILD})
            return None, None
        tier = actions[catcher].emblem_tier
        chance = self.capture_chance(tier, setup.of(foe), sides[foe].freeze())
        succeeded = rec.next() < chance
        events.append({"type": "capture_attempt", "side": catcher, "emblem": tier, "chance": round(chance, 4), "success": succeeded})
        return ("captured" if succeeded else None), tier

    @staticmethod
    def _expire(me: _Side) -> None:
        me.buffs = [replace(b, rounds_left=b.rounds_left - 1) if b.rounds_left is not None else b for b in me.buffs]
        me.buffs = [b for b in me.buffs if b.rounds_left is None or b.rounds_left > 0]
        if me.defense:
            left = replace(me.defense, rounds_left=me.defense.rounds_left - 1)
            me.defense = left if left.rounds_left > 0 and left.attacks_left > 0 else None
