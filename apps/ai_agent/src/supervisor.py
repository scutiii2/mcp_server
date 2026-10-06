"""Starts every agent in ai_agent/agents/ as its own `python -m src.server`
child process and keeps them running.

run.bat runs this module, so server_launcher still sees one ai_agent
instance. All agent files are validated before any child starts. Each
child's output is relayed line by line as "[<agent id>] ...". A child that
exits on its own is deregistered (it could not clean up after itself),
then restarted with backoff - 1s, 2s, 4s... up to 60s - until it has
crashed 5 times within 5 minutes, after which it is left stopped and the
others keep running.

Run with:
    python -m src.supervisor
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import time
from pathlib import Path
from typing import Awaitable, Callable, Sequence

from src.agents import agent_registry, agent_spec
from src.agents.agent_spec import AgentSpec

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MAX_CRASHES = 5
CRASH_WINDOW_SECONDS = 300.0
BACKOFF_CAP_SECONDS = 60.0
STOP_GRACE_SECONDS = 10.0
LINE_LIMIT = 1024 * 1024  # longest child output line relayed whole

CommandFor = Callable[[AgentSpec], Sequence[str]]
Deregister = Callable[[str], None]
Out = Callable[[str], None]
Sleep = Callable[[float], Awaitable[None]]


def _print(line: str) -> None:
    print(line, flush=True)


def default_command(spec: AgentSpec) -> list[str]:
    return [sys.executable, "-m", "src.server"]


def child_env(spec: AgentSpec) -> dict[str, str]:
    env = dict(os.environ)
    env["AI_AGENT_FILE"] = str(spec.source)
    env["AI_AGENT_PORT"] = str(spec.port)
    env["PYTHONUNBUFFERED"] = "1"  # relay output as it happens, not per 8 KB block
    return env


class CrashPolicy:
    """Backoff for one child: record() a crash, get the delay before the
    restart, or None once it has crashed max_crashes times in `window`."""

    def __init__(
        self,
        max_crashes: int = MAX_CRASHES,
        window: float = CRASH_WINDOW_SECONDS,
        base: float = 1.0,
        cap: float = BACKOFF_CAP_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_crashes
        self._window = window
        self._base = base
        self._cap = cap
        self._clock = clock
        self._crashes: list[float] = []

    def record(self) -> float | None:
        now = self._clock()
        self._crashes = [t for t in self._crashes if now - t < self._window]
        self._crashes.append(now)
        if len(self._crashes) >= self._max:
            return None
        return min(self._base * 2 ** (len(self._crashes) - 1), self._cap)


class AgentProcess:
    """One agent's child process: start it, relay its output, restart it."""

    def __init__(
        self, spec: AgentSpec, command_for: CommandFor, deregister: Deregister, out: Out,
        policy: CrashPolicy, sleep: Sleep,
    ) -> None:
        self.spec = spec
        self.failed = False
        self._command_for = command_for
        self._deregister = deregister
        self._out = out
        self._policy = policy
        self._sleep = sleep
        self._proc: asyncio.subprocess.Process | None = None
        self._stopping = False

    async def run(self) -> None:
        while not self._stopping:
            try:
                code = await self._run_once()
                if self._stopping:
                    return
                await asyncio.to_thread(self._deregister, self.spec.id)
                what = f"exited with code {code}"
            except Exception as error:  # this child only; the others keep running
                if self._stopping:
                    return
                self._out(f"[supervisor] {self.spec.id} failed: {error}")
                what = "failed"
            delay = self._policy.record()
            if delay is None:
                self.failed = True
                self._out(f"[supervisor] {self.spec.id} crashed {MAX_CRASHES} times in 5 minutes - not restarting")
                return
            self._out(f"[supervisor] {self.spec.id} {what} - restarting in {delay:g}s")
            await self._sleep(delay)

    async def _run_once(self) -> int | None:
        proc = await asyncio.create_subprocess_exec(
            *self._command_for(self.spec),
            cwd=PROJECT_ROOT,
            env=child_env(self.spec),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            limit=LINE_LIMIT,
        )
        self._proc = proc
        if self._stopping:  # stop() ran while the spawn was in flight
            await self._terminate(proc, STOP_GRACE_SECONDS)
            return proc.returncode
        await self._relay()
        return await proc.wait()

    def _emit(self, raw: bytes) -> None:
        too_long = len(raw) > LINE_LIMIT
        text = raw[:LINE_LIMIT].decode(errors="replace").rstrip()
        self._out(f"[{self.spec.id}] {text}")
        if too_long:
            self._out(f"[{self.spec.id}] <line too long, truncated>")

    async def _relay(self) -> None:
        """Relay output line by line; a line longer than LINE_LIMIT is cut
        (with a notice) instead of crashing the reader."""
        assert self._proc is not None and self._proc.stdout is not None
        stream = self._proc.stdout
        buf = b""
        skipping = False  # inside the tail of an over-long line
        while True:
            chunk = await stream.read(65536)
            if not chunk:
                break
            buf += chunk
            while (i := buf.find(b"\n")) >= 0:
                line, buf = buf[:i], buf[i + 1:]
                if skipping:
                    skipping = False
                else:
                    self._emit(line)
            if len(buf) > LINE_LIMIT:
                if not skipping:
                    self._emit(buf)
                    skipping = True
                buf = b""
        if buf and not skipping:
            self._emit(buf)

    async def stop(self, grace: float = STOP_GRACE_SECONDS) -> None:
        self._stopping = True
        proc = self._proc
        if proc is None or proc.returncode is not None:
            return
        await self._terminate(proc, grace)

    @staticmethod
    async def _terminate(proc: asyncio.subprocess.Process, grace: float) -> None:
        with contextlib.suppress(ProcessLookupError):
            proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), grace)
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()


class Supervisor:
    def __init__(
        self,
        specs: list[AgentSpec],
        command_for: CommandFor = default_command,
        deregister: Deregister = agent_registry.deregister,
        out: Out = _print,
        policy_factory: Callable[[], CrashPolicy] = CrashPolicy,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._specs = specs
        self._deregister = deregister
        self._out = out
        self._children = [
            AgentProcess(spec, command_for, deregister, out, policy_factory(), sleep)
            for spec in specs if spec.enabled
        ]

    async def run(self) -> None:
        # Entries a crashed earlier run left behind for OUR agents only.
        for spec in self._specs:
            await asyncio.to_thread(self._deregister, spec.id)
        self._out(f"[supervisor] starting {', '.join(c.spec.id for c in self._children) or 'no agents'}")
        try:
            await asyncio.gather(*(child.run() for child in self._children))
        finally:
            await self.stop()
        if self._children and all(child.failed for child in self._children):
            self._out("[supervisor] every agent failed - exiting")

    async def stop(self) -> None:
        await asyncio.gather(*(child.stop() for child in self._children))
        # Children deregister on a clean exit; a terminated one cannot.
        for child in self._children:
            await asyncio.to_thread(self._deregister, child.spec.id)


def main() -> None:
    try:
        specs = agent_spec.load_dir(agent_spec.AGENTS_DIR)
    except agent_spec.AgentSpecError as error:
        sys.stderr.write(f"\nai_agent cannot start - agent file error:\n  {error}\n\n")
        sys.exit(1)
    try:
        asyncio.run(Supervisor(specs).run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
