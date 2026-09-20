"""One tracked server process: launch, log capture, stop/restart."""

from __future__ import annotations

import collections
import datetime
import subprocess
import threading
import time
from typing import Callable

from .config import _POLL_MS, _RESTART_WAIT_SECONDS
from .models import ServerTemplate
from .processes import _ensure_venv, _kill_pid_tree, _pid_alive, _spawn


class _TimestampedLog(collections.deque):
    """Deque of log lines that prefixes each appended line with date and time."""

    def append(self, line: str) -> None:
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        super().append(f"[{stamp}] {line}")


class Instance:
    def __init__(
        self, template: ServerTemplate, port: int, extra_env: dict[str, str], extra_args: str,
        *, adopted_pid: int | None = None, preset_name: str | None = None,
    ) -> None:
        self.id = f"{template.key}:{port}:{int(time.time() * 1000)}"
        self.template = template
        self.port = port
        self.extra_env = extra_env
        self.extra_args = extra_args
        # An adopted process was not launched from this window, so it has no
        # trustworthy preset provenance. Self-started instances receive the
        # selected preset name from the server form instead.
        self.preset_name = preset_name
        self.log_lines: collections.deque[str] = _TimestampedLog(maxlen=4000)
        self.process: subprocess.Popen | None = None
        # Set only when this Instance wraps a process this window didn't
        # spawn itself (found already listening on a template's default
        # port at startup). There's no Popen handle for one of these, so
        # is_alive()/stop() fall back to a PID instead - see
        # _start_liveness_watcher() for why is_alive() never blocks.
        self._adopted_pid = adopted_pid
        self._adopted_alive = True
        # "running" | "stopping" | "exited" | "failed", plus "starting" as a
        # plain (uncolored, not notified) placeholder before the first real
        # transition - "initializing"/"restarting" as their own tracked,
        # colored states were removed: both were too short-lived to ever
        # reliably show up (venv-already-exists / a fast kill routinely
        # finished before a single redraw), so they never actually worked
        # as a visible feature. Every REAL transition runs through
        # _set_status() so on_status_change fires immediately (passed the
        # status string itself, not just a "something changed" ping) instead
        # of waiting for the next poll tick and re-reading self.status then,
        # which could land on a later status and skip the one just set.
        self.on_status_change: Callable[[str], None] | None = None
        # Bumped by _launch() so a stale reader thread from a launch that's
        # since been superseded (restart's OLD process finally hitting
        # stdout EOF after the NEW one from _launch() is already running)
        # can't clobber the current status back to "exited" - it only ever
        # applies a status if its own generation is still the current one.
        self._generation = 0
        if adopted_pid is not None:
            self.log_lines.append(
                f"--- adopted an already-running process on port {port} (PID {adopted_pid}) from "
                "a previous launcher session - log output from before this point is unavailable ---"
            )
            self._set_status("running")
            self._start_liveness_watcher()
        else:
            self.status = "starting"
            self._launch()

    def _set_status(self, status: str) -> None:
        self.status = status
        if self.on_status_change is not None:
            self.on_status_change(status)

    def _launch(self) -> None:
        self._generation += 1
        generation = self._generation
        threading.Thread(target=self._boot_and_run, args=(generation,), daemon=True).start()

    def _boot_and_run(self, generation: int) -> None:
        def set_status(status: str) -> None:
            if generation == self._generation:
                self._set_status(status)

        if not _ensure_venv(self.template, self.log_lines):
            set_status("failed")
            return
        set_status("running")
        process = _spawn(self.template, self.port, self.extra_env, self.extra_args)
        self.process = process
        try:
            for line in process.stdout:  # closes/ends when the process exits
                self.log_lines.append(line.rstrip("\n"))
        except (OSError, ValueError):
            pass
        set_status("exited")

    def _start_liveness_watcher(self) -> None:
        """Adopted instances have no Popen handle for a cheap poll() check -
        is_alive() would otherwise have to shell out (tasklist) every time
        it's called, INCLUDING from _tick() on the main thread every poll
        interval - that repeated blocking call is what froze the UI before.
        This background thread does the blocking check instead, on its own
        schedule, and is_alive() just reads the cached result - a plain
        attribute read, safe to call from anywhere including the UI thread."""
        def watch() -> None:
            while self.process is None and self._adopted_pid is not None:
                alive = _pid_alive(self._adopted_pid)
                self._adopted_alive = alive
                if not alive:
                    if self.process is None:  # nothing (e.g. restart) took over meanwhile
                        self._set_status("exited")
                    return
                time.sleep(_POLL_MS / 1000)

        threading.Thread(target=watch, daemon=True).start()

    def is_alive(self) -> bool:
        if self.process is not None:
            return self.process.poll() is None
        if self._adopted_pid is not None:
            return self._adopted_alive
        return False

    def stop(self) -> None:
        self._set_status("stopping")
        if self.process is not None:
            _kill_pid_tree(self.process.pid)
        elif self._adopted_pid is not None:
            _kill_pid_tree(self._adopted_pid)

    def restart(self) -> None:
        self.stop()  # status stays "stopping" through the wait below - no separate "restarting" state
        deadline = time.time() + _RESTART_WAIT_SECONDS
        while time.time() < deadline and self.is_alive():
            time.sleep(0.2)
        self.log_lines.append(f"--- restarting on port {self.port} ---")
        self._launch()
