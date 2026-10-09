"""Exercise the startup guard across real processes without opening GUI windows."""

import subprocess
import sys
from pathlib import Path

import pytest


APP_DIR = Path(__file__).resolve().parents[1]
STARTUP = """
import sys
from src import run

# Replace only GUI and user-data operations; run the real startup and OS lock.
run._hide_console_window = lambda: None
run._migrate_legacy_data = lambda: print('migration', flush=True)
class Root:
    def mainloop(self):
        print('running', flush=True)
        sys.stdin.readline()
run.tk.Tk = Root
run.LauncherWindow = lambda root: None
run.main()
"""


@pytest.mark.parametrize("crash", [False, True], ids=["normal-exit", "crash"])
def test_second_launch_exits_before_startup_and_can_restart_after_exit(crash):
    first = subprocess.Popen(
        [sys.executable, "-u", "-c", STARTUP], cwd=APP_DIR,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert first.stdout.readline().strip() == "migration"
        assert first.stdout.readline().strip() == "running"
        second = subprocess.run(
            [sys.executable, "-u", "-c", STARTUP], cwd=APP_DIR,
            input="\n", capture_output=True, text=True, timeout=10,
        )
        assert second.returncode == 0, second.stderr
        assert second.stdout == "", "Duplicate launcher performed startup operations"
    finally:
        if crash:
            first.kill()
        first.communicate(input=None if crash else "\n", timeout=10)

    restarted = subprocess.run(
        [sys.executable, "-u", "-c", STARTUP], cwd=APP_DIR,
        input="\n", capture_output=True, text=True, timeout=10,
    )
    assert restarted.returncode == 0, restarted.stderr
    assert restarted.stdout.splitlines() == ["migration", "running"]
