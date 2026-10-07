"""Tests for the usage_report domain logic."""

from __future__ import annotations

import json
from datetime import date

import pytest

from src.capabilities.usage_report import domain

TODAY = date(2026, 10, 7)


def _row(agent="ember", model="m1", inp=10, out=5):
    return json.dumps({"agent_id": agent, "model": model, "input_tokens": inp, "output_tokens": out})


@pytest.fixture
def usage_dir(tmp_path):
    (tmp_path / "2026-10-07.ember.jsonl").write_text(_row() + "\n" + _row(inp=20, out=10) + "\n")
    (tmp_path / "2026-10-06.server-ops.jsonl").write_text(_row("server-ops", "m2", 100, 50) + "\nnot json\n\n")
    (tmp_path / "2026-09-01.ember.jsonl").write_text(_row(inp=999, out=999) + "\n")
    (tmp_path / "notes.jsonl").write_text(_row() + "\n")
    return tmp_path


def test_group_by_agent_largest_first(usage_dir):
    result = domain.summarize(usage_dir, 7, "agent", TODAY)
    assert [(r.key, r.requests, r.total_tokens) for r in result.rows] == [("server-ops", 1, 150), ("ember", 2, 45)]
    assert result.requests == 3 and result.total_tokens == 195 and result.skipped_lines == 1


def test_old_days_and_odd_file_names_are_left_out(usage_dir):
    assert domain.summarize(usage_dir, 1, "agent", TODAY).total_tokens == 45


def test_group_by_day_is_in_date_order(usage_dir):
    result = domain.summarize(usage_dir, 7, "day", TODAY)
    assert [r.key for r in result.rows] == ["2026-10-06", "2026-10-07"]


def test_group_by_model(usage_dir):
    assert {r.key for r in domain.summarize(usage_dir, 7, "model", TODAY).rows} == {"m1", "m2"}


@pytest.mark.parametrize("days, group", [(0, "agent"), (91, "agent"), (7, "user")])
def test_input_is_validated(usage_dir, days, group):
    with pytest.raises(ValueError):
        domain.summarize(usage_dir, days, group, TODAY)


def test_missing_folder_names_the_setting(tmp_path):
    with pytest.raises(FileNotFoundError, match="MCP_USAGE_DIR"):
        domain.summarize(tmp_path / "nope")
