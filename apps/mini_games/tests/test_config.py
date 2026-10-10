import json

import pytest

from src.config import ConfigError, load_config, parse_config
from tests.conftest import EXAMPLE_CONFIG


def test_example_config_loads(config):
    assert config.port == 8060
    assert config.situation_source == "heuristic"
    assert config.emblem_prompt_seconds == 5.0
    assert config.database_path.name == "sparks.sqlite3"


@pytest.fixture
def raw():
    return json.loads(EXAMPLE_CONFIG.read_text(encoding="utf-8"))


def test_unknown_situation_source_is_rejected(raw):
    raw["situation_source"] = "magic"
    with pytest.raises(ConfigError, match="situation_source"):
        parse_config(raw)


def test_bool_is_not_a_number(raw):
    raw["port"] = True
    with pytest.raises(ConfigError, match="port"):
        parse_config(raw)


def test_confidence_above_one_is_rejected(raw):
    raw["laya_min_confidence"] = 1.5
    with pytest.raises(ConfigError, match="at most"):
        parse_config(raw)


def test_missing_field_is_rejected(raw):
    del raw["host"]
    with pytest.raises(ConfigError, match="host"):
        parse_config(raw)


def test_unreadable_file_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError, match="cannot read"):
        load_config(tmp_path / "missing.json")
