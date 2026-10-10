import json
import logging
from pathlib import Path

import pytest

from src import run
from src.config import ConfigError, parse_config
from tests.conftest import EXAMPLE_CONFIG


@pytest.fixture
def raw():
    return json.loads(EXAMPLE_CONFIG.read_text(encoding="utf-8"))


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("key", ["port", "laya_timeout_seconds", "faint_seconds", "laya_min_confidence"])
def test_non_finite_numbers_are_rejected(raw, key, bad):
    raw[key] = bad
    with pytest.raises(ConfigError, match=key):
        parse_config(raw)


def test_a_fractional_port_is_rejected_not_truncated(raw):
    raw["port"] = 8060.5
    with pytest.raises(ConfigError, match="port.*whole"):
        parse_config(raw)


def test_a_whole_float_port_is_accepted(raw):
    raw["port"] = 8061.0
    assert parse_config(raw).port == 8061


def test_error_text_says_at_least_only_for_range_errors(raw):
    raw["port"] = "80"
    with pytest.raises(ConfigError) as wrong_type:
        parse_config(raw)
    assert "at least" not in str(wrong_type.value)
    raw["port"] = 0
    with pytest.raises(ConfigError, match="at least"):
        parse_config(raw)


def test_sparks_path_defaults_when_absent(raw):
    raw.pop("sparks_path")
    config = parse_config(raw, root=Path("/proj"))
    assert config.sparks_path == Path("/proj") / "catalogs" / "sparks"


def test_sparks_path_resolves_against_the_root_and_keeps_absolute_paths(raw):
    raw["sparks_path"] = "custom/sparks"
    assert parse_config(raw, root=Path("/proj")).sparks_path == Path("/proj") / "custom" / "sparks"
    absolute = Path("/elsewhere").resolve()
    raw["sparks_path"] = str(absolute)
    assert parse_config(raw, root=Path("/proj")).sparks_path == absolute


@pytest.mark.parametrize("bad", ["", 5, None, ["x"]])
def test_a_bad_sparks_path_is_rejected(raw, bad):
    raw["sparks_path"] = bad
    with pytest.raises(ConfigError, match="sparks_path"):
        parse_config(raw)


def test_empty_token_logs_a_warning(monkeypatch, caplog):
    monkeypatch.setattr(run, "load_token", lambda: "")
    with caplog.at_level(logging.WARNING, logger="mini_games"):
        run.build_app()
    assert any("unauthenticated" in r.message for r in caplog.records)


def test_a_configured_token_logs_no_warning(monkeypatch, caplog):
    monkeypatch.setattr(run, "load_token", lambda: "secret-token")
    with caplog.at_level(logging.WARNING, logger="mini_games"):
        run.build_app()
    assert not any("unauthenticated" in r.message for r in caplog.records)
