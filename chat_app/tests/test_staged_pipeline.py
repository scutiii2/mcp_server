"""Tests for services/llm/staged_pipeline.py."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from chat_app.services.llm import staged_pipeline, staged_plans_store
from chat_app.services.llm.base import ToolCallRecord


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


def test_filter_tools_drops_a_labeled_tool_with_no_overlap_when_another_tool_matches():
    health = _tool("get_host_health_tool", keywords=["cpu", "memory"])
    otp = _tool("request_otp_tool", keywords=["otp", "passcode"])

    result = staged_pipeline._filter_tools([health, otp], "how is the cpu doing?")

    assert result == [health]


def test_filter_tools_falls_back_to_the_full_list_when_nothing_matches():
    """Regression test: a capability question like "give me the list of
    tools you have" shares no token with any tool-specific keyword, so
    every labeled tool would otherwise get dropped and Enumerate would be
    shown zero tools for exactly the question most likely to ask about
    them - see _filter_tools's docstring."""
    health = _tool("get_host_health_tool", keywords=["cpu", "memory"])
    otp = _tool("request_otp_tool", keywords=["otp", "passcode"])

    result = staged_pipeline._filter_tools([health, otp], "give me the list of tools you have")

    assert result == [health, otp]


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


def test_filter_tools_keeps_a_tool_named_literally_in_the_text_with_no_keyword_overlap():
    """Regression test: _ENUMERATE_SYSTEM_PROMPT instructs tool_call steps
    to name the tool literally in `detail` (e.g. "call get_host_health_tool
    with name=zima"), and _execute_tool_call_step re-filters against that
    detail text. The tool's own declared keywords deliberately share no
    tokens with its name here, so this only survives filtering if
    _filter_tools also matches against the tool's own name tokens."""
    tool = _tool("get_host_health_tool", keywords=["cpu", "memory", "disk", "uptime"])

    result = staged_pipeline._filter_tools([tool], "call get_host_health_tool with name=zima")

    assert result == [tool]


def test_filter_tools_matches_a_keyword_immediately_followed_by_punctuation():
    """Regression test: the old str.split() tokenization left "cpu?" as
    one token, which never matched the bare keyword "cpu"."""
    tool = _tool("get_host_health_tool", keywords=["cpu"])

    result = staged_pipeline._filter_tools([tool], "how's the cpu?")

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


def test_execute_steps_runs_a_tool_call_step_and_records_the_result():
    tool = _tool("get_host_health_tool", keywords=["health"])
    plan = [{"type": "tool_call", "detail": "check zima's health"}]
    call = SimpleNamespace(id="call_1", function=SimpleNamespace(name="get_host_health_tool", arguments="{}"))
    round_one = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[call]))])
    round_two = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="zima is healthy", tool_calls=None))]
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(side_effect=[round_one, round_two])))
    )
    tools_used: list[str] = []
    tool_calls_log: list[ToolCallRecord] = []
    results: list = []

    with patch("chat_app.services.llm.staged_pipeline.call_tool", return_value="cpu 12%") as mock_call_tool:
        pause, calls_used = staged_pipeline._execute_steps(
            fake_client, "phi4-mini:latest", [tool], "", plan, 0, results, tools_used, tool_calls_log,
            calls_budget=10,
        )

    assert pause is None
    # Honest round-counting: this step made 2 real calls (one that
    # produced the tool_call, one that produced the final answer), not a
    # flat 1 - see the call-budget accounting fix in _execute_steps.
    assert calls_used == 2
    assert results == [{"detail": "check zima's health", "result": "zima is healthy"}]
    assert tools_used == ["get_host_health_tool"]
    mock_call_tool.assert_called_once_with("get_host_health_tool", {})


def test_execute_steps_stops_and_returns_a_pause_on_ask_user():
    plan = [
        {"type": "reasoning", "detail": "think about it"},
        {"type": "ask_user", "detail": "which host do you mean?"},
        {"type": "reasoning", "detail": "never reached"},
    ]
    reasoning_response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="thought"))])
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(return_value=reasoning_response)))
    )
    results: list = []

    pause, calls_used = staged_pipeline._execute_steps(
        fake_client, "phi4-mini:latest", [], "", plan, 0, results, [], [], calls_budget=10,
    )

    assert pause == staged_pipeline._AskUserPause(step_index=1, question="which host do you mean?")
    assert calls_used == 1  # only the reasoning step before the pause
    assert results == [{"detail": "think about it", "result": "thought"}]


