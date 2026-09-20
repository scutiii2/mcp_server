"""Port checks, PID lookup/kill and venv bootstrap + spawn helpers."""

from __future__ import annotations

import collections
import os
import shlex
import socket
import subprocess
from pathlib import Path

from .models import ServerTemplate


def _port_in_use(port: int) -> bool:
    # No SO_REUSEADDR here deliberately: on Windows it lets bind() succeed
    # even while another process is actively LISTENING on the port (unlike
    # Berkeley sockets, where it only relaxes TIME_WAIT) - with it set, this
    # check silently reported free ports that were actually taken.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return True
        return False


def _find_free_port(start_port: int) -> int:
    port = start_port
    while _port_in_use(port):
        port += 1
    return port


def _kill_pid_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)


def _find_pid_on_port(port: int) -> int | None:
    """Best-effort PID of whatever's LISTENING on 127.0.0.1:<port>, parsed
    from `netstat -ano` - used only for the one-time startup adoption scan
    (see LauncherWindow._adopt_running_instances()), never called
    repeatedly from the main thread."""
    result = subprocess.run(["netstat", "-ano"], capture_output=True, text=True)
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0] == "TCP" and parts[3] == "LISTENING" and parts[1].endswith(f":{port}"):
            try:
                return int(parts[-1])
            except ValueError:
                continue
    return None


def _pid_alive(pid: int) -> bool:
    """Shells out to `tasklist` - blocking, ~tens of ms. Only ever called
    from Instance's own background liveness-watcher thread for an adopted
    instance, never from the UI thread - see Instance._start_liveness_watcher().
    Calling this from _tick() every poll interval is what froze the app
    before; the watcher thread now does it instead, off-thread, and is_alive()
    just reads the cached result."""
    result = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True)
    return str(pid) in result.stdout


def _run_and_log(cmd: list[str], cwd: Path, log: collections.deque) -> int:
    """Runs `cmd` to completion, streaming its output into `log` line by
    line (same deque the server's own stdout lands in later) rather than
    waiting silently - a first-run venv-create + editable-install can
    take a while, and the Instances log view is the only place watching
    it happens."""
    proc = subprocess.Popen(
        cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    for line in proc.stdout:
        log.append(line.rstrip("\n"))
    return proc.wait()


def _ensure_venv(template: ServerTemplate, log: collections.deque) -> bool:
    """Creates `template.venv_python`'s venv and editable-installs the
    project into it if it isn't there yet - mirrors the same
    if-not-exist bootstrap block each run.bat carries for anyone running
    it directly instead of through this tool. Returns False on failure."""
    if template.venv_python.exists():
        return True
    venv_dir = template.venv_python.parent.parent
    log.append(f"Creating virtual environment {venv_dir.name} ...")
    if _run_and_log(["py", "-m", "venv", str(venv_dir)], template.working_dir, log) != 0:
        log.append("Failed to create the virtual environment.")
        return False
    log.append(f"Installing {template.working_dir.name} in editable mode ...")
    if _run_and_log([str(template.venv_python), "-m", "pip", "install", "-e", ".[dev]"], template.working_dir, log) != 0:
        log.append("Failed to install dependencies.")
        return False
    log.append("Virtual environment ready.")
    return True


def _build_launch_args(
    template: ServerTemplate, port: int, extra_env: dict[str, str], extra_args: str,
) -> tuple[list[str], dict[str, str]]:
    env = {**os.environ, template.port_env_var: str(port), **extra_env}
    cmd = [str(template.venv_python), "-m", template.module]
    if template.supports_args and extra_args.strip():
        cmd += shlex.split(extra_args.strip())
    return cmd, env


def _spawn(template: ServerTemplate, port: int, extra_env: dict[str, str], extra_args: str) -> subprocess.Popen:
    cmd, env = _build_launch_args(template, port, extra_env, extra_args)
    return subprocess.Popen(
        cmd,
        cwd=template.working_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def _spawn_detached(template: ServerTemplate, port: int, extra_env: dict[str, str], extra_args: str) -> None:
    """Like _spawn(), but with stdout/stderr discarded instead of piped, and
    no reader thread - used only when handing an instance off to survive
    this app's exit ("keep running in background"). Confirmed by testing: a
    piped Popen whose read end lives in this process, actively read by a
    background thread, reliably dies along with this process at interpreter
    shutdown (the reader thread gets torn down mid-syscall on the pipe). A
    process with no pipe tied to us at all has no such dependency and
    survives fine - the trade-off is losing its log history once handed off
    this way, which is unavoidable since nothing would be left to read it."""
    cmd, env = _build_launch_args(template, port, extra_env, extra_args)
    subprocess.Popen(
        cmd,
        cwd=template.working_dir,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
