"""Start the mini_games backend: `python -m src.run`."""

from __future__ import annotations

import logging

import uvicorn
from fastapi import FastAPI

from src.app import create_app
from src.auth import load_token
from src.config import AppConfig, load_config
from src.laya_client import LayaClient, LayaError
from src.sparks.api import mount_sparks
from src.sparks.composition import build_spark_services

log = logging.getLogger("mini_games")


def build_app() -> tuple[FastAPI, AppConfig]:
    config = load_config()
    laya = LayaClient(timeout=config.laya_timeout_seconds, min_confidence=config.laya_min_confidence)
    if laya.is_available():
        try:
            laya.prepare()
            log.info("Laya loaded")
        except LayaError as error:
            log.warning("Laya could not be loaded; game decisions will use heuristics: %s", error)
    else:
        log.info("Laya is not installed; game decisions will use heuristics")
    app = create_app(load_token())
    mount_sparks(app, build_spark_services(config, laya))
    return app, config


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app, config = build_app()
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    main()
