import asyncio
import json

import pytest

import src.sparks.coordinator as coordinator_module
from src.sparks.errors import (
    ActiveBattleExists,
    BattleFinished,
    DeadlinePassed,
    IdempotencyConflict,
    InsufficientEmblems,
    InvalidRequest,
    NotFound,
    SparkFainted,
    StaleBattle,
    WrongPhase,
)
from src.sparks.models import PersonalityInstance
from src.sparks.records import EncounterRecord, SparkRecord
from tests.sparks.env import Env, run
from tests.sparks.helpers import ScriptedPolicy

COWARD = PersonalityInstance("wild-secret-1", "COWARD", 2)
BOLD = PersonalityInstance("wild-secret-2", "BOLD", 3)
SECRET_WORDS = ("COWARD", "BOLD", "wild-secret-1", "wild-secret-2")  # hidden wild personalities; ids that cannot occur by chance


@pytest.fixture(autouse=True)
def fixed_seed(monkeypatch):
    monkeypatch.setattr(coordinator_module, "new_seed", lambda: 7)


def make(tmp_path, **kwargs):
    return Env(tmp_path / "s.sqlite3", **kwargs)


async def encounter(env, spark_id="scout", tier="common", level=1, instances=(COWARD, BOLD), eid="e1", owner="ann"):
    async with env.repo.transaction() as tx:
        await tx.add_encounter(EncounterRecord(eid, owner, spark_id, tier, level, "pending", tuple(instances), env.clock.now()))
    return eid


async def strong_guardian(env, copies=250, level=30):
    await env.give(guardian=SparkRecord("ann", "guardian", copies, level, 0))


async def begin(env, coord, mode="manual", eid=None, slot=1, limit=None, **enc):
    eid = eid or await encounter(env, **enc)
    return await coord.start("ann", env.key(), encounter_id=eid, spark_id="guardian", preset_slot=slot,
                             mode=mode, emblem_limit=limit)


def act(coord, env, view, kind="attack", **extra):
    return coord.submit_action("ann", env.key(), view["id"], round=view["round"], revision=view["revision"],
                               action={"kind": kind, **extra})


def advance(coord, env, view):
    return coord.advance("ann", env.key(), view["id"], round=view["round"], revision=view["revision"])


async def stats(env):
    async with env.repo.transaction() as tx:
        return (await tx.get_player("ann")).insignia, await tx.emblem_counts("ann"), {s.spark_id: s for s in await tx.list_sparks("ann")}


# -- starting ------------------------------------------------------------------------

