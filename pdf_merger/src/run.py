"""pdf_merger entry point: ``py -m src.run`` (see run.bat)."""

from __future__ import annotations

import uvicorn

from src.app import create_app
from src.config import load_settings
from src.logging_setup import configure_logging


def main() -> None:
    settings = load_settings()
    configure_logging(settings.log_dir)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
