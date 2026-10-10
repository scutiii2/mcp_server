from __future__ import annotations

import json

import pytest

from src.services.ticket_config import DEFAULT_TAGS, load_ticket_config


def test_missing_file_gives_defaults(tmp_path):
    config = load_ticket_config(tmp_path / "config_tickets.json")

    assert config.tags == DEFAULT_TAGS
    assert 2 <= len(config.tags) <= 10
    assert config.auto_hourly_cap == 5
    assert config.recent_hours == 24
    assert config.elevation == {"high": {"tickets": 3, "recent": 2}, "urgent": {"tickets": 6, "recent": 4}}
    assert config.laya_min_confidence == 0.7
    assert config.laya_candidates == 5
    assert config.laya_timeout_seconds == 20.0


def test_file_overrides_only_what_it_names(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"auto_hourly_cap": 2, "laya": {"candidates": 3}}))

    config = load_ticket_config(path)

    assert config.auto_hourly_cap == 2
    assert config.laya_candidates == 3
    assert config.laya_timeout_seconds == 20.0
    assert config.tags == DEFAULT_TAGS


@pytest.mark.parametrize(
    "raw",
    [
        {"tags": {"only-one": "x"}},
        {"tags": {f"t{i}": "d" for i in range(11)}},
        {"tags": {"a": "", "b": "d"}},
        {"auto_hourly_cap": 0},
        {"elevation": {"critical": {"tickets": 1, "recent": 1}}},
        {"elevation": {"high": {"tickets": 0, "recent": 1}}},
        {"laya": {"min_confidence": 1.5}},
        {"laya": {"timeout_seconds": 0}},
    ],
)
def test_bad_values_are_rejected(tmp_path, raw):
    path = tmp_path / "c.json"
    path.write_text(json.dumps(raw))

    with pytest.raises(ValueError):
        load_ticket_config(path)


def test_invalid_json_is_rejected(tmp_path):
    path = tmp_path / "c.json"
    path.write_text("{nope")

    with pytest.raises(ValueError, match="not valid JSON"):
        load_ticket_config(path)
