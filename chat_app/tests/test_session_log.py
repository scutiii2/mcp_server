from __future__ import annotations

import dataclasses
import json

from chat_app.config import settings as base_settings
from chat_app.services import session_log
from chat_app.services.llm.base import RecursiveRoundRecord, ToolCallRecord


def test_record_turn_appends_one_json_line_with_the_full_detail(monkeypatch, tmp_path):
    monkeypatch.setattr(session_log, "settings", dataclasses.replace(base_settings, log_dir=tmp_path))

    session_log.record_turn(
        "alice",
        "chat123",
        question="how is web-1?",
        response="web-1 is healthy.",
        provider_id="claude",
        model="claude-sonnet-5",
        tool_calls=[ToolCallRecord(name="get_status_tool", arguments={"resource_id": "web-1"}, result="ok")],
        recursive_rounds=[RecursiveRoundRecord(round=1, response="refined answer", converged=True)],
        total_tokens=42,
    )

    log_file = tmp_path / "chats" / "alice" / "chat123.jsonl"
    assert log_file.exists()
    entry = json.loads(log_file.read_text(encoding="utf-8").strip())
    assert entry["question"] == "how is web-1?"
    assert entry["response"] == "web-1 is healthy."
    assert entry["provider_id"] == "claude"
    assert entry["model"] == "claude-sonnet-5"
    assert entry["total_tokens"] == 42
    assert entry["tool_calls"] == [
        {"name": "get_status_tool", "arguments": {"resource_id": "web-1"}, "result": "ok"}
    ]
    assert entry["recursive_rounds"] == [{"round": 1, "response": "refined answer", "converged": True}]
    assert "timestamp" in entry


def test_record_turn_appends_rather_than_overwrites(monkeypatch, tmp_path):
    monkeypatch.setattr(session_log, "settings", dataclasses.replace(base_settings, log_dir=tmp_path))

    for question in ("first", "second"):
        session_log.record_turn(
            "alice",
            "chat123",
            question=question,
            response="ok",
            provider_id="claude",
            model=None,
            tool_calls=[],
            recursive_rounds=[],
            total_tokens=None,
        )

    lines = (tmp_path / "chats" / "alice" / "chat123.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["question"] for line in lines] == ["first", "second"]


def test_record_turn_sanitizes_a_username_that_looks_like_a_path(monkeypatch, tmp_path):
    monkeypatch.setattr(session_log, "settings", dataclasses.replace(base_settings, log_dir=tmp_path))

    session_log.record_turn(
        "../../etc/passwd",
        "chat123",
        question="q",
        response="a",
        provider_id="claude",
        model=None,
        tool_calls=[],
        recursive_rounds=[],
        total_tokens=None,
    )

    # Nothing escaped tmp_path / "chats" - every unsafe character became "_".
    chats_dir = tmp_path / "chats"
    created_dirs = [p for p in chats_dir.iterdir() if p.is_dir()]
    assert len(created_dirs) == 1
    assert created_dirs[0].parent == chats_dir
    assert (created_dirs[0] / "chat123.jsonl").exists()