def test_start_creates_a_public_view_and_marks_the_encounter(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        view = await begin(env, env.coordinator())
        async with env.repo.transaction() as tx:
            enc = await tx.get_encounter("ann", "e1")
            active = (await tx.active_battle("ann")).id
        await env.close()
        return view, enc, active

    view, enc, active = run(scenario())
    assert (view["status"], view["phase"], view["mode"], view["round"], view["revision"]) == ("active", "choosing", "manual", 1, 1)
    assert enc.status == "started" and active == view["id"]
    assert view["player"]["spark_id"] == "guardian" and view["wild"]["spark_id"] == "scout"
    assert {"attack", "flee", "catch"} <= {a["kind"] for a in view["actions"]}
    assert not any(word in json.dumps(view) for word in SECRET_WORDS)


def test_start_validates_its_inputs(tmp_path):
    async def scenario():
        env = make(tmp_path)
        coord = env.coordinator()
        await env.start_player()
        eid = await encounter(env)
        base = dict(encounter_id=eid, spark_id="guardian", preset_slot=1, mode="manual", emblem_limit=None)
        for bad in (dict(mode="turbo"), dict(mode="autonomous", emblem_limit=None), dict(mode="autonomous", preset_slot=None, emblem_limit="common"),
                    dict(emblem_limit="gold"), dict(spark_id="nope")):
            with pytest.raises(InvalidRequest):
                await coord.start("ann", env.key(), **{**base, **bad})
        with pytest.raises(NotFound):
            await coord.start("ann", env.key(), **{**base, "encounter_id": "nope"})
        with pytest.raises(NotFound):
            await coord.start("ann", env.key(), **{**base, "spark_id": "scout"})  # not owned
        await env.close()

    run(scenario())


def test_an_empty_preset_cannot_play_autonomously_but_can_play_manually(tmp_path):
    async def scenario():
        env = make(tmp_path)
        coord = env.coordinator()
        await env.start_player()
        eid = await encounter(env)
        with pytest.raises(InvalidRequest, match="no personalities"):
            await coord.start("ann", env.key(), encounter_id=eid, spark_id="guardian", preset_slot=2, mode="autonomous", emblem_limit="common")
        view = await coord.start("ann", env.key(), encounter_id=eid, spark_id="guardian", preset_slot=2, mode="manual", emblem_limit=None)
        await env.close()
        return view

    assert run(scenario())["mode"] == "manual"


def test_a_fainted_spark_cannot_start_a_battle(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        await env.give(guardian=SparkRecord("ann", "guardian", 0, 1, 0, faint_until=env.clock.now() + 100))
        with pytest.raises(SparkFainted):
            await begin(env, env.coordinator())
        env.clock.advance(101)
        view = await begin(env, env.coordinator(), eid="e1")
        await env.close()
        return view

    assert run(scenario())["status"] == "active"


def test_one_active_battle_at_a_time_and_encounters_are_single_use(tmp_path):
    async def scenario():
        env = make(tmp_path)
        coord = env.coordinator()
        await env.start_player()
        await begin(env, coord)
        second = await encounter(env, eid="e2")
        with pytest.raises(ActiveBattleExists):
            await begin(env, coord, eid=second)
        with pytest.raises(WrongPhase):
            await begin(env, coord, eid="e1")  # e1 was already used
        await env.close()

    run(scenario())


def test_the_preset_is_frozen_for_the_battle(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        coord = env.coordinator()
        view = await begin(env, coord, mode="autonomous", limit="common")
        await env.collection.put_preset("ann", env.key(), "guardian", 1, [])  # edited after the fight began
        record, _ = await coord._load("ann", view["id"])
        await env.close()
        return record

    assert len(run(scenario()).player_personalities) == 1


# -- manual rounds -------------------------------------------------------------------

def test_a_manual_round_resolves_and_advances_the_checkpoint(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        coord = env.coordinator(ScriptedPolicy(wild=["flee"]))
        view = await begin(env, coord)
        after = await act(coord, env, view)
        await env.close()
        return view, after

    view, after = run(scenario())
    assert (after["round"], after["revision"], after["phase"]) in {(2, 2, "choosing"), (1, 2, "terminal")}
    assert len(after["history"]) == 1 and after["history"][0]["actions"]["player"] == ["attack", "ATTACK"]
    assert not any(word in json.dumps(after) for word in SECRET_WORDS)


def test_stale_round_or_revision_is_a_conflict(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        coord = env.coordinator(ScriptedPolicy(wild=["flee"] * 5))
        view = await begin(env, coord)
        await act(coord, env, view)
        for round_, revision in ((view["round"], view["revision"]), (view["round"] + 5, view["revision"] + 1)):
            with pytest.raises(StaleBattle):
                await coord.submit_action("ann", env.key(), view["id"], round=round_, revision=revision, action={"kind": "attack"})
        await env.close()

    run(scenario())


def test_a_retry_with_the_same_key_returns_the_first_result_and_applies_once(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        coord = env.coordinator(ScriptedPolicy(wild=["flee"] * 3))
        view = await begin(env, coord)
        first = await coord.submit_action("ann", "same", view["id"], round=1, revision=1, action={"kind": "attack"})
        again = await coord.submit_action("ann", "same", view["id"], round=1, revision=1, action={"kind": "attack"})
        with pytest.raises(IdempotencyConflict):
            await coord.submit_action("ann", "same", view["id"], round=1, revision=1, action={"kind": "flee"})
        await env.close()
        return first, again

    first, again = run(scenario())
    assert first == again and len(first["history"]) == 1


@pytest.mark.parametrize("action", [{"kind": "dance"}, {"kind": "ability", "ability_id": "nope"}, {"kind": "catch"}, {"kind": "catch", "emblem_tier": "gold"}])
def test_illegal_manual_actions_are_rejected_without_changing_the_battle(tmp_path, action):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        coord = env.coordinator()
        view = await begin(env, coord)
        with pytest.raises(InvalidRequest):
            await coord.submit_action("ann", env.key(), view["id"], round=1, revision=1, action=action)
        after = await coord.view("ann", view["id"])
        await env.close()
        return view, after

    view, after = run(scenario())
    assert after == view


def test_catching_needs_an_emblem_of_that_tier(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        coord = env.coordinator()
        view = await begin(env, coord)
        with pytest.raises(InsufficientEmblems):
            await act(coord, env, view, "catch", emblem_tier="rare")
        await env.close()

    run(scenario())


def test_an_ability_on_cooldown_is_not_offered_again(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        coord = env.coordinator(ScriptedPolicy(wild=["flee"] * 5))
        view = await begin(env, coord)
        after = await act(coord, env, view, "ability", ability_id="guardian_bulwark")
        offered = [a.get("ability_id") for a in after["actions"]]
        with pytest.raises(InvalidRequest):
            await act(coord, env, after, "ability", ability_id="guardian_bulwark")
        await env.close()
        return offered

    assert "guardian_bulwark" not in run(scenario())


def test_the_wild_decision_cannot_depend_on_the_players_action(tmp_path):
    async def one(kind):
        env = Env(tmp_path / f"{kind}.sqlite3")
        await env.start_player()
        policy = ScriptedPolicy()
        coord = env.coordinator(policy)
        view = await begin(env, coord)
        views_seen = []
        original = coord._decider._reader.read

        async def spy(situation_view):
            views_seen.append(situation_view)
            return await original(situation_view)

        coord._decider._reader.read = spy
        await act(coord, env, view, kind)
        await env.close()
        return views_seen, [c for c in policy.contexts if not c.collector]

    attack_views, attack_ctx = run(one("attack"))
    flee_views, flee_ctx = run(one("flee"))
    assert attack_views == flee_views and attack_ctx == flee_ctx  # identical inputs whatever the player chose


# -- endings -------------------------------------------------------------------------

def test_a_win_pays_out_exactly_once(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        await strong_guardian(env)
        coord = env.coordinator(ScriptedPolicy(wild=["flee"]))
        view = await begin(env, coord, level=1)
        done = await coord.submit_action("ann", "win", view["id"], round=1, revision=1, action={"kind": "attack"})
        replay = await coord.submit_action("ann", "win", view["id"], round=1, revision=1, action={"kind": "attack"})
        with pytest.raises(BattleFinished):
            await act(coord, env, view)
        after = await stats(env)
        await env.close()
        return done, replay, after

    done, replay, (insignia, emblems, sparks) = run(scenario())
    assert done == replay and done["status"] == "terminal" and done["result"]["kind"] == "won"
    assert insignia == 10 and done["result"]["xp"] == 20 and sparks["guardian"].faint_until is None and emblems == {"common": 5}


def test_a_knockout_faints_the_fighter_for_five_minutes_without_copy_loss(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        await env.give(guardian=SparkRecord("ann", "guardian", 3, 1, 0))
        coord = env.coordinator(ScriptedPolicy())
        view = await begin(env, coord, spark_id="forbidden", tier="forbidden", level=50)
        done = await act(coord, env, view)
        while done["status"] == "active":
            done = await act(coord, env, done)
        sparks = (await stats(env))[2]
        await env.close()
        return done, sparks["guardian"], env.clock.now()

    done, guardian, now = run(scenario())
    assert done["result"]["kind"] == "knocked_out" and guardian.copies == 3 and guardian.faint_until == now + 300


def test_a_successful_escape_ends_without_rewards_or_fainting(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        await strong_guardian(env)
        coord = env.coordinator(ScriptedPolicy(wild=["catch"]))
        view = await begin(env, coord, level=1)
        outcome = None
        for _ in range(60):  # FLEE is a roll; keep trying until it lands
            outcome = await act(coord, env, view, "flee")
            if outcome["status"] == "terminal":
                break
            view = outcome
        sparks = (await stats(env))
        await env.close()
        return outcome, sparks

    outcome, (insignia, _, sparks) = run(scenario())
    assert outcome["result"] == {"kind": "escaped"} and insignia == 0 and sparks["guardian"].faint_until is None


def test_a_capture_reveals_every_source_personality_and_spends_the_emblem(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        await strong_guardian(env)
        async with env.repo.transaction() as tx:
            await tx.add_emblems("ann", "legendary", 40)
        coord = env.coordinator(ScriptedPolicy())  # the wild Spark only attacks, so nothing preempts the attempt
        view = await begin(env, coord, spark_id="channeler", level=1)
        outcome = view
        for _ in range(100):
            outcome = await act(coord, env, view, "catch", emblem_tier="legendary")
            if outcome["status"] == "terminal":
                break
            view = outcome
        after = await stats(env)
        async with env.repo.transaction() as tx:
            pool = await tx.list_personalities("ann", "channeler", 50, 0)
        await env.close()
        return outcome, after, pool

    outcome, (insignia, emblems, sparks), pool = run(scenario())
    result = outcome["result"]
    assert result["kind"] == "captured" and {p["type"] for p in result["revealed_personalities"]} == {"COWARD", "BOLD"}
    assert len(pool) == 1 and result["awarded_personality"]["type"] in {"COWARD", "BOLD"}
    assert sparks["channeler"].level == 1 and sparks["channeler"].copies == 1 and insignia == 10
    assert emblems["legendary"] == 40 - len(outcome["history"])  # one EMBLEM per attempt, win or lose


def test_a_failed_collection_attempt_still_costs_the_emblem(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        await strong_guardian(env)  # 1462 HP survives one hit from the level-50 Forbidden Spark
        coord = env.coordinator(ScriptedPolicy())
        view = await begin(env, coord, spark_id="forbidden", tier="forbidden", level=50)
        after = await act(coord, env, view, "catch", emblem_tier="common")  # 100 / (100 + 12800): about 0.8%
        counts = (await stats(env))[1]
        await env.close()
        return after, counts

    after, counts = run(scenario())
    assert counts == {"common": 4}
    assert after["status"] == "active" and after["result"] is None and len(after["history"]) == 1


def test_forfeit_ends_the_battle_as_a_loss_and_is_final(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        coord = env.coordinator()
        view = await begin(env, coord)
        done = await coord.forfeit("ann", "f1", view["id"])
        replay = await coord.forfeit("ann", "f1", view["id"])
        with pytest.raises(BattleFinished):
            await coord.forfeit("ann", "f2", view["id"])
        with pytest.raises(BattleFinished):
            await act(coord, env, view)
        sparks = (await stats(env))[2]
        profile = await env.collection.profile("ann")
        await env.close()
        return done, replay, sparks, profile, env.clock.now()

    done, replay, sparks, profile, now = run(scenario())
    assert done == replay and done["result"]["kind"] == "forfeited" and sparks["guardian"].faint_until == now + 300
    assert profile["active_battle"] is None


def test_forfeit_and_resolution_race_leaves_one_consistent_ending(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        await strong_guardian(env)
        coord = env.coordinator(ScriptedPolicy(wild=["flee"]))
        view = await begin(env, coord, level=1)
        results = await asyncio.gather(
            coord.submit_action("ann", "a", view["id"], round=1, revision=1, action={"kind": "attack"}),
            coord.forfeit("ann", "f", view["id"]),
            return_exceptions=True,
        )
        final = await coord.view("ann", view["id"])
        insignia, _, sparks = await stats(env)
        await env.close()
        return results, final, insignia, sparks["guardian"]

    results, final, insignia, guardian = run(scenario())
    kinds = {final["result"]["kind"]}
    assert kinds <= {"won", "forfeited"} and sum(isinstance(r, Exception) for r in results) == 1
    assert (final["result"]["kind"] == "won") == (insignia == 10) and (final["result"]["kind"] == "forfeited") == (guardian.faint_until is not None)


def test_other_owners_cannot_see_or_touch_a_battle(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player("ann")
        await env.start_player("bob")
        coord = env.coordinator()
        view = await begin(env, coord)
        with pytest.raises(NotFound):
            await coord.view("bob", view["id"])
        with pytest.raises(NotFound):
            await coord.submit_action("bob", "k", view["id"], round=1, revision=1, action={"kind": "attack"})
        with pytest.raises(NotFound):
            await coord.forfeit("bob", "k", view["id"])
        await env.close()

    run(scenario())


# -- autonomous rounds and the EMBLEM prompt -----------------------------------------

def test_an_autonomous_round_plays_without_input(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        coord = env.coordinator(ScriptedPolicy(player=["attack"], wild=["flee"]))
        view = await begin(env, coord, mode="autonomous", limit="common")
        with pytest.raises(WrongPhase):
            await act(coord, env, view)
        after = await advance(coord, env, view)
        await env.close()
        return after

    after = run(scenario())
    assert len(after["history"]) == 1 and after["history"][0]["actions"]["player"][0] == "attack"


def catch_battle(tmp_path, *, laya=None, emblems=None, limit="rare", reader_policy=None, kwargs=None):
    async def setup():
        env = Env(tmp_path / "s.sqlite3")
        await env.start_player()
        await strong_guardian(env)  # survives the wild attack, so the CATCH is never preempted
        async with env.repo.transaction() as tx:
            for tier, count in (emblems or {"rare": 2, "royal": 1}).items():
                await tx.add_emblems("ann", tier, count)
        coord = env.coordinator(ScriptedPolicy(player=["catch"], wild=["attack"]), laya=laya)
        view = await begin(env, coord, mode="autonomous", limit=limit, spark_id="channeler", tier="common", level=1)
        return env, coord, view

    return setup()


def test_an_autonomous_catch_opens_a_five_second_prompt(tmp_path):
    async def scenario():
        env, coord, view = await catch_battle(tmp_path)
        prompt = await advance(coord, env, view)
        again = await coord.advance("ann", env.key(), view["id"], round=1, revision=prompt["revision"])
        await env.close()
        return view, prompt, again

    view, prompt, again = run(scenario())
    assert prompt["phase"] == "awaiting_emblem" and prompt["prompt"]["seconds_left"] == 5.0
    assert prompt["prompt"]["permitted_tiers"] == ["common", "rare"] and prompt["history"] == []
    assert again == prompt  # still waiting for the player: nothing changes before the deadline
    assert not any(word in json.dumps(prompt) for word in SECRET_WORDS + ("wild_action",))


def test_the_player_can_answer_with_any_owned_emblem_even_above_the_limit(tmp_path):
    async def scenario():
        env, coord, view = await catch_battle(tmp_path)
        prompt = await advance(coord, env, view)
        env.clock.advance(2)
        done = await coord.answer_emblem("ann", env.key(), view["id"], round=1, revision=prompt["revision"], tier="royal")
        counts = (await stats(env))[1]
        await env.close()
        return done, counts

    done, counts = run(scenario())
    assert "royal" not in counts and done["history"][0]["actions"]["player"][0] == "catch"


def test_a_late_answer_is_refused(tmp_path):
    async def scenario():
        env, coord, view = await catch_battle(tmp_path)
        prompt = await advance(coord, env, view)
        env.clock.advance(5)
        with pytest.raises(DeadlinePassed):
            await coord.answer_emblem("ann", env.key(), view["id"], round=1, revision=prompt["revision"], tier="rare")
        counts = (await stats(env))[1]
        await env.close()
        return counts

    assert run(scenario()) == {"common": 5, "rare": 2, "royal": 1}


def test_an_answer_needs_an_owned_emblem(tmp_path):
    async def scenario():
        env, coord, view = await catch_battle(tmp_path)
        prompt = await advance(coord, env, view)
        with pytest.raises(InsufficientEmblems):
            await coord.answer_emblem("ann", env.key(), view["id"], round=1, revision=prompt["revision"], tier="legendary")
        await env.close()

    run(scenario())


def test_after_the_deadline_laya_picks_within_the_limit(tmp_path):
    async def scenario():
        env, coord, view = await catch_battle(tmp_path, laya=FakeEngineWith("rare"))
        prompt = await advance(coord, env, view)
        env.clock.advance(6)
        done = await advance(coord, env, prompt)
        counts = (await stats(env))[1]
        await env.close()
        return done, counts

    done, counts = run(scenario())
    assert done["history"][0]["actions"]["player"][0] == "catch" and counts["rare"] == 1 and counts["royal"] == 1


def FakeEngineWith(pick):
    from tests.fake_laya import FakeEngine

    return FakeEngine(pick=pick, confidence=0.95)


@pytest.mark.parametrize("laya_factory", [
    lambda: None,  # no Laya at all
    lambda: __import__("tests.fake_laya", fromlist=["FakeEngine"]).FakeEngine(confidence=0.3),  # uncertain
    lambda: __import__("tests.fake_laya", fromlist=["FakeEngine"]).FakeEngine(raw={"choice": {"choice": "gold", "probabilities": {}, "answer_confidence": 0.9}}),  # invalid
])
def test_when_laya_cannot_choose_the_catch_becomes_basic_attack_and_nothing_is_spent(tmp_path, laya_factory):
    async def scenario():
        env, coord, view = await catch_battle(tmp_path, laya=laya_factory())
        prompt = await advance(coord, env, view)
        env.clock.advance(6)
        done = await advance(coord, env, prompt)
        counts = (await stats(env))[1]
        await env.close()
        return done, counts

    done, counts = run(scenario())
    assert done["history"][0]["actions"]["player"] == ["attack", "ATTACK"] and counts == {"common": 5, "rare": 2, "royal": 1}


def test_with_no_permitted_emblem_at_the_deadline_it_falls_back_to_attack(tmp_path):
    async def scenario():
        env, coord, view = await catch_battle(tmp_path, emblems={"rare": 1}, limit="rare")
        prompt = await advance(coord, env, view)
        async with env.repo.transaction() as tx:  # the permitted EMBLEMs vanish while the prompt is open
            await tx.add_emblems("ann", "rare", -1)
            await tx.add_emblems("ann", "common", -5)
        env.clock.advance(6)
        done = await advance(coord, env, prompt)
        await env.close()
        return done

    assert run(scenario())["history"][0]["actions"]["player"][0] == "attack"


def test_an_open_prompt_survives_a_restart_and_keeps_its_deadline(tmp_path):
    async def first():
        env, coord, view = await catch_battle(tmp_path)
        prompt = await advance(coord, env, view)
        now = env.clock.now()
        await env.close()
        return prompt, now

    async def second(prompt, now, wait):
        env = Env(tmp_path / "s.sqlite3")
        env.clock.t = now + wait
        coord = env.coordinator(ScriptedPolicy(player=["flee"], wild=["flee"]))  # a rerolled choice would differ
        resumed = await coord.view("ann", prompt["id"])
        result = await coord.answer_emblem("ann", env.key(), prompt["id"], round=1, revision=prompt["revision"], tier="rare")
        await env.close()
        return resumed, result

    prompt, now = run(first())
    resumed, result = run(second(prompt, now, 3))
    assert resumed["prompt"]["seconds_left"] == pytest.approx(2.0) and result["history"][0]["actions"]["wild"][0] == "attack"  # the saved choice


def test_closing_the_view_pauses_a_battle_and_reopening_resumes_it(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        coord = env.coordinator(ScriptedPolicy(wild=["flee"] * 4))
        view = await begin(env, coord, mode="autonomous", limit="common")
        after = await advance(coord, env, view)
        await env.close()
        env2 = Env(tmp_path / "s.sqlite3")
        env2.clock.t = env.clock.now() + 3600  # an hour passes with nobody calling advance
        coord2 = env2.coordinator(ScriptedPolicy(wild=["flee"] * 4))
        resumed = await coord2.view("ann", after["id"])
        profile = await env2.collection.profile("ann")
        await env2.close()
        return after, resumed, profile

    after, resumed, profile = run(scenario())
    assert resumed == after and len(resumed["history"]) == 1 and profile["active_battle"] == after["id"]


# -- mode ----------------------------------------------------------------------------

def test_mode_can_be_switched_between_rounds_and_keeps_the_frozen_preset(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        coord = env.coordinator(ScriptedPolicy(wild=["flee"] * 4))
        view = await begin(env, coord)
        with pytest.raises(InvalidRequest, match="EMBLEM tier limit"):
            await coord.set_mode("ann", env.key(), view["id"], round=1, revision=1, mode="autonomous", emblem_limit=None)
        auto = await coord.set_mode("ann", env.key(), view["id"], round=1, revision=1, mode="autonomous", emblem_limit="rare")
        back = await coord.set_mode("ann", env.key(), view["id"], round=1, revision=auto["revision"], mode="manual", emblem_limit=None)
        with pytest.raises(InvalidRequest):
            await coord.set_mode("ann", env.key(), view["id"], round=1, revision=back["revision"], mode="turbo", emblem_limit=None)
        await env.close()
        return auto, back

    auto, back = run(scenario())
    assert (auto["mode"], auto["emblem_limit"], auto["revision"]) == ("autonomous", "rare", 2)
    assert (back["mode"], back["emblem_limit"]) == ("manual", "rare")


def test_mode_cannot_change_while_an_emblem_prompt_is_open(tmp_path):
    async def scenario():
        env, coord, view = await catch_battle(tmp_path)
        prompt = await advance(coord, env, view)
        with pytest.raises(WrongPhase):
            await coord.set_mode("ann", env.key(), view["id"], round=1, revision=prompt["revision"], mode="manual", emblem_limit=None)
        await env.close()

    run(scenario())


def test_a_battle_without_personalities_cannot_go_autonomous(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        coord = env.coordinator()
        view = await begin(env, coord, slot=2)  # an empty preset
        with pytest.raises(InvalidRequest):
            await coord.set_mode("ann", env.key(), view["id"], round=1, revision=1, mode="autonomous", emblem_limit="common")
        await env.close()

    run(scenario())


# -- recovery ------------------------------------------------------------------------

def test_a_restart_between_rounds_gives_the_same_battle_as_not_restarting(tmp_path):
    async def play(path, restart):
        env = Env(path / "s.sqlite3")
        await env.start_player()
        coord = env.coordinator()  # the real policy and situation reader, driven by the saved seed
        view = await begin(env, coord, mode="autonomous", limit="common", spark_id="sentinel", level=3)
        view = await advance(coord, env, view)
        if restart:
            await env.close()
            env = Env(path / "s.sqlite3")
            coord = env.coordinator()
        for _ in range(3):
            if view["status"] != "active":
                break
            view = await advance(coord, env, view)
        history = view["history"]
        await env.close()
        return history

    one = tmp_path / "one"
    two = tmp_path / "two"
    one.mkdir(), two.mkdir()
    assert run(play(one, restart=False)) == run(play(two, restart=True))
