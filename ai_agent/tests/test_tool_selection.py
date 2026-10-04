"""Settings tests for Laya tool identification."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from src import tool_selection


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    path = tmp_path / "config_tool_selection.json"
    monkeypatch.setattr(tool_selection, "_CONFIG_PATH", path)
    tool_selection.reset_cache()
    yield path
    tool_selection.reset_cache()


def _write(path, data):
    path.write_text(json.dumps({"tool_selection": data}), encoding="utf-8")


def test_values_come_from_file(config_path):
    _write(config_path, {"enabled": True, "top_k": 7})
    assert tool_selection.is_enabled() is True
    assert tool_selection.top_k() == 7


def test_missing_keys_default_to_off_and_20(config_path):
    _write(config_path, {})
    assert tool_selection.is_enabled() is False
    assert tool_selection.top_k() == 20


def test_missing_file_is_seeded_from_example(config_path):
    # tmp_path has no .example sibling, so point at the real one via the shipped file.
    real = Path(tool_selection.__file__).resolve().parent.parent / "configs"
    config_path.with_name(config_path.name + ".example").write_text(
        (real / "config_tool_selection.json.example").read_text(encoding="utf-8"), encoding="utf-8"
    )
    assert tool_selection.is_enabled() is False
    assert config_path.exists()


@pytest.mark.parametrize("bad", [{"enabled": "yes"}, {"top_k": 0}, {"top_k": "5"}, {"top_k": True}, []])
def test_invalid_values_raise(config_path, bad):
    _write(config_path, bad)
    with pytest.raises(ValueError):
        tool_selection.is_enabled()


def _run(*args, **kwargs):
    return asyncio.run(tool_selection.shortlist_schemas(*args, **kwargs))


class _FakeRanker:
    def __init__(self, chosen=None, error=None):
        self.chosen, self.error, self.calls = chosen, error, []

    def rank(self, question, options, k):
        self.calls.append((question, dict(options), k))
        if self.error:
            raise self.error
        return self.chosen


def _schemas(*names):
    return [{"name": n, "description": f"does {n}"} for n in names]


def _enable(config_path, top_k):
    _write(config_path, {"enabled": True, "top_k": top_k})


def test_off_returns_input_untouched(config_path):
    _write(config_path, {"enabled": False, "top_k": 1})
    ranker = _FakeRanker(["a"])
    schemas = _schemas("a", "b", "c")
    assert _run("q", schemas, ranker=ranker) is schemas
    assert ranker.calls == []


def test_keeps_ranked_tools_in_original_order(config_path):
    _enable(config_path, 2)
    ranker = _FakeRanker(["c", "a"])
    result = _run("q", _schemas("a", "b", "c", "d"), ranker=ranker)
    assert [s["name"] for s in result] == ["a", "c"]
    assert ranker.calls == [("q", {"a": "does a", "b": "does b", "c": "does c", "d": "does d"}, 2)]


def test_always_keep_stays_and_is_not_ranked(config_path):
    _enable(config_path, 1)
    ranker = _FakeRanker(["b"])
    result = _run(
        "q", _schemas("a", "b", "delegate"), {"delegate"}, ranker=ranker
    )
    assert [s["name"] for s in result] == ["b", "delegate"]
    assert "delegate" not in ranker.calls[0][1]


def test_small_catalog_skips_ranking(config_path):
    _enable(config_path, 3)
    ranker = _FakeRanker(["a"])
    schemas = _schemas("a", "b", "c", "delegate")
    assert _run("q", schemas, {"delegate"}, ranker=ranker) is schemas
    assert ranker.calls == []


def test_ranker_failure_falls_back_to_every_tool(config_path):
    _enable(config_path, 1)
    schemas = _schemas("a", "b")
    result = _run("q", schemas, ranker=_FakeRanker(error=RuntimeError("boom")))
    assert result is schemas
