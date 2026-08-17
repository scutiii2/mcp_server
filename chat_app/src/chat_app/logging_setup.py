"""Wires Python logging to disk. Called once, from run.py.

Deliberately not called from app.py's create_app(): tests construct a
fresh app per test case (see tests/conftest.py), and attaching handlers
there would pile up duplicate handlers across a test run and scatter log
files into whatever the test process's CWD happens to be.

Attaches a file handler to the *root* logger, not just chat_app's own -
so this also captures Flask/Werkzeug's request logs, not only the
exceptions errors.report() logs. A StreamHandler is attached alongside
it because adding any handler to the root logger suppresses Python's
"lastResort" handler, which is what prints to stderr when a logger has
no handlers configured - without this, running the app in a terminal
would go silent on the console the moment file logging was added.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_MAX_BYTES = 5_000_000
_BACKUP_COUNT = 3
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(_FORMAT)

    file_handler = RotatingFileHandler(
        log_dir / "server.log", maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)
