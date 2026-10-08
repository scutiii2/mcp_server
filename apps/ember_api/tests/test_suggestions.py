from __future__ import annotations

import asyncio

from src.services import suggestions
from src.services.agent_gateway import Caller
from fastapi.testclient import TestClient

from tests.conftest import FakeAgent, FakeEmailSender
from tests.test_admin import login, make_member
from tests.test_registration import as_admin
from tests.test_turns import AGENT_ID, chat as get_chat, new_id, start, wait_until

CALLER = Caller(username="alice", email="alice@example.com")


def run(agent: FakeAgent, question: str = "Who wrote Dune?", answer: str = "Frank Herbert."):
    return asyncio.run(suggestions.suggest(agent, "http://agent", CALLER, question, answer))


# --- suggest ---------------------------------------------------------------------


def test_returns_the_cleaned_one_line_suggestion(agent: FakeAgent) -> None:
    agent.summary = '  "Who wrote the sequel?"\nBecause that is next.  '

    outcome = run(agent)

    assert outcome is not None
    assert outcome.text == "Who wrote the sequel?"
    assert outcome.result["total_tokens"] == 10
    sent = agent.interprets[0]
    assert "Who wrote Dune?" in sent and "Frank Herbert." in sent


def test_none_and_empty_replies_mean_no_suggestion_but_keep_the_usage(agent: FakeAgent) -> None:
    for reply in ("NONE", "none.", "", "   "):
        agent.summary = reply
        outcome = run(agent)
        assert outcome is not None and outcome.text is None, reply
        assert outcome.result["total_tokens"] == 10


def test_collapses_whitespace_and_caps_the_length(agent: FakeAgent) -> None:
    agent.summary = "tell   me\tmore"
    assert run(agent).text == "tell me more"

    agent.summary = "word " * 100
    text = run(agent).text
    assert text is not None and len(text) <= suggestions.SUGGESTION_MAX


def test_an_agent_failure_is_none(agent: FakeAgent) -> None:
    agent.fail = "agent down"

    assert run(agent) is None


def test_the_prompt_keeps_the_start_of_the_question_and_the_end_of_the_answer(agent: FakeAgent) -> None:
    question = "Q" * 5000 + "END_OF_QUESTION"
    answer = "START_OF_ANSWER" + "A" * 5000

    prompt = suggestions.build_prompt(question, answer)

    assert "END_OF_QUESTION" not in prompt and "START_OF_ANSWER" not in prompt
    assert prompt.count("Q") <= suggestions.EXCHANGE_MAX + 50
    assert prompt.count("A") <= suggestions.EXCHANGE_MAX + 50


# --- last_exchange ---------------------------------------------------------------

ASK = {"role": "user", "content": "What is the capital of France?"}
REPLY = {"role": "assistant", "content": "Paris."}


def test_last_exchange_is_the_final_plain_pair() -> None:
    earlier = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]

    assert suggestions.last_exchange([*earlier, ASK, REPLY]) == ("What is the capital of France?", "Paris.")


def test_last_exchange_is_none_when_there_is_nothing_to_follow_up() -> None:
    cases = {
        "empty": [],
        "only a question": [ASK],
        "ends on a question": [REPLY, ASK],
        "question too short": [{"role": "user", "content": "hi"}, REPLY],
        "empty answer": [ASK, {"role": "assistant", "content": "  "}],
        "an error answer": [ASK, {"role": "assistant", "content": "error: the agent is down"}],
        "a cancelled answer": [ASK, {"role": "assistant", "content": "⏹️ Cancelled."}],
        "a cancelled answer from the agent": [ASK, {"role": "assistant", "content": "Cancelled."}],
        "an interrupted answer": [ASK, {"role": "assistant", "content": "partial\n\n⚠️ Interrupted: ember_api stopped before the answer finished."}],
        "a slash command": [{**ASK, "kind": "command"}, {**REPLY, "kind": "command"}],
        "a summary": [{"role": "assistant", "kind": "summary", "content": "S"}, {"role": "assistant", "kind": "log_attachment", "content": "L"}],
    }
    for name, messages in cases.items():
        assert suggestions.last_exchange(messages) is None, name


# --- cache -----------------------------------------------------------------------


def test_cache_remembers_a_miss_and_a_none_and_forgets_the_oldest() -> None:
    cache = suggestions.SuggestionCache(size=2)
    assert cache.lookup("a") == (False, None)

    cache.put("a", "first")
    cache.put("b", None)
    assert cache.lookup("a") == (True, "first")
    assert cache.lookup("b") == (True, None)

    cache.put("c", "third")  # lookup order was a, b: "a" is the least recently used

    assert cache.lookup("c") == (True, "third")
    assert cache.lookup("b") == (True, None)
    assert cache.lookup("a") == (False, None)


# --- GET /api/chats/{id}/suggestion -------------------------------------------------