def test_execute_steps_resumes_from_the_given_step_index():
    plan = [
        {"type": "ask_user", "detail": "already answered"},
        {"type": "reasoning", "detail": "continue here"},
    ]
    reasoning_response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="done"))])
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(return_value=reasoning_response)))
    )
    results = [{"detail": "already answered", "result": "the user's answer"}]

    pause, calls_used = staged_pipeline._execute_steps(
        fake_client, "phi4-mini:latest", [], "", plan, 1, results, [], [], calls_budget=10,
    )

    assert pause is None
    assert calls_used == 1
    assert results[-1] == {"detail": "continue here", "result": "done"}


def test_execute_steps_stops_at_the_call_budget_without_erroring():
    plan = [{"type": "reasoning", "detail": f"step {i}"} for i in range(5)]
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(return_value=response))))
    results: list = []

    pause, calls_used = staged_pipeline._execute_steps(
        fake_client, "phi4-mini:latest", [], "", plan, 0, results, [], [], calls_budget=2,
    )

    assert pause is None
    assert calls_used == 2
    assert len(results) == 2


def test_execute_tool_call_step_recovers_from_a_failing_tool():
    tool = _tool("get_host_health_tool", keywords=None)
    call = SimpleNamespace(id="call_1", function=SimpleNamespace(name="get_host_health_tool", arguments="{}"))
    round_one = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[call]))])
    round_two = SimpleNamespace(
        choices=[
            SimpleNamespace(message=SimpleNamespace(content="couldn't check, but here's what I know", tool_calls=None))
        ]
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(side_effect=[round_one, round_two])))
    )

    with patch("chat_app.services.llm.staged_pipeline.call_tool", side_effect=RuntimeError("connection refused")):
        result, rounds_used = staged_pipeline._execute_tool_call_step(
            fake_client, "phi4-mini:latest", "check zima", [tool], [], []
        )

    assert result == "couldn't check, but here's what I know"
    assert rounds_used == 2  # one round that made the (failing) tool call, one that gave the final answer


def test_run_full_happy_path_with_no_ask_user_step(tmp_path: Path):
    plan_json = json.dumps([{"type": "reasoning", "detail": "think"}])
    enumerate_response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=plan_json))])
    execute_response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="thought result"))])
    conclude_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="Here is your answer."))]
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=Mock(side_effect=[enumerate_response, execute_response, conclude_response])
            )
        )
    )
    db = tmp_path / "staged_plans.db"

    with patch("chat_app.services.llm.staged_pipeline.list_tools", return_value=[]):
        result = staged_pipeline.run(fake_client, "how is zima?", [], "phi4-mini:latest", "chat-1", None, db)

    assert result.response == "Here is your answer."
    assert result.provider_id == "ollama"
    assert staged_plans_store.get(db, "chat-1") is None  # nothing left paused


def test_run_pauses_on_ask_user_and_persists_the_plan(tmp_path: Path):
    plan_json = json.dumps([{"type": "ask_user", "detail": "which host do you mean?"}])
    enumerate_response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=plan_json))])
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(return_value=enumerate_response)))
    )
    db = tmp_path / "staged_plans.db"

    with patch("chat_app.services.llm.staged_pipeline.list_tools", return_value=[]):
        result = staged_pipeline.run(fake_client, "check my host", [], "phi4-mini:latest", "chat-1", None, db)

    assert result.response == "which host do you mean?"
    saved = staged_plans_store.get(db, "chat-1")
    assert saved is not None
    assert saved.step_index == 0
    assert saved.model == "phi4-mini:latest"


def test_run_resumes_a_paused_plan_and_completes_it(tmp_path: Path):
    db = tmp_path / "staged_plans.db"
    plan = [
        {"type": "ask_user", "detail": "which host do you mean?"},
        {"type": "reasoning", "detail": "summarize"},
    ]
    staged_plans_store.save(db, "chat-1", "ollama", "phi4-mini:latest", plan, 0, [])
    execute_response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="summarized"))])
    conclude_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="Final answer about zima."))]
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=Mock(side_effect=[execute_response, conclude_response]))
        )
    )

    with patch("chat_app.services.llm.staged_pipeline.list_tools", return_value=[]):
        result = staged_pipeline.run(fake_client, "zima", [], "phi4-mini:latest", "chat-1", None, db)

    assert result.response == "Final answer about zima."
    assert staged_plans_store.get(db, "chat-1") is None


def test_run_discards_a_resume_row_saved_under_a_different_model(tmp_path: Path):
    """A paused plan saved under one model, then resumed after the user
    switched models, must not be silently continued under the new
    model's assumptions."""
    db = tmp_path / "staged_plans.db"
    staged_plans_store.save(db, "chat-1", "ollama", "phi4-mini:latest", [{"type": "ask_user", "detail": "q"}], 0, [])
    plan_json = json.dumps([{"type": "reasoning", "detail": "fresh plan"}])
    enumerate_response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=plan_json))])
    execute_response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="fresh result"))])
    conclude_response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="fresh answer"))])
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=Mock(side_effect=[enumerate_response, execute_response, conclude_response])
            )
        )
    )

    with patch("chat_app.services.llm.staged_pipeline.list_tools", return_value=[]):
        result = staged_pipeline.run(fake_client, "new question", [], "qwen2.5:7b", "chat-1", None, db)

    assert result.response == "fresh answer"


