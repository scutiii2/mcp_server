"""questions.py: asking the user clickable questions - the policy, the broker that
waits for the answer, the ask()/handle() helpers the providers call, and both
providers' tool loops. Plain sync tests around asyncio.run(), like test_approvals.py."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from src import server
from src.core import approvals
from src.llm import anthropic_provider, openai_provider
from src.llm.base_provider import ChatResult


import pytest

from src.agents import ask_user
from src.core import questions
from src.llm import cancellation
from src.llm.base_provider import ChatCancelled

REQUEST = "req-q"
QUESTIONS = [
    {
        "header": "Format",
        "question": "Which format?",
        "multi_select": False,
        "options": [{"label": "CSV"}, {"label": "JSON"}],
    },
    {
        "header": "Extras",
        "question": "Which extras?",
        "multi_select": True,
        "options": [{"label": "Totals"}, {"label": "Chart"}],
    },
]
ANSWERS = [{"selected": ["CSV"], "other": None}, {"selected": ["Totals", "Chart"], "other": "and a title"}]


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    cancellation.clear(REQUEST)
    monkeypatch.setattr(questions, "BROKER", questions.QuestionBroker(timeout=3.0, poll=0.05, keepalive=0.1))
    yield
    cancellation.clear(REQUEST)


def run(coro):
    return asyncio.run(coro)


class Recorder:
    """An on_event that keeps every event, and answers a question when told how."""

    def __init__(self, answers=None, skipped=False) -> None:
        self.events: list[dict] = []
        self._answers = answers
        self._skipped = skipped

    async def __call__(self, event: dict) -> None:
        self.events.append(event)
        if event["type"] == "question_request" and (self._answers is not None or self._skipped):
            asyncio.get_running_loop().call_soon(
                questions.BROKER.answer, REQUEST, event["id"], self._answers or [], self._skipped
            )

    def types(self) -> list[str]:
        return [e["type"] for e in self.events]


# --- the policy ------------------------------------------------------------------------


def test_the_default_policy_offers_nothing() -> None:
    assert questions.current().enabled is False


def test_bind_and_reset_restore_the_previous_policy() -> None:
    token = questions.bind(questions.QuestionPolicy(True))
    assert questions.current().enabled is True

    questions.reset(token)

    assert questions.current().enabled is False


# --- the broker -------------------------------------------------------------------------


def test_wait_returns_the_answers_or_a_skip() -> None:
    async def scenario():
        broker = questions.QuestionBroker(timeout=5, poll=0.05)
        loop = asyncio.get_running_loop()
        loop.call_soon(broker.answer, REQUEST, "s1", ANSWERS, False)
        first = await broker.wait(REQUEST, "s1")
        loop.call_soon(broker.answer, REQUEST, "s1", [], True)
        second = await broker.wait(REQUEST, "s1")
        return first, second

    first, second = run(scenario())

    assert (first.outcome, list(first.answers)) == ("answered", ANSWERS)
    assert second.outcome == "skipped"


def test_answer_is_false_when_nothing_is_waiting_and_counts_once() -> None:
    async def scenario():
        broker = questions.QuestionBroker(timeout=5, poll=0.05)
        before = broker.answer(REQUEST, "s1", ANSWERS, False)
        waiter = asyncio.create_task(broker.wait(REQUEST, "s1"))
        await asyncio.sleep(0)
        first = broker.answer(REQUEST, "s1", ANSWERS, False)
        second = broker.answer(REQUEST, "s1", ANSWERS, False)
        await waiter
        return before, first, second

    assert run(scenario()) == (False, True, False)


def test_an_unanswered_question_times_out_at_the_safety_cap() -> None:
    async def scenario():
        return await questions.QuestionBroker(timeout=0.2, poll=0.05).wait(REQUEST, "s1")

    assert run(scenario()).outcome == "timeout"


def test_stop_ends_the_wait() -> None:
    async def scenario():
        asyncio.get_running_loop().call_later(0.1, cancellation.cancel, REQUEST)
        return await questions.QuestionBroker(timeout=5, poll=0.05).wait(REQUEST, "s1")

    cancellation.register(REQUEST)
    assert run(scenario()).outcome == "cancelled"


def test_a_second_wait_on_the_same_step_replaces_the_first_which_reads_as_skipped() -> None:
    async def scenario():
        broker = questions.QuestionBroker(timeout=5, poll=0.05)
        first = asyncio.create_task(broker.wait(REQUEST, "s1"))
        await asyncio.sleep(0.01)
        second = asyncio.create_task(broker.wait(REQUEST, "s1"))
        await asyncio.sleep(0.01)
        broker.answer(REQUEST, "s1", ANSWERS, False)
        return (await first).outcome, (await second).outcome

    assert run(scenario()) == ("skipped", "answered")


def test_a_keepalive_event_is_sent_while_waiting() -> None:
    async def scenario():
        rec = Recorder()
        broker = questions.QuestionBroker(timeout=5, poll=0.02, keepalive=0.05)
        waiter = asyncio.create_task(broker.wait(REQUEST, "s1", rec))
        await asyncio.sleep(0.3)
        broker.answer(REQUEST, "s1", [], True)
        await waiter
        return rec.types()

    types = run(scenario())

    assert types and set(types) == {"keepalive"} and len(types) >= 2


# --- the answer text ---------------------------------------------------------------------


def test_format_answers_names_each_question_and_what_was_chosen() -> None:
    text = questions.format_answers(QUESTIONS, ANSWERS)

    assert text == (
        "The user answered:\n"
        "- Which format?: CSV\n"
        "- Which extras?: Totals, Chart; other: and a title"
    )


def test_format_answers_handles_only_other_and_missing_answers() -> None:
    text = questions.format_answers(QUESTIONS, [{"selected": [], "other": "XML"}])

    assert text == "The user answered:\n- Which format?: other: XML\n- Which extras?: (no answer)"


# --- ask() ------------------------------------------------------------------------------


def test_ask_emits_request_then_resolved_and_returns_the_answer_text() -> None:
    rec = Recorder(answers=ANSWERS)

    text = run(questions.ask(REQUEST, "s1", QUESTIONS, rec))

    assert text == questions.format_answers(QUESTIONS, ANSWERS)
    assert rec.types() == ["question_request", "question_resolved"]
    assert rec.events[0]["id"] == "s1" and rec.events[0]["questions"] == QUESTIONS
    assert rec.events[1]["outcome"] == "answered"


def test_ask_tells_the_model_when_the_user_skips() -> None:
    rec = Recorder(skipped=True)

    assert run(questions.ask(REQUEST, "s1", QUESTIONS, rec)) == questions.SKIPPED
    assert rec.events[-1]["outcome"] == "skipped"


def test_ask_tells_the_model_when_the_cap_runs_out(monkeypatch) -> None:
    monkeypatch.setattr(questions, "BROKER", questions.QuestionBroker(timeout=0.2, poll=0.05, keepalive=10))
    rec = Recorder()

    assert run(questions.ask(REQUEST, "s1", QUESTIONS, rec)) == questions.TIMED_OUT
    assert rec.events[-1]["outcome"] == "timeout"


def test_ask_has_no_channel_without_an_event_sink_or_a_request_id() -> None:
    assert run(questions.ask(REQUEST, "s1", QUESTIONS, None)) == questions.NO_CHANNEL
    assert run(questions.ask(None, "s1", QUESTIONS, Recorder())) == questions.NO_CHANNEL


def test_stop_while_a_question_is_open_ends_the_step_and_cancels_the_turn() -> None:
    cancellation.register(REQUEST)
    rec = Recorder()

    async def stopper(event: dict) -> None:
        await rec(event)
        if event["type"] == "question_request":
            asyncio.get_running_loop().call_later(0.05, cancellation.cancel, REQUEST)

    with pytest.raises(ChatCancelled):
        run(questions.ask(REQUEST, "s1", QUESTIONS, stopper))

    assert rec.types() == ["question_request", "question_resolved", "step_end"]
    assert rec.events[-1]["ok"] is False


# --- handle() -----------------------------------------------------------------------------


def test_handle_ignores_every_other_tool() -> None:
    assert run(questions.handle("tool_srv_stopApp", REQUEST, "s1", {}, Recorder())) is None


def test_handle_refuses_the_tool_when_it_was_not_offered() -> None:
    rec = Recorder()

    result = run(questions.handle(ask_user.TOOL_NAME, REQUEST, "s1", {"questions": QUESTIONS}, rec))

    assert result == (questions.NOT_OFFERED, False)
    assert rec.events == []


def test_handle_gives_a_bad_call_back_to_the_model_without_asking_the_user() -> None:
    rec = Recorder()
    token = questions.bind(questions.QuestionPolicy(True))
    try:
        text, ok = run(questions.handle(ask_user.TOOL_NAME, REQUEST, "s1", {"questions": []}, rec))
    finally:
        questions.reset(token)

    assert ok is False and "1 to 4" in text
    assert rec.events == []


def test_handle_asks_and_returns_the_answers_as_the_tool_result() -> None:
    rec = Recorder(answers=ANSWERS)
    token = questions.bind(questions.QuestionPolicy(True))
    try:
        result = run(questions.handle(ask_user.TOOL_NAME, REQUEST, "s1", {"questions": QUESTIONS}, rec))
    finally:
        questions.reset(token)

    assert result == (questions.format_answers(QUESTIONS, ANSWERS), True)

# --- the providers' tool loops ----------------------------------------------------------------

ASK_ARGUMENTS = {"questions": QUESTIONS}


def _anthropic_client(arguments):
    tool_block = MagicMock(type="tool_use", input=arguments, id="t1")
    tool_block.name = ask_user.TOOL_NAME
    first = MagicMock(stop_reason="tool_use", content=[tool_block])
    first.usage.input_tokens = 10
    first.usage.output_tokens = 5
    second = MagicMock(stop_reason="end_turn", content=[])
    second.usage.input_tokens = 3
    second.usage.output_tokens = 1

    def round_cm(chunks, final):
        async def gen():
            for chunk in chunks:
                yield chunk

        stream = MagicMock()
        stream.text_stream = gen()
        stream.get_final_message = AsyncMock(return_value=final)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=stream)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    client = MagicMock()
    client.messages.stream = MagicMock(side_effect=[round_cm([], first), round_cm(["Done"], second)])
    return client


def anthropic_turn(monkeypatch, recorder, dispatch, enabled=True, approval_mode="off"):
    client = _anthropic_client(ASK_ARGUMENTS)
    monkeypatch.setattr(anthropic_provider, "_get_client", lambda: client)
    monkeypatch.setattr(anthropic_provider, "_dispatch", dispatch)
    monkeypatch.setattr(anthropic_provider, "_tool_schemas", lambda enabled_extensions=None, roster=(): [])

    async def scenario():
        policy = questions.bind(questions.QuestionPolicy(enabled))
        approval = approvals.bind(approvals.ApprovalPolicy(approval_mode))
        try:
            return await anthropic_provider.run_chat("which?", [], request_id=REQUEST, on_event=recorder)
        finally:
            approvals.reset(approval)
            questions.reset(policy)

    return run(scenario()), client


def test_anthropic_asks_the_user_and_feeds_the_answers_back(monkeypatch) -> None:
    dispatch = Mock(return_value="never")
    rec = Recorder(answers=ANSWERS)

    result, client = anthropic_turn(monkeypatch, rec, dispatch)

    assert result.response == "Done"
    dispatch.assert_not_called()
    steps = [t for t in rec.types() if t in ("step_start", "question_request", "question_resolved", "step_end")]
    assert steps == ["step_start", "question_request", "question_resolved", "step_end"]
    expected = questions.format_answers(QUESTIONS, ANSWERS)
    sent = client.messages.stream.call_args_list[1].kwargs["messages"][-1]["content"][0]
    assert sent["content"] == expected
    assert result.tool_calls[0].result == expected


def test_anthropic_is_not_gated_by_tool_approval(monkeypatch) -> None:
    rec = Recorder(answers=ANSWERS)

    anthropic_turn(monkeypatch, rec, Mock(), approval_mode="ask")

    assert "approval_request" not in rec.types()


def test_anthropic_refuses_the_tool_when_it_was_not_offered(monkeypatch) -> None:
    rec = Recorder()

    result, _ = anthropic_turn(monkeypatch, rec, Mock(), enabled=False)

    assert "question_request" not in rec.types()
    assert result.tool_calls[0].result == questions.NOT_OFFERED


def test_anthropic_stop_while_a_question_is_open_cancels_the_turn(monkeypatch) -> None:
    rec = Recorder()

    async def stopper(event: dict) -> None:
        await rec(event)
        if event["type"] == "question_request":
            asyncio.get_running_loop().call_later(0.05, cancellation.cancel, REQUEST)

    with pytest.raises(ChatCancelled):
        anthropic_turn(monkeypatch, stopper, Mock())

    assert rec.types()[-1] == "step_end"


def test_anthropic_offers_the_schema_only_when_enabled() -> None:
    with patch("src.llm.anthropic_provider.list_tools", return_value=[]):
        off = anthropic_provider._tool_schemas([], ())
        token = questions.bind(questions.QuestionPolicy(True))
        try:
            on = anthropic_provider._tool_schemas([], ())
        finally:
            questions.reset(token)

    assert [s["name"] for s in off if s["name"] == "ask_user"] == []
    assert [s["name"] for s in on if s["name"] == "ask_user"] == [ask_user.TOOL_NAME]
    assert on[0]["input_schema"] == ask_user.tool_parameters()


def _openai_client(arguments):
    import json

    def stream_cm(deltas, final):
        events = [SimpleNamespace(type="response.output_text.delta", delta=text) for text in deltas]

        async def _aiter():
            for event in events:
                yield event

        stream = MagicMock()
        stream.__aiter__ = Mock(return_value=_aiter())
        stream.get_final_response = AsyncMock(return_value=final)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=stream)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    call = SimpleNamespace(
        type="function_call", call_id="call-1", name=ask_user.TOOL_NAME, arguments=json.dumps(arguments)
    )
    one = SimpleNamespace(usage=SimpleNamespace(total_tokens=10), output=[call])
    two = SimpleNamespace(usage=SimpleNamespace(total_tokens=2), output=[], output_text="Done")
    return SimpleNamespace(responses=SimpleNamespace(stream=Mock(side_effect=[stream_cm([], one), stream_cm(["Done"], two)])))


def openai_turn(monkeypatch, recorder, enabled=True):
    monkeypatch.setenv("GPT_API_KEY", "sk-test")
    dispatch = Mock(return_value="never")

    async def scenario():
        policy = questions.bind(questions.QuestionPolicy(enabled))
        try:
            with patch("src.llm.openai_provider._get_client", return_value=_openai_client(ASK_ARGUMENTS)), \
                 patch("src.llm.openai_provider._dispatch", dispatch), \
                 patch("src.llm.openai_provider.list_tools", return_value=[]):
                return await openai_provider.run_chat("which?", [], request_id=REQUEST, on_event=recorder)
        finally:
            questions.reset(policy)

    return run(scenario()), dispatch


def test_openai_asks_the_user_and_feeds_the_answers_back(monkeypatch) -> None:
    rec = Recorder(answers=ANSWERS)

    result, dispatch = openai_turn(monkeypatch, rec)

    assert result.response == "Done"
    dispatch.assert_not_called()
    request = [e for e in rec.events if e["type"] == "question_request"][0]
    assert (request["id"], request["questions"]) == ("call-1", QUESTIONS)
    assert result.tool_calls[0].result == questions.format_answers(QUESTIONS, ANSWERS)


def test_openai_refuses_the_tool_when_it_was_not_offered(monkeypatch) -> None:
    rec = Recorder()

    result, _ = openai_turn(monkeypatch, rec, enabled=False)

    assert "question_request" not in rec.types()
    assert result.tool_calls[0].result == questions.NOT_OFFERED


def test_openai_offers_the_schema_only_when_enabled() -> None:
    with patch("src.llm.openai_provider.list_tools", return_value=[]):
        off = openai_provider._tool_schemas([], ())
        token = questions.bind(questions.QuestionPolicy(True))
        try:
            on = openai_provider._tool_schemas([], ())
        finally:
            questions.reset(token)

    assert [s["name"] for s in off if s["name"] == "ask_user"] == []
    assert [s["name"] for s in on if s["name"] == "ask_user"] == [ask_user.TOOL_NAME]
    assert on[0]["parameters"] == ask_user.tool_parameters()


# --- ask() / answer_question / agent_config ------------------------------------------------------------


def _result() -> ChatResult:
    return ChatResult(response="ok", provider_id="anthropic", model="m", total_tokens=1)


def _ask_kwargs(**arguments) -> dict:
    async def scenario():
        with patch("src.server.agent_config.run_chat", new_callable=AsyncMock, return_value=_result()) as run_chat, \
             patch("src.server.agent_config.status", return_value={"context_window": 1, "model": "m"}):
            await server.ask("q", request_id="r", **arguments)
        return run_chat.call_args.kwargs

    return run(scenario())


def test_ask_passes_ask_user_on_and_defaults_it_off() -> None:
    assert _ask_kwargs(ask_user=True)["ask_user"] is True
    assert _ask_kwargs()["ask_user"] is False


def test_run_chat_enables_the_policy_for_a_top_level_turn_only() -> None:
    from src.agents import agent_config

    seen: list[bool] = []

    async def fake_provider_run_chat(*args, **kwargs):
        seen.append(questions.current().enabled)
        return _result()

    with patch.object(agent_config._PROVIDER_MODULE, "run_chat", fake_provider_run_chat):
        run(agent_config.run_chat("q", [], [], request_id=REQUEST, ask_user=True))
        run(agent_config.run_chat("q", [], [], request_id=REQUEST, ask_user=False))
        run(agent_config.run_chat("q", [], [], request_id=REQUEST, depth=1, ask_user=True))

    assert seen == [True, False, False]
    assert questions.current().enabled is False


def test_answer_question_answers_a_pending_question() -> None:
    async def scenario():
        waiter = asyncio.create_task(questions.BROKER.wait(REQUEST, "s1"))
        await asyncio.sleep(0)
        answered = await server.answer_question(REQUEST, "s1", ANSWERS, False)
        return answered, await waiter

    answered, answer = run(scenario())

    assert answered == {"answered": True}
    assert (answer.outcome, list(answer.answers)) == ("answered", ANSWERS)


def test_answer_question_can_skip_and_reports_when_nothing_is_waiting() -> None:
    async def scenario():
        waiter = asyncio.create_task(questions.BROKER.wait(REQUEST, "s1"))
        await asyncio.sleep(0)
        skipped = await server.answer_question(REQUEST, "s1", None, True)
        return skipped, (await waiter).outcome, await server.answer_question(REQUEST, "s1", None, True)

    assert run(scenario()) == ({"answered": True}, "skipped", {"answered": False})


def test_status_says_questions_are_understood() -> None:
    with patch("src.server.agent_config.status", return_value={"available": True}):
        assert server.status()["user_questions"] is True
