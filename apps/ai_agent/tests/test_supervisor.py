"""supervisor.py tests with real (tiny) child processes: output is
prefixed, a crash deregisters and restarts with backoff, the fifth crash
in the window gives up, stop() ends children promptly, and leftover
registry entries for our own agents are cleared at start."""

from __future__ import annotations

import asyncio
import sys

from src import supervisor
from src.agents.agent_spec import AgentSpec, LlmSpec


def _spec(agent_id, port=9200, enabled=True, tmp_path=None):
    return AgentSpec(id=agent_id, label=agent_id, port=port, llm=LlmSpec(provider="anthropic"),
                     enabled=enabled, source=(tmp_path / f"{agent_id}.json") if tmp_path else None)


def test_crash_policy_backoff_and_give_up():
    now = [0.0]
    policy = supervisor.CrashPolicy(max_crashes=5, window=300.0, base=1.0, cap=4.0, clock=lambda: now[0])
    delays = [policy.record() for _ in range(4)]
    assert delays == [1.0, 2.0, 4.0, 4.0]
    assert policy.record() is None


def test_crash_policy_forgets_old_crashes():
    now = [0.0]
    policy = supervisor.CrashPolicy(max_crashes=2, window=10.0, clock=lambda: now[0])
    assert policy.record() == 1.0
    now[0] = 20.0
    assert policy.record() == 1.0


def test_child_env_points_at_the_agent_file(tmp_path):
    env = supervisor.child_env(_spec("calc", port=9103, tmp_path=tmp_path))
    assert env["AI_AGENT_FILE"] == str(tmp_path / "calc.json")
    assert env["AI_AGENT_PORT"] == "9103"
    assert env["PYTHONUNBUFFERED"] == "1"


def test_crashing_child_is_prefixed_deregistered_restarted_then_failed(tmp_path):
    lines, deregistered, sleeps = [], [], []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    sup = supervisor.Supervisor(
        [_spec("calc", tmp_path=tmp_path), _spec("off", enabled=False, tmp_path=tmp_path)],
        command_for=lambda spec: [sys.executable, "-c", "print('hello from child'); raise SystemExit(3)"],
        deregister=deregistered.append,
        out=lines.append,
        policy_factory=lambda: supervisor.CrashPolicy(max_crashes=2),
        sleep=fake_sleep,
    )

    asyncio.run(asyncio.wait_for(sup.run(), timeout=30))

    assert lines.count("[calc] hello from child") == 2
    assert any("restarting in 1s" in line for line in lines)
    assert any("not restarting" in line for line in lines)
    assert sleeps == [1.0]
    # start-up cleanup for both files, one crash before the restart, one
    # after the final crash, then the shutdown sweep.
    assert deregistered[:2] == ["calc", "off"]
    assert deregistered.count("calc") >= 3
    assert "off" not in deregistered[2:]


def test_stop_terminates_a_running_child_quickly(tmp_path):
    lines = []

    async def scenario():
        sup = supervisor.Supervisor(
            [_spec("calc", tmp_path=tmp_path)],
            command_for=lambda spec: [sys.executable, "-c", "import time; print('up', flush=True); time.sleep(60)"],
            deregister=lambda agent_id: None,
            out=lines.append,
        )
        task = asyncio.create_task(sup.run())
        for _ in range(200):
            if "[calc] up" in lines:
                break
            await asyncio.sleep(0.05)
        await sup.stop()
        await asyncio.wait_for(task, timeout=15)

    asyncio.run(scenario())
    assert "[calc] up" in lines


def test_overlong_output_line_is_truncated_and_supervisor_survives(tmp_path, monkeypatch):
    monkeypatch.setattr(supervisor, "LINE_LIMIT", 4096)
    lines = []
    code = "import sys; sys.stdout.write('x' * 200000 + '\\n'); print('after', flush=True)"
    sup = supervisor.Supervisor(
        [_spec("calc", tmp_path=tmp_path)],
        command_for=lambda spec: [sys.executable, "-c", code],
        deregister=lambda agent_id: None,
        out=lines.append,
        policy_factory=lambda: supervisor.CrashPolicy(max_crashes=1),
    )
    asyncio.run(asyncio.wait_for(sup.run(), timeout=30))
    assert "[calc] <line too long, truncated>" in lines
    assert "[calc] after" in lines
    assert not any(len(line) > 5000 for line in lines)


def test_spawn_failure_only_fails_that_child(tmp_path):
    lines, sleeps = [], []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    def command_for(spec):
        if spec.id == "broken":
            return [str(tmp_path / "no-such-executable")]
        return [sys.executable, "-c", "import time; print('up', flush=True); time.sleep(60)"]

    async def scenario():
        sup = supervisor.Supervisor(
            [_spec("broken", tmp_path=tmp_path), _spec("ok", tmp_path=tmp_path)],
            command_for=command_for,
            deregister=lambda agent_id: None,
            out=lines.append,
            policy_factory=lambda: supervisor.CrashPolicy(max_crashes=2),
            sleep=fake_sleep,
        )
        task = asyncio.create_task(sup.run())
        for _ in range(200):
            if "[ok] up" in lines and sup._children[0].failed:
                break
            await asyncio.sleep(0.05)
        assert not task.done()
        assert sup._children[0].failed
        assert not sup._children[1].failed
        await sup.stop()
        await asyncio.wait_for(task, timeout=15)

    asyncio.run(scenario())
    assert any(line.startswith("[supervisor] broken failed:") for line in lines)
    assert any("not restarting" in line for line in lines)
    assert sleeps == [1.0]


def test_stop_during_spawn_does_not_orphan_the_child(tmp_path):
    holder = []

    def command_for(spec):
        # stop() runs while create_subprocess_exec is still awaiting.
        asyncio.get_running_loop().create_task(holder[0].stop())
        return [sys.executable, "-c", "import time; time.sleep(60)"]

    async def scenario():
        child = supervisor.AgentProcess(
            _spec("calc", tmp_path=tmp_path), command_for, lambda agent_id: None,
            lambda line: None, supervisor.CrashPolicy(), asyncio.sleep,
        )
        holder.append(child)
        try:
            await asyncio.wait_for(child.run(), timeout=5)
        finally:
            if child._proc is not None and child._proc.returncode is None:
                child._proc.kill()
        return child

    child = asyncio.run(scenario())
    assert child._proc.returncode is not None


def test_start_publishes_every_defined_agent_including_disabled(tmp_path):
    published = []
    specs = [_spec("calc", tmp_path=tmp_path), _spec("off", enabled=False, tmp_path=tmp_path)]
    sup = supervisor.Supervisor(
        specs,
        command_for=lambda spec: [sys.executable, "-c", "pass"],
        deregister=lambda agent_id: None,
        out=lambda line: None,
        policy_factory=lambda: supervisor.CrashPolicy(max_crashes=1),
        sleep=lambda seconds: asyncio.sleep(0),
        publish=published.append,
    )

    asyncio.run(asyncio.wait_for(sup.run(), timeout=30))

    assert published == [specs]
