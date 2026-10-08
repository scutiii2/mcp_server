from __future__ import annotations

import asyncio

from src.services import suggestions
from src.services.agent_gateway import Caller
from tests.conftest import FakeAgent

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
