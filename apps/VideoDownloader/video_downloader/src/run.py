"""video_downloader entry point: ``py -m src.run`` (see run.bat)."""

from __future__ import annotations

import sys

import uvicorn

from src.app import create_app
from src.config import load_settings
from src.errors import DownloaderError
from src.logging_setup import configure_logging
from src.system_info import require_ffmpeg

# On Ctrl+C uvicorn waits for open connections (SSE streams stay open) before the app
# shuts down. After this many seconds it closes them, so the lifespan can cancel running jobs.
GRACEFUL_SHUTDOWN_SECONDS = 5


def main() -> None:
    try:
        require_ffmpeg()
    except DownloaderError as error:
        print(f"video_downloader cannot start: {error.message}", file=sys.stderr)
        raise SystemExit(1) from None
    settings = load_settings()
    configure_logging(settings.log_dir)
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_SECONDS,
    )


if __name__ == "__main__":
    main()
