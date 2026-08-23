from __future__ import annotations

import logging

from src.logging_setup import configure_logging


def test_configure_logging_creates_a_rotating_file_and_writes_to_it(tmp_path):
    log_dir = tmp_path / "logs"
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    try:
        configure_logging(log_dir)
        logging.getLogger("mcp_server").info("hello from a test")

        log_file = log_dir / "server.log"
        assert log_file.exists()
        assert "hello from a test" in log_file.read_text(encoding="utf-8")
    finally:
        root.handlers[:] = original_handlers
        root.setLevel(original_level)
