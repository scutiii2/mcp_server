"""Clickable questions: the clamping and checking helpers, the turn's pending
question and snapshot, and (Task 4) the answer route."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from src.services import question_answers as qa
from tests.conftest import FakeAgent
from tests.test_registration import as_admin
from tests.test_turns import events, new_id, start, wait_until

QUESTIONS = [
    {
        "header": "Format",
        "question": "Which format?",
        "multi_select": False,
        "options": [{"label": "CSV"}, {"label": "JSON", "description": "Structured"}],
    },
    {
        "header": "Extras",
        "question": "Which extras?",
        "multi_select": True,
        "options": [{"label": "Totals"}, {"label": "Chart"}, {"label": "Title"}],
    },
]


# --- clamp_questions -------------------------------------------------------------------


def test_clamp_keeps_a_good_request_as_it_is() -> None:
    assert qa.clamp_questions(QUESTIONS) == QUESTIONS


def test_clamp_cuts_long_text_and_extra_questions_and_options() -> None:
    raw = [
        {
            "header": "h" * 40,
            "question": "q" * 500,
            "multi_select": "truthy",
            "options": [{"label": "l" * 200, "description": "d" * 400}] + [{"label": f"o{i}"} for i in range(8)],
        }
    ] * 6

    clamped = qa.clamp_questions(raw)

    assert len(clamped) == qa.MAX_QUESTIONS
    first = clamped[0]
    assert len(first["header"]) == qa.HEADER_MAX and len(first["question"]) == qa.QUESTION_MAX
    assert first["multi_select"] is True
    assert len(first["options"]) == qa.MAX_OPTIONS
    assert len(first["options"][0]["label"]) == qa.LABEL_MAX
    assert len(first["options"][0]["description"]) == qa.DESCRIPTION_MAX


def test_clamp_drops_anything_that_is_not_a_question() -> None:
    assert qa.clamp_questions("nope") == []
    assert qa.clamp_questions([1, None, {"header": "x"}]) == []
    assert qa.clamp_questions([{"header": "x", "question": "y", "options": ["A", {"label": "B"}, {"nolabel": 1}]}]) == [
        {"header": "x", "question": "y", "multi_select": False, "options": [{"label": "B"}]}
    ]


# --- check_answers ---------------------------------------------------------------------


def ok(selected, other=None):
    return {"selected": selected, "other": other}


def test_a_complete_answer_passes() -> None:
    assert qa.check_answers(QUESTIONS, [ok(["CSV"]), ok(["Totals", "Chart"], "and a title")]) is None


def test_other_alone_is_an_answer() -> None:
    assert qa.check_answers(QUESTIONS, [ok([], "XML"), ok(["Title"])]) is None


def test_bad_answers_are_described() -> None:
    cases = {
        "too few answers": [ok(["CSV"])],
        "too many answers": [ok(["CSV"]), ok(["Chart"]), ok(["Title"])],
        "nothing chosen": [ok([]), ok(["Chart"])],
        "blank other only": [ok([], "   "), ok(["Chart"])],
        "an unknown label": [ok(["XML"]), ok(["Chart"])],
        "two for a single-select": [ok(["CSV", "JSON"]), ok(["Chart"])],
        "the same label twice": [ok(["CSV"]), ok(["Chart", "Chart"])],
    }
    for name, answers in cases.items():
        problem = qa.check_answers(QUESTIONS, answers)
        assert isinstance(problem, str) and problem, name


# --- the turn: events, pending question, snapshot ----------------------------------------------


def waiting_question(client: TestClient, agent: FakeAgent, chat_id: str) -> None:
    """Starts a turn whose agent asks QUESTIONS and waits for the answer."""
    agent.questions = QUESTIONS
    start(client, chat_id, "which format?", can_ask=True)
    wait_until(lambda: bool(agent._asking))


def test_the_agent_is_told_the_browser_can_ask_only_when_it_says_so(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)

    start(client, new_id(), "plain")
    wait_until(lambda: len(agent.asks) == 1)
    start(client, new_id(), "asking", can_ask=True)
    wait_until(lambda: len(agent.asks) == 2)

    assert [a["ask_user"] for a in agent.asks] == [False, True]


def test_a_waiting_question_is_part_of_the_snapshot_and_clears_when_answered(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    waiting_question(client, agent, chat_id)
    registry = client.app.state.turns
    account_id = client.get("/api/auth/me").json()["id"]
    turn = registry.get(account_id, chat_id)

    assert turn.snapshot()["questions"] == [{"id": "q1", "questions": QUESTIONS}]
    assert registry.pending_question(account_id, chat_id, "q1") == {"id": "q1", "questions": QUESTIONS}
    assert registry.pending_question(account_id, chat_id, "other") is None

    answered = asyncio.run_coroutine_threadsafe(
        registry.answer(account_id, chat_id, "q1", [{"selected": ["CSV"], "other": None}], False), agent.loop
    ).result(5)
    wait_until(lambda: not turn.pending_questions)

    assert answered is True
    assert agent.answers[0][1:] == ("q1", [{"selected": ["CSV"], "other": None}], False)
    assert turn.snapshot()["questions"] == []
    wait_until(lambda: turn.status != "running")


def test_an_oversized_question_is_cut_down_before_it_is_shown(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    agent.questions = [
        {"header": "h" * 40, "question": "q" * 900, "multi_select": False, "options": [{"label": "A"}, {"label": "B"}]}
    ]
    start(client, chat_id, "go", can_ask=True)
    wait_until(lambda: bool(agent._asking))
    registry = client.app.state.turns
    account_id = client.get("/api/auth/me").json()["id"]

    shown = registry.pending_question(account_id, chat_id, "q1")["questions"][0]

    assert len(shown["header"]) == qa.HEADER_MAX and len(shown["question"]) == qa.QUESTION_MAX
