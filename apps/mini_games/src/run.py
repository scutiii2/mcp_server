"""Start the mini_games backend: `python -m src.run`."""

from __future__ import annotations

import logging

import uvicorn
from fastapi import FastAPI

from src.app import create_app
from src.auth import load_token
from src.config import AppConfig, load_config
from src.laya_client import LayaClient
from src.ascension.api import mount_ascendeds
from src.ascension.composition import build_ascended_services

log = logging.getLogger("mini_games")


def build_app() -> tuple[FastAPI, AppConfig]:
    config = load_config()
    laya = LayaClient(timeout=config.laya_timeout_seconds, min_confidence=config.laya_min_confidence)
    if laya.is_available():
        try:
            laya.prepare()
            log.info("Laya loaded")
        except Exception as error:  # any load failure (missing weights, OSError, ...) degrades to heuristics
            log.warning("Laya could not be loaded; game decisions will use heuristics: %s", error)
    else:
        log.info("Laya is not installed; game decisions will use heuristics")
    token = load_token()
    if not token:
        log.warning("INTERNAL_API_TOKEN is empty; the API is unauthenticated")
    app = create_app(token)
    mount_ascendeds(app, build_ascended_services(config, laya))
    return app, config


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app, config = build_app()
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    main()
