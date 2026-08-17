"""Tests for services/llm/staged_pipeline.py."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from chat_app.services.llm import staged_pipeline


def _tool(name: str, keywords: list[str] | None = None):
    meta = {"keywords": keywords} if keywords is not None else None
    return SimpleNamespace(
        name=name,
        description=f"{name} description",
        meta=meta,
        inputSchema={"type": "object", "properties": {}},
    )


def test_filter_tools_keeps_a_tool_whose_keyword_matches_the_question():
    health = _tool("get_host_health_tool", keywords=["disk", "cpu", "memory", "health"])
    otp = _tool("request_otp_tool", keywords=["otp", "passcode", "verify"])

    result = staged_pipeline._filter_tools([health, otp], "how is the cpu doing on zima?")

    assert result == [health]


def test_filter_tools_is_case_insensitive():
    health = _tool("get_host_health_tool", keywords=["CPU"])

    result = staged_pipeline._filter_tools([health], "check cpu usage")

    assert result == [health]


def test_filter_tools_keeps_a_tool_with_no_declared_keywords_fail_open():
    """An unannotated tool (no meta at all, e.g. an extension author who
    never adopted the keywords convention) must never become silently
    uncallable just because nothing was declared."""
    unlabeled = _tool("some_extension_tool", keywords=None)

    result = staged_pipeline._filter_tools([unlabeled], "totally unrelated question")

    assert result == [unlabeled]


def test_filter_tools_drops_a_labeled_tool_with_no_overlap():
    otp = _tool("request_otp_tool", keywords=["otp", "passcode"])

    result = staged_pipeline._filter_tools([otp], "how is the cpu doing?")

    assert result == []


def test_filter_tools_ranks_more_matches_first():
    weak_match = _tool("weak", keywords=["cpu", "unrelated1", "unrelated2"])
    strong_match = _tool("strong", keywords=["cpu", "memory", "disk"])

    result = staged_pipeline._filter_tools([weak_match, strong_match], "cpu memory disk usage")

    assert result == [strong_match, weak_match]


def test_filter_tools_caps_the_kept_set():
    tools = [_tool(f"tool_{i}", keywords=["health"]) for i in range(staged_pipeline._MAX_FILTERED_TOOLS + 3)]

    result = staged_pipeline._filter_tools(tools, "health check")

    assert len(result) == staged_pipeline._MAX_FILTERED_TOOLS


def test_filter_tools_empty_meta_dict_is_treated_as_no_keywords():
    tool = _tool("edge_case_tool")
    tool.meta = {}

    result = staged_pipeline._filter_tools([tool], "anything")

    assert result == [tool]


def test_enumerate_plan_parses_a_valid_json_plan():
    plan_json = json.dumps(
        [
            {"type": "tool_call", "detail": "check zima's health"},
            {"type": "reasoning", "detail": "summarize the result"},
        ]
    )
    message = SimpleNamespace(content=plan_json)
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(return_value=response))))

    plan = staged_pipeline._enumerate_plan(fake_client, "phi4-mini:latest", "how is zima?", [])

    assert plan == [
        {"type": "tool_call", "detail": "check zima's health"},
        {"type": "reasoning", "detail": "summarize the result"},
    ]


def test_enumerate_plan_falls_back_on_unparsable_json():
    message = SimpleNamespace(content="not json at all")
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(return_value=response))))

    plan = staged_pipeline._enumerate_plan(fake_client, "phi4-mini:latest", "how is zima?", [])

    assert plan == [{"type": "tool_call", "detail": "how is zima?"}]


def test_enumerate_plan_falls_back_when_step_count_exceeds_the_cap():
    oversized = json.dumps(
        [{"type": "reasoning", "detail": f"step {i}"} for i in range(staged_pipeline._MAX_PLAN_STEPS + 1)]
    )
    message = SimpleNamespace(content=oversized)
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(return_value=response))))

    plan = staged_pipeline._enumerate_plan(fake_client, "phi4-mini:latest", "q", [])

    assert plan == [{"type": "tool_call", "detail": "q"}]


def test_enumerate_plan_falls_back_on_an_unrecognized_step_type():
    bad = json.dumps([{"type": "do_a_backflip", "detail": "??"}])
    message = SimpleNamespace(content=bad)
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(return_value=response))))

    plan = staged_pipeline._enumerate_plan(fake_client, "phi4-mini:latest", "q", [])

    assert plan == [{"type": "tool_call", "detail": "q"}]


def test_enumerate_plan_falls_back_on_an_empty_plan():
    message = SimpleNamespace(content="[]")
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(return_value=response))))

    plan = staged_pipeline._enumerate_plan(fake_client, "phi4-mini:latest", "q", [])

    assert plan == [{"type": "tool_call", "detail": "q"}]


def test_enumerate_plan_sends_filtered_tool_names_and_descriptions_only():
    """Enumerate's own request must stay small - full JSON schemas aren't
    sent, just name + description (see module docstring)."""
    tool = _tool("get_host_health_tool", keywords=None)
    tool.description = "Check CPU, memory, disk."
    message = SimpleNamespace(content="[]")
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    fake_create = Mock(return_value=response)
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create)))

    staged_pipeline._enumerate_plan(fake_client, "phi4-mini:latest", "how is zima?", [tool])

    _, kwargs = fake_create.call_args
    user_message = kwargs["messages"][1]["content"]
    assert "get_host_health_tool" in user_message
    assert "Check CPU, memory, disk." in user_message
    assert "inputSchema" not in user_message and "properties" not in user_message
