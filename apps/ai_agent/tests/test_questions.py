"""questions.py: asking the user clickable questions - the policy, the broker that
waits for the answer, the ask()/handle() helpers the providers call, and both
providers' tool loops. Plain sync tests around asyncio.run(), like test_approvals.py."""

from __future__ import annotations

import asyncio

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
