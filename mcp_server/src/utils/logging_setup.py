"""Wires Python logging to disk. Called once, from run.py's main().

Mirrors chat_app/src/utils/logging_setup.py - see that module's
docstring for the reasoning (root logger so uvicorn's own request/error
logs land here too; a StreamHandler alongside the file handler because
attaching any handler to the root logger suppresses Python's stderr
"lastResort" handler). Deliberately duplicated rather than shared: the
two apps live in separate venvs with no dependency between them (see
infra/app_config.py's docstring for the same convention elsewhere in
this repo).
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
