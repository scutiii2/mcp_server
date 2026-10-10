import asyncio

import pytest

from src.laya_client import LayaClient, LayaError, choice_question, noul_question, score_question
from tests.fake_laya import FakeEngine

OPTIONS = {"a": "first", "b": "second", "c": "third"}
LEVELS = ["low", "mid", "high"]
QUESTIONS = {
    "level": score_question("How high?", LEVELS),
    "yes": noul_question("Is it so?", "No.", "Yes."),
    "pick": choice_question("Which?", OPTIONS),
}


def ask(client, text="A short text.", questions=None):
    return asyncio.run(client.ask(text, QUESTIONS if questions is None else questions))


def test_all_three_question_types_are_answered():
    answers = ask(LayaClient(FakeEngine(pick="b", scores={"level": 1.7}, noul={"yes": 0.25})))
    assert answers["level"].value == 1.7 and answers["level"].kind == "score"
    assert answers["yes"].value == 0.25 and answers["yes"].kind == "noul"
    assert answers["pick"].value == "b" and answers["pick"].confidence == 0.9
    assert not any(a.uncertain for a in answers.values())


def test_low_confidence_is_flagged_uncertain_per_answer():
    answers = ask(LayaClient(FakeEngine(confidence=0.5)))
    assert all(a.uncertain for a in answers.values())


def test_min_confidence_comes_from_the_client():
    assert ask(LayaClient(FakeEngine(confidence=0.8), min_confidence=0.9))["pick"].uncertain is True


def test_choose_returns_the_chosen_key():
    answer = asyncio.run(LayaClient(FakeEngine(pick="c")).choose("Text.", "Which?", OPTIONS))
    assert (answer.value, answer.uncertain) == ("c", False)


def test_questions_are_sent_to_the_engine_unchanged():
    engine = FakeEngine()
    ask(LayaClient(engine))
    text, sent = engine.calls[0]
    assert text == "A short text." and sent == QUESTIONS


@pytest.mark.parametrize("questions", [
    {},
    {f"q{i}": noul_question("Q?", "n", "y") for i in range(9)},
    {"x": {"type": "weird", "instructions": "?", "criteria": {}}},
    {"x": choice_question("Which?", {"only": "one"})},
    {"x": score_question("How?", ["just one"])},
    {"x": {"type": "noul", "instructions": "?", "criteria": {"yes": "a", "no": "b"}}},
    {"": noul_question("Q?", "n", "y")},
])
def test_invalid_questions_are_rejected_before_the_model(questions):
    engine = FakeEngine()
    with pytest.raises(LayaError):
        ask(LayaClient(engine), questions=questions)
    assert engine.calls == []


@pytest.mark.parametrize("text", ["", "   ", "x" * 4001])
def test_text_length_is_checked(text):
    with pytest.raises(LayaError, match="characters"):
        ask(LayaClient(FakeEngine()), text=text)


def test_truncated_input_is_rejected():
    with pytest.raises(LayaError, match="complete input"):
        ask(LayaClient(FakeEngine(usage={"truncated": True})))


@pytest.mark.parametrize("raw", [
    {"level": {"score": 9, "answer_confidence": 0.9}},
    {"level": {"score": float("nan"), "answer_confidence": 0.9}},
    {"level": {"score": 1, "answer_confidence": 2}},
    {"yes": {"noul": 1.5, "answer_confidence": 0.9}},
    {"pick": {"choice": "z", "probabilities": {"a": 1, "b": 0, "c": 0}, "answer_confidence": 0.9}},
    {"pick": {"choice": "a", "probabilities": {"a": 1}, "answer_confidence": 0.9}},
    {"pick": {"choice": "a"}},
])
def test_invalid_engine_output_is_rejected(raw):
    with pytest.raises(LayaError, match="invalid result"):
        ask(LayaClient(FakeEngine(raw=raw)))


def test_engine_exceptions_become_laya_errors():
    with pytest.raises(LayaError, match="Laya failed: engine failure"):
        ask(LayaClient(FakeEngine(fail=True)))


def test_timeout_raises_laya_error():
    with pytest.raises(LayaError, match="timed out"):
        ask(LayaClient(FakeEngine(delay=0.5), timeout=0.05))


def test_missing_package_is_unavailable_and_raises():
    client = LayaClient()
    if client.is_available():
        pytest.skip("laya is installed here")
    with pytest.raises(LayaError, match="optional dependency"):
        ask(client)


def test_injected_engine_counts_as_available():
    assert LayaClient(FakeEngine()).is_available() is True
