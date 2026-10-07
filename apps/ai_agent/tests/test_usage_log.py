"""usage_log.py tests: the agent_usage row shape and the per-agent,
per-day JSONL append (which never fails a turn)."""

from __future__ import annotations

import asyncio
import json
import logging

from src.core import usage_log
from src.llm.base_provider import ChatResult


def _row():
    result = ChatResult(response="x", provider_id="anthropic", model="claude-sonnet-5-5",
                        total_tokens=15, input_tokens=10, output_tokens=5)
    return usage_log.own_row(
        result, agent_id="calc", agent_label="Calculator", gateway="openrouter",
        started_at="2026-10-04T09:12:03.512Z", finished_at="2026-10-04T09:12:07.044Z", delegated_by="claude-agent",
    )


def test_own_row_shape():
    assert _row() == {
        "agent_id": "calc", "agent_label": "Calculator", "provider_id": "anthropic", "gateway": "openrouter",
        "model": "claude-sonnet-5-5", "input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
        "started_at": "2026-10-04T09:12:03.512Z", "finished_at": "2026-10-04T09:12:07.044Z",
        "delegated_by": "claude-agent",
    }


def test_append_writes_one_line_per_turn_to_a_per_agent_daily_file(tmp_path):
    asyncio.run(usage_log.append({**_row(), "request_id": "r1"}, tmp_path))
    asyncio.run(usage_log.append({**_row(), "request_id": "r2"}, tmp_path))

    lines = (tmp_path / "2026-10-04.calc.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["request_id"] for line in lines] == ["r1", "r2"]


def test_append_failure_only_warns(tmp_path, caplog):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="src.core.usage_log"):
        asyncio.run(usage_log.append(_row(), blocker))
    assert "usage log" in caplog.text


def test_usage_dir_honours_the_env(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_AGENT_USAGE_DIR", str(tmp_path))
    assert usage_log.usage_dir() == tmp_path


def test_own_row_records_model_tier_only_when_given():
    result = ChatResult(response="x", provider_id="anthropic", model="haiku")
    common = dict(
        agent_id="calc", agent_label="Calculator", gateway="claude",
        started_at="2026-10-08T09:00:00.000Z", finished_at="2026-10-08T09:00:01.000Z", delegated_by=None,
    )
    assert usage_log.own_row(result, **common, model_tier="light")["model_tier"] == "light"
    assert "model_tier" not in usage_log.own_row(result, **common)
