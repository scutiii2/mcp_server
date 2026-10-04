"""Execute client state/DOM regressions when the development Node runtime exists."""

from pathlib import Path
import shutil
import subprocess

import pytest


def test_chat_client_behavior():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the browser behavior tests")
    result = subprocess.run(
        [node, str(Path(__file__).with_name("chat_client.test.cjs"))],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
