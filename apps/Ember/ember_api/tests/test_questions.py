"""Clickable questions: the clamping and checking helpers, the turn's pending
question and snapshot, and (Task 4) the answer route."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from src.services import question_answers as qa
from tests.conftest import FakeAgent, FakeEmailSender
from tests.test_admin import login, make_member
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


# --- POST /api/chats/{id}/questions ----------------------------------------------------------------


def answer(client: TestClient, chat_id: str, **body):
    return client.post(f"/api/chats/{chat_id}/questions", json={"step_id": "q1", **body})


GOOD = [ok(["CSV"]), ok(["Totals", "Chart"], "and a title")]


def test_answering_needs_login(client: TestClient) -> None:
    assert answer(client, new_id(), skipped=True).status_code == 401


def test_answering_needs_chat_use(client: TestClient, email: FakeEmailSender) -> None:
    make_member(client, email, verify=False)
    login(client, "alice")

    assert answer(client, new_id(), skipped=True).status_code == 403


def test_answering_with_no_running_answer_is_404(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)

    assert answer(client, new_id(), skipped=True).status_code == 404


def test_answering_a_question_that_is_not_waiting_is_409(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    agent.hold = True
    start(client, chat_id, "no question here")
    wait_until(lambda: len(agent.asks) == 1)

    assert answer(client, chat_id, skipped=True).status_code == 409
    agent.release()


def test_a_valid_answer_reaches_the_agent_and_lets_the_turn_finish(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    waiting_question(client, agent, chat_id)

    response = answer(client, chat_id, answers=GOOD)

    assert response.status_code == 200
    assert response.json() == {"answered": True}
    assert agent.answers[0][1:] == ("q1", GOOD, False)
    stream = events(client, chat_id)
    assert [e["type"] for e in stream if e["type"] in ("question_resolved", "final")] == ["question_resolved", "final"]
    assert next(e for e in stream if e["type"] == "question_resolved")["outcome"] == "answered"


def test_skipping_needs_no_answers(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    waiting_question(client, agent, chat_id)

    response = answer(client, chat_id, skipped=True)

    assert response.status_code == 200
    assert agent.answers[0][1:] == ("q1", [], True)
    stream = events(client, chat_id)
    assert next(e for e in stream if e["type"] == "question_resolved")["outcome"] == "skipped"


def test_an_invalid_answer_is_422_and_changes_nothing(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    waiting_question(client, agent, chat_id)
    bad = {
        "too few": [ok(["CSV"])],
        "unknown label": [ok(["XML"]), ok(["Chart"])],
        "two for a single-select": [ok(["CSV", "JSON"]), ok(["Chart"])],
        "nothing chosen": [ok([]), ok(["Chart"])],
    }

    for name, answers in bad.items():
        response = answer(client, chat_id, answers=answers)
        assert response.status_code == 422, name
        assert response.json()["detail"], name
    assert agent.answers == []
    assert answer(client, chat_id, answers=GOOD).status_code == 200  # still waiting, and answerable


def test_body_limits_are_enforced(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    waiting_question(client, agent, chat_id)

    too_long = [ok(["CSV"], "x" * (qa.OTHER_MAX + 1)), ok(["Chart"])]
    assert answer(client, chat_id, answers=too_long).status_code == 422
    assert client.post(f"/api/chats/{chat_id}/questions", json={"skipped": True}).status_code == 422
    assert client.post(f"/api/chats/{chat_id}/questions", json={"step_id": "q1", "answers": "x"}).status_code == 422
    assert agent.answers == []
    answer(client, chat_id, skipped=True)


def test_a_second_answer_to_the_same_question_is_409(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    waiting_question(client, agent, chat_id)
    assert answer(client, chat_id, answers=GOOD).status_code == 200
    events(client, chat_id)  # the turn is over

    assert answer(client, chat_id, answers=GOOD).status_code in (404, 409)


def test_the_agent_saying_nothing_is_waiting_is_409(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    waiting_question(client, agent, chat_id)
    agent.answer_result = False

    assert answer(client, chat_id, answers=GOOD).status_code == 409
    agent.answer_result = None
    answer(client, chat_id, skipped=True)


def test_an_unreachable_agent_is_502(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    waiting_question(client, agent, chat_id)
    agent.answer_error = "agent down"

    assert answer(client, chat_id, answers=GOOD).status_code == 502
    agent.answer_error = None
    answer(client, chat_id, skipped=True)


def test_another_account_cannot_answer(client: TestClient, agent: FakeAgent, email: FakeEmailSender) -> None:
    as_admin(client)
    chat_id = new_id()
    waiting_question(client, agent, chat_id)
    make_member(client, email)
    login(client, "alice")

    assert answer(client, chat_id, skipped=True).status_code == 404
