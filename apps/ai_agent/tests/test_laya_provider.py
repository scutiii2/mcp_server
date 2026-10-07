"""The local triage provider never generates text or calls another model."""

import asyncio
import copy

import pytest

from src.llm import laya_provider
from src.llm.base_provider import ChatCancelled


def prediction(category="database", severity="warning", investigation=0.9, confidence=0.9):
    return {
        "answers": {
            "category": {"choice": category, "answer_confidence": confidence},
            "severity": {"choice": severity, "answer_confidence": confidence},
            "needs_investigation": {"noul": investigation, "answer_confidence": confidence},
        },
        "usage": {"input_tokens": 120, "output_tokens": 0, "state_tokens": 12, "truncated": False},
    }


class FakeEngine:
    def __init__(self, result=None, error=None):
        self.result = result if result is not None else prediction()
        self.error = error
        self.calls = []

    def predict(self, state, questions, **kwargs):
        self.calls.append((state, questions, kwargs))
        if self.error:
            raise self.error
        return copy.deepcopy(self.result)


@pytest.fixture
def engine(monkeypatch):
    fake = FakeEngine()
    monkeypatch.setattr(laya_provider, "_triage", laya_provider.LayaTriage(fake))
    return fake


def ask(text="SQLite database is locked", **kwargs):
    return asyncio.run(laya_provider.run_chat(text, [], None, [], **kwargs))


def test_fixed_result_and_real_inference_token_usage(engine):
    result = ask()
    assert "Category: Database" in result.response
    assert "Severity: Warning" in result.response
    assert "Needs investigation: Yes" in result.response
    assert "Uncertain: No" in result.response
    assert result.provider_id == "laya"
    assert result.model == "convaiinnovations/laya"
    assert result.input_tokens == result.total_tokens == 120
    assert result.output_tokens == 0
    assert result.tools_used == result.tool_calls == []
    assert engine.calls[0][0] == "SQLite database is locked"
    assert engine.calls[0][2]["max_len"] == 512


def test_low_confidence_is_flagged_without_changing_the_prediction(engine):
    engine.result = prediction(confidence=0.4)
    result = ask()
    assert "Category: Database" in result.response
    assert "Uncertain: Yes" in result.response
    assert "human review" in result.response


def test_unknown_category_is_uncertain_even_with_high_confidence(engine):
    engine.result = prediction(category="unknown", confidence=0.99)
    assert "Uncertain: Yes" in ask().response


def test_investigation_probability_below_half_returns_no(engine):
    engine.result = prediction(investigation=0.1)
    assert "Needs investigation: No" in ask().response


@pytest.mark.parametrize("text", ["", "   ", "x" * 4001])
def test_invalid_input_is_rejected_before_inference(engine, text):
    with pytest.raises(ValueError, match="short|empty"):
        ask(text)
    assert not engine.calls


def test_truncated_input_is_not_reported_as_a_classification(engine):
    engine.result["usage"]["truncated"] = True
    with pytest.raises(ValueError, match="shorter excerpt"):
        ask()


@pytest.mark.parametrize("field,value", [
    ("category", {"choice": "invented", "answer_confidence": 0.9}),
    ("severity", {"choice": "critical", "answer_confidence": float("nan")}),
    ("needs_investigation", {"noul": 2, "answer_confidence": 0.9}),
])
def test_malformed_model_results_are_rejected(engine, field, value):
    engine.result["answers"][field] = value
    with pytest.raises(ValueError, match="Laya returned"):
        ask()


def test_inference_errors_propagate_without_a_fallback(engine):
    engine.error = RuntimeError("local model failed")
    with pytest.raises(RuntimeError, match="local model failed"):
        ask()
    assert len(engine.calls) == 1


def test_cancellation_is_checked_before_and_after_inference(engine, monkeypatch):
    monkeypatch.setattr(laya_provider.cancellation, "is_cancelled", lambda _: True)
    with pytest.raises(ChatCancelled):
        ask(request_id="cancelled")
    assert not engine.calls

    checks = iter([False, True])
    monkeypatch.setattr(laya_provider.cancellation, "is_cancelled", lambda _: next(checks))
    with pytest.raises(ChatCancelled):
        ask(request_id="during-inference")
    assert len(engine.calls) == 1


def test_history_and_extensions_do_not_change_the_classification_input(engine):
    result = asyncio.run(laya_provider.run_chat(
        "Connection refused", [{"role": "user", "content": "old issue"}], None,
        ["external-server"], caveman=True,
    ))
    assert engine.calls[0][0] == "Connection refused"
    assert result.tools_used == []


def test_interpret_does_not_claim_to_summarize_or_generate_text(engine):
    with pytest.raises(ValueError, match="does not support"):
        laya_provider.run_interpret("Summarize this conversation")
    assert not engine.calls


def test_other_model_ids_cannot_be_used(engine):
    with pytest.raises(ValueError, match="only supports"):
        asyncio.run(laya_provider.run_chat("issue", [], "gpt-x", []))
    assert not engine.calls