def seed(client: TestClient, chat_id: str, question: str = "What is the capital of France?", answer: str = "Paris.") -> None:
    messages = [{"role": "user", "content": question}]
    if answer:
        messages.append({"role": "assistant", "content": answer})
    response = client.put(
        f"/api/chats/{chat_id}", json={"title": "t", "agent_id": AGENT_ID, "messages": messages}
    )
    assert response.status_code == 200, response.text


def suggestion(client: TestClient, chat_id: str):
    return client.get(f"/api/chats/{chat_id}/suggestion")


def test_suggestion_needs_login(client: TestClient) -> None:
    assert suggestion(client, new_id()).status_code == 401


def test_suggestion_needs_chat_use(client: TestClient, email: FakeEmailSender) -> None:
    make_member(client, email, verify=False)
    login(client, "alice")

    assert suggestion(client, new_id()).status_code == 403


def test_suggestion_of_an_unknown_or_foreign_chat_is_404(client: TestClient, email: FakeEmailSender) -> None:
    as_admin(client)
    chat_id = new_id()
    seed(client, chat_id)
    assert suggestion(client, new_id()).status_code == 404
    make_member(client, email)  # logs the admin out
    login(client, "alice")

    assert suggestion(client, chat_id).status_code == 404


def test_suggests_after_an_answer_records_usage_and_asks_only_once(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    seed(client, chat_id)
    agent.summary = "And what about Germany?"

    first = suggestion(client, chat_id)

    assert first.status_code == 200
    assert first.json() == {"text": "And what about Germany?"}
    assert "What is the capital of France?" in agent.interprets[0]
    rows = client.get("/api/usage/records").json()
    assert [r["kind"] for r in rows] == ["suggestion"]
    assert rows[0]["chat_id"] == chat_id
    # Reopening the chat asks nobody and costs nothing.
    assert suggestion(client, chat_id).json() == {"text": "And what about Germany?"}
    assert len(agent.interprets) == 1
    assert len(client.get("/api/usage/records").json()) == 1


def test_suggests_for_an_answer_written_by_a_real_turn(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    agent.summary = "Tell me more"
    start(client, chat_id, "hi there")
    wait_until(lambda: not get_chat(client, chat_id)["running"])

    assert suggestion(client, chat_id).json() == {"text": "Tell me more"}


def test_a_new_answer_gets_a_new_suggestion(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    seed(client, chat_id)
    agent.summary = "first"
    assert suggestion(client, chat_id).json() == {"text": "first"}
    seed(client, chat_id, question="And Spain?", answer="Madrid.")
    agent.summary = "second"

    assert suggestion(client, chat_id).json() == {"text": "second"}


def test_no_call_when_the_account_switched_suggestions_off(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    seed(client, chat_id)
    client.patch("/api/account/preferences", json={"prompt_suggestions": False})

    assert suggestion(client, chat_id).json() == {"text": None}
    assert agent.interprets == []


def test_no_call_while_an_answer_is_running(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    agent.hold = True
    start(client, chat_id, "a long question")
    wait_until(lambda: len(agent.asks) == 1)

    assert suggestion(client, chat_id).json() == {"text": None}
    assert agent.interprets == []
    agent.release()
    wait_until(lambda: not get_chat(client, chat_id)["running"])


def test_no_call_when_there_is_nothing_to_follow_up(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    cases = {
        "no answer yet": dict(answer=""),
        "a question too short": dict(question="hi"),
        "an error answer": dict(answer="error: the agent is down"),
        "a cancelled answer": dict(answer="⏹️ Cancelled."),
    }
    for name, kwargs in cases.items():
        chat_id = new_id()
        seed(client, chat_id, **kwargs)

        assert suggestion(client, chat_id).json() == {"text": None}, name
    assert agent.interprets == []


def test_a_failing_agent_gives_no_suggestion_and_no_error(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    seed(client, chat_id)
    agent.fail = "agent down"

    response = suggestion(client, chat_id)

    assert response.status_code == 200
    assert response.json() == {"text": None}
    assert client.get("/api/usage/records").json() == []
    # Not remembered: the next try may work.
    agent.fail = None
    agent.summary = "back again"
    assert suggestion(client, chat_id).json() == {"text": "back again"}


def test_a_none_reply_is_no_suggestion_but_is_accounted_for(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    seed(client, chat_id)
    agent.summary = "NONE"

    assert suggestion(client, chat_id).json() == {"text": None}
    assert [r["kind"] for r in client.get("/api/usage/records").json()] == ["suggestion"]
    assert suggestion(client, chat_id).json() == {"text": None}
    assert len(agent.interprets) == 1


def test_no_suggestion_without_a_running_agent(client: TestClient, agent: FakeAgent, tmp_path) -> None:
    as_admin(client)
    chat_id = new_id()
    seed(client, chat_id)
    (tmp_path / "config_agents.json").write_text('{"agents": []}', encoding="utf-8")

    assert suggestion(client, chat_id).json() == {"text": None}
    assert agent.interprets == []
