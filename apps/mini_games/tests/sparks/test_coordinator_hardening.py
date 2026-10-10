import asyncio

import pytest

import src.sparks.coordinator as coordinator_module
from src.sparks.models import PersonalityInstance
from src.sparks.records import EncounterRecord, SparkRecord
from tests.sparks.env import Env, run
from tests.sparks.helpers import ScriptedPolicy
from tests.sparks.test_coordinator import advance, begin, encounter, strong_guardian


@pytest.fixture(autouse=True)
def fixed_seed(monkeypatch):
    monkeypatch.setattr(coordinator_module, "new_seed", lambda: 7)


class Picker:
    def __init__(self, behaviour):
        self.behaviour = behaviour

    async def pick(self, view, chances):
        return await self.behaviour(chances)


async def prompt_battle(tmp_path, picker, emblems=None):
    env = Env(tmp_path / "s.sqlite3")
    await env.start_player()
    await strong_guardian(env)
    async with env.repo.transaction() as tx:
        for tier, count in (emblems or {"rare": 2}).items():
            await tx.add_emblems("ann", tier, count)
    coord = env.coordinator(ScriptedPolicy(player=["catch"], wild=["attack"]), picker=picker)
    view = await begin(env, coord, mode="autonomous", limit="rare", species="channeler", tier="normal", level=1)
    prompt = await advance(coord, env, view)
    env.clock.advance(6)
    return env, coord, prompt


def test_concurrent_identical_requests_replay_the_stored_response(tmp_path):
    async def scenario():
        env = Env(tmp_path / "s.sqlite3")
        await env.start_player()
        coord = env.coordinator(ScriptedPolicy(player=["attack"] * 3, wild=["attack"] * 3))
        view = await begin(env, coord)
        key = env.key()
        call = lambda: coord.submit_action("ann", key, view["id"], round=view["round"], revision=view["revision"], action={"kind": "attack"})
        first, second = await asyncio.gather(call(), call())
        await env.close()
        return first, second

    first, second = run(scenario())
    assert first == second


def test_concurrent_advance_with_one_key_replays(tmp_path):
    async def scenario():
        env = Env(tmp_path / "s.sqlite3")
        await env.start_player()
        coord = env.coordinator(ScriptedPolicy(player=["attack"] * 3, wild=["attack"] * 3))
        view = await begin(env, coord, mode="autonomous", limit="normal")
        key = env.key()
        call = lambda: coord.advance("ann", key, view["id"], round=view["round"], revision=view["revision"])
        results = await asyncio.gather(call(), call())
        await env.close()
        return results

    first, second = run(scenario())
    assert first == second


def test_a_failing_picker_means_basic_attack(tmp_path):
    async def boom(chances):
        raise RuntimeError("model exploded")

    async def scenario():
        env, coord, prompt = await prompt_battle(tmp_path, Picker(boom))
        done = await advance(coord, env, prompt)
        await env.close()
        return done

    done = run(scenario())
    assert done["history"][0]["actions"]["player"][0] == "attack"


def test_emblems_vanishing_between_read_and_commit_fall_back_to_attack(tmp_path):
    async def scenario():
        env = None

        async def pick_then_lose(chances):
            async with env.repo.transaction() as tx:
                await tx.add_emblems("ann", "rare", -2)  # spent elsewhere after the counts were read
            return "rare"

        env, coord, prompt = await prompt_battle(tmp_path, Picker(pick_then_lose))
        done = await advance(coord, env, prompt)
        async with env.repo.transaction() as tx:
            counts = await tx.emblem_counts("ann")
        await env.close()
        return done, counts

    done, counts = run(scenario())
    assert done["history"][0]["actions"]["player"][0] == "attack" and "rare" not in counts


def test_lock_entries_are_dropped_when_a_battle_ends(tmp_path):
    async def scenario():
        env = Env(tmp_path / "s.sqlite3")
        await env.start_player()
        coord = env.coordinator(ScriptedPolicy(player=["attack"], wild=["attack"]))
        view = await begin(env, coord)
        after_start = len(coord._locks)
        done = await coord.forfeit("ann", env.key(), view["id"])
        await env.close()
        return after_start, done, coord

    after_start, done, coord = run(scenario())
    assert done["status"] == "terminal" and coord._locks == {}