def test_run_with_no_chat_id_still_answers_an_ask_user_pause_but_cannot_persist(tmp_path: Path):
    plan_json = json.dumps([{"type": "ask_user", "detail": "which host?"}])
    enumerate_response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=plan_json))])
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(return_value=enumerate_response)))
    )
    db = tmp_path / "staged_plans.db"

    with patch("chat_app.services.llm.staged_pipeline.list_tools", return_value=[]):
        result = staged_pipeline.run(fake_client, "check my host", [], "phi4-mini:latest", None, None, db)

    assert result.response == "which host?"
    assert not db.exists()  # nothing to persist against - no chat_id


def test_run_discards_a_resume_row_saved_under_a_different_provider_id(tmp_path: Path):
    """A saved plan is only resumable when BOTH provider_id and model
    match this turn's (design spec §3, phase 0) - not model alone. A row
    somehow saved under a different provider_id (e.g. a future non-Ollama
    caller of this same store) must not be silently continued."""
    db = tmp_path / "staged_plans.db"
    staged_plans_store.save(
        db, "chat-1", "not-ollama", "phi4-mini:latest", [{"type": "ask_user", "detail": "q"}], 0, []
    )
    plan_json = json.dumps([{"type": "reasoning", "detail": "fresh plan"}])
    enumerate_response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=plan_json))])
    execute_response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="fresh result"))])
    conclude_response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="fresh answer"))])
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=Mock(side_effect=[enumerate_response, execute_response, conclude_response])
            )
        )
    )

    with patch("chat_app.services.llm.staged_pipeline.list_tools", return_value=[]):
        result = staged_pipeline.run(fake_client, "new question", [], "phi4-mini:latest", "chat-1", None, db)

    assert result.response == "fresh answer"


def test_run_stops_at_the_call_budget_under_honest_round_counting_and_still_concludes(tmp_path: Path):
    """Regression test for the call-budget accounting bug: a tool_call
    step's internal rounds (up to _MAX_STEP_TOOL_ROUNDS each) must be
    charged individually against _MAX_TOTAL_CALLS, not a flat 1 per step -
    otherwise the budget can never actually fire, since _MAX_PLAN_STEPS
    (8) is always smaller than _MAX_TOTAL_CALLS (20).

    Five tool_call steps that each exhaust every one of their rounds
    (never producing a final answer) would, under honest counting, blow
    past the remaining budget (19, after Enumerate's own call) partway
    through the 4th step - so only 4 of the 5 steps' full round budgets
    are ever spent, the 5th step's rounds are never requested, and the
    run still completes via Conclude using whatever partial results
    exist. Under the old flat-1-per-step accounting, all 5 steps would
    run to exhaustion (32 real calls total), which this test's fixed
    number of mocked responses (26) would not have enough of to satisfy -
    so this test also fails loudly under the old buggy accounting.
    """
    tool = _tool("get_host_health_tool", keywords=None)
    plan_steps = [{"type": "tool_call", "detail": f"step {i}"} for i in range(5)]
    plan_json = json.dumps(plan_steps)
    enumerate_response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=plan_json))])

    call = SimpleNamespace(id="call_1", function=SimpleNamespace(name="get_host_health_tool", arguments="{}"))
    exhausting_round = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[call]))]
    )
    conclude_response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Partial answer."))])

    # Enumerate (1) + 4 fully-exhausted tool_call steps (4 * 6 rounds each)
    # + Conclude (1) = 26. A 5th step's rounds must never be requested.
    responses = (
        [enumerate_response]
        + [exhausting_round] * (staged_pipeline._MAX_STEP_TOOL_ROUNDS * 4)
        + [conclude_response]
    )
    fake_create = Mock(side_effect=responses)
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create)))
    db = tmp_path / "staged_plans.db"

    with patch("chat_app.services.llm.staged_pipeline.list_tools", return_value=[tool]), \
         patch("chat_app.services.llm.staged_pipeline.call_tool", return_value="ok"):
        result = staged_pipeline.run(fake_client, "check 5 hosts", [], "phi4-mini:latest", "chat-1", None, db)

    assert result.response == "Partial answer."
    assert fake_create.call_count == 1 + staged_pipeline._MAX_STEP_TOOL_ROUNDS * 4 + 1
