import json

import pytest

from src.utils.config_loader import (
    load_all_json_configs,
    load_env_secrets,
    load_json_config,
)


def test_load_json_config_reads_file(tmp_path):
    config_file = tmp_path / "config_example.json"
    config_file.write_text(json.dumps({"enabled": True, "max": 5}))

    result = load_json_config(config_file)

    assert result == {"enabled": True, "max": 5}


def test_load_json_config_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_json_config(tmp_path / "does_not_exist.json")


def test_load_env_secrets_reads_file(tmp_path):
    env_file = tmp_path / "secret_app.env"
    env_file.write_text("SECRET_KEY=abc123\nOTHER=xyz\n")

    result = load_env_secrets(env_file)

    assert result == {"SECRET_KEY": "abc123", "OTHER": "xyz"}


def test_load_env_secrets_missing_returns_empty(tmp_path):
    result = load_env_secrets(tmp_path / "does_not_exist.env")

    assert result == {}


def test_load_all_json_configs_directory(tmp_path):
    (tmp_path / "config_a.json").write_text(json.dumps({"a": 1}))
    (tmp_path / "config_b.json").write_text(json.dumps({"b": 2}))
    (tmp_path / "not_json.txt").write_text("ignore me")

    result = load_all_json_configs(tmp_path)

    assert result == {"config_a": {"a": 1}, "config_b": {"b": 2}}


def test_load_all_json_configs_missing_dir_returns_empty(tmp_path):
    result = load_all_json_configs(tmp_path / "nope")

    assert result == {}
