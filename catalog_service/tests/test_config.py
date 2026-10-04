from __future__ import annotations

import importlib
import json
from pathlib import Path

from src.config import Settings


def test_defaults():
    settings = Settings()
    assert settings.host == "127.0.0.1"
    assert settings.port == 8020
    assert settings.configs_dir == Path("configs")
    assert settings.cache_path == Path("data/catalog_cache.json")


def test_sources_config_path_joins_configs_dir(tmp_path):
    settings = Settings(configs_dir=tmp_path)
    assert settings.sources_config_path == tmp_path / "config_sources.json"


def test_sources_reads_project_path_pairs(tmp_path):
    config_file = tmp_path / "config_sources.json"
    config_file.write_text(
        json.dumps([{"project": "chat_app", "path": "../chat_app/src"}]),
        encoding="utf-8",
    )
    settings = Settings(configs_dir=tmp_path)

    assert settings.sources() == [("chat_app", Path("../chat_app/src"))]


def test_env_override_for_port(monkeypatch):
    monkeypatch.setenv("CATALOG_PORT", "9999")
    from src import config

    importlib.reload(config)
    try:
        assert config.settings.port == 9999
    finally:
        monkeypatch.delenv("CATALOG_PORT", raising=False)
        importlib.reload(config)
