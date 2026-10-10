"""Local Laya wrapper: typed questions about a short text.

A copy of the contract in ai_agent's laya_provider.py (projects never import
each other): `choice`, `score` and `noul` questions, validated answers, a
`uncertain` flag per answer. Lazy model load under a lock, inference in a
worker thread, and a timeout so a slow model never stalls a game turn. Laya
reads text only; it generates no text and is never trusted without its own
confidence flag.
"""

from __future__ import annotations

import asyncio
import importlib.util
import math
import threading
from dataclasses import dataclass
from typing import Any

DEFAULT_MODEL = "convaiinnovations/laya"
CONTEXT_WINDOW = 512
MAX_TEXT_CHARS = 4000
MAX_QUESTIONS = 8
MIN_OPTIONS, MAX_OPTIONS = 2, 10
_TYPES = ("choice", "score", "noul")
_NOUL_KEYS = {"false", "true"}


class LayaError(RuntimeError):
    """Laya failed, timed out, or returned something unusable."""


class LayaUnavailable(LayaError):
    """The optional `laya` package is not installed."""


@dataclass(frozen=True)
class LayaAnswer:
    """One validated answer. `value` is the chosen option key (choice), the
    score from 0 to len(levels) - 1 (score) or the yes probability (noul)."""

    kind: str
    value: Any
    confidence: float
    uncertain: bool


def choice_question(instructions: str, options: dict[str, str]) -> dict[str, Any]:
    return {"type": "choice", "instructions": instructions, "criteria": dict(options)}


def score_question(instructions: str, levels: list[str]) -> dict[str, Any]:
    """`levels` are descriptions, lowest first."""
    return {"type": "score", "instructions": instructions, "criteria": list(levels)}


def noul_question(instructions: str, false_text: str, true_text: str) -> dict[str, Any]:
    return {"type": "noul", "instructions": instructions, "criteria": {"false": false_text, "true": true_text}}


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _unit(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("invalid probability")
    return float(value)


def _check_question(qid: str, spec: Any) -> None:
    if not _is_text(qid) or not isinstance(spec, dict):
        raise LayaError("every question needs a non-empty id and an object")
    kind, criteria = spec.get("type"), spec.get("criteria")
    if kind not in _TYPES or not _is_text(spec.get("instructions")):
        raise LayaError(f"question {qid!r} needs a valid type and instructions")
    if kind == "choice":
        valid = (isinstance(criteria, dict) and MIN_OPTIONS <= len(criteria) <= MAX_OPTIONS
                 and all(_is_text(k) and _is_text(v) for k, v in criteria.items()))
    elif kind == "score":
        valid = (isinstance(criteria, list) and MIN_OPTIONS <= len(criteria) <= MAX_OPTIONS
                 and all(_is_text(v) for v in criteria))
    else:
        valid = isinstance(criteria, dict) and set(criteria) == _NOUL_KEYS and all(_is_text(v) for v in criteria.values())
    if not valid:
        raise LayaError(f"question {qid!r} ({kind}) has invalid criteria")


def _answer(spec: dict[str, Any], raw: dict[str, Any], min_confidence: float) -> LayaAnswer:
    confidence = _unit(raw["answer_confidence"])
    kind = spec["type"]
    if kind == "choice":
        key, probabilities = raw["choice"], raw["probabilities"]
        if key not in spec["criteria"] or set(probabilities) != set(spec["criteria"]):
            raise ValueError("unknown choice")
        for probability in probabilities.values():
            _unit(probability)
        value: Any = key
    elif kind == "score":
        score = raw["score"]
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) \
                or not 0 <= score <= len(spec["criteria"]) - 1:
            raise ValueError("invalid score")
        value = float(score)
    else:
        value = _unit(raw["noul"])
    return LayaAnswer(kind, value, confidence, confidence < min_confidence)


class LayaClient:
    """Engine injection (`engine=`) lets tests run without the real model."""

    def __init__(self, engine: Any = None, timeout: float = 2.0, min_confidence: float = 0.7) -> None:
        self._engine = engine
        self._timeout = timeout
        self._min_confidence = min_confidence
        self._lock = threading.Lock()

    def is_available(self) -> bool:
        return self._engine is not None or importlib.util.find_spec("laya") is not None

    def _load(self) -> Any:
        # Called only while holding _lock, including during inference.
        if self._engine is None:
            try:
                import laya
            except ImportError as error:
                raise LayaUnavailable('Laya needs the optional dependency: pip install -e ".[laya]"') from error
            self._engine = laya.load(DEFAULT_MODEL)
        return self._engine

    def prepare(self) -> None:
        """Warm the model so the first game turn is not slow."""
        with self._lock:
            self._load()

    def _ask_sync(self, text: str, questions: dict[str, dict[str, Any]]) -> dict[str, LayaAnswer]:
        if not 1 <= len(questions) <= MAX_QUESTIONS:
            raise LayaError(f"ask 1 to {MAX_QUESTIONS} questions at once")
        for qid, spec in questions.items():
            _check_question(qid, spec)
        if not text.strip() or len(text) > MAX_TEXT_CHARS:
            raise LayaError(f"text must be 1 to {MAX_TEXT_CHARS} characters")
        try:
            with self._lock:
                prediction = self._load().predict(text, questions, max_len=CONTEXT_WINDOW)
        except LayaError:
            raise
        except Exception as error:  # the model library's own failures, whatever their type
            raise LayaError(f"Laya failed: {error}") from error
        try:
            usage = prediction.get("usage", {})
            if usage.get("truncated") or usage.get("state_tokens_dropped", 0):
                raise LayaError("Laya could not read the complete input")
            return {qid: _answer(spec, prediction["answers"][qid], self._min_confidence) for qid, spec in questions.items()}
        except LayaError:
            raise
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise LayaError("Laya returned an invalid result") from error

    async def ask(self, text: str, questions: dict[str, dict[str, Any]]) -> dict[str, LayaAnswer]:
        """All answers or a LayaError. Individual answers may be `uncertain`."""
        try:
            return await asyncio.wait_for(asyncio.to_thread(self._ask_sync, text, questions), self._timeout)
        except asyncio.TimeoutError as error:
            raise LayaError(f"Laya timed out after {self._timeout}s") from error

    async def choose(self, text: str, instructions: str, options: dict[str, str]) -> LayaAnswer:
        """One `choice` question; the answer's value is the chosen option key."""
        answers = await self.ask(text, {"choice": choice_question(instructions, options)})
        return answers["choice"]
