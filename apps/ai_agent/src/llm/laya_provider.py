"""Local, fixed-schema triage. No generated text, tool calls or LLM fallback."""

from __future__ import annotations

import importlib.util
import math
import threading
from typing import Any

import anyio.to_thread

from src.core.catalog import catalog
from src.llm import cancellation
from src.llm.base_provider import ChatCancelled, ChatResult, step_event

PROVIDER_ID = "laya"
DEFAULT_MODEL = "convaiinnovations/laya"
VENDOR_LABEL = "Laya (local)"
SUPPORTS_STREAMING = True
CONTEXT_WINDOW = 512
MAX_INPUT_CHARS = 4000
# An initial review gate, not a measured accuracy guarantee. Validate against
# representative local examples before using these classifications for actions.
MIN_CONFIDENCE = 0.7

QUESTIONS = {
    "category": {
        "type": "choice",
        "instructions": "Which category best describes this technical issue?",
        "criteria": {
            "database": "Database queries, storage, SQL, locking or data integrity errors.",
            "network": "Connections, DNS, timeouts, sockets or unreachable services.",
            "authentication": "Login, identity, credentials, authorization or access denied.",
            "configuration": "Missing or incorrect settings, environment variables or setup.",
            "unknown": "No technical issue, insufficient evidence, or none of these categories fits.",
        },
    },
    "severity": {
        "type": "choice",
        "instructions": "How severe is the issue described? Do not assume unstated impact.",
        "criteria": {
            "informational": "Normal operation or an informational event without a problem.",
            "warning": "An error or degraded operation without evidence of a critical incident.",
            "critical": "An explicit service outage, data loss, security breach or complete failure.",
        },
    },
    "needs_investigation": {
        "type": "noul",
        "instructions": "Does this text describe a technical problem that needs investigation?",
        "criteria": {"false": "Normal operation; no technical problem.", "true": "A failure or problem needs investigation."},
    },
}


@catalog
class LayaTriage:
    """Load one English Laya checkpoint and serialize its fixed triage predictions.

    Mirrors LayaToolRanker's lazy load + lock, but uses typed decisions rather
    than embedding ranking. An engine can be injected for offline contract tests.
    """

    def __init__(self, engine: Any = None) -> None:
        self._engine = engine
        self._lock = threading.Lock()

    def _load(self) -> Any:
        # Called only while holding _lock, including during inference.
        if self._engine is None:
            try:
                import laya
            except ImportError as error:
                raise RuntimeError('Laya triage requires the optional dependency: pip install -e ".[laya]"') from error
            self._engine = laya.load(DEFAULT_MODEL)
        return self._engine

    def prepare(self) -> None:
        """Warm the model before registering this agent as running."""
        with self._lock:
            self._load()

    def classify(self, text: str) -> ChatResult:
        if not text.strip():
            raise ValueError("Cannot triage an empty issue description.")
        if len(text) > MAX_INPUT_CHARS:
            raise ValueError("Laya triage needs a short issue description or log excerpt (at most 4000 characters).")
        with self._lock:
            prediction = self._load().predict(text, QUESTIONS, max_len=CONTEXT_WINDOW)
        answers = prediction.get("answers", {})
        usage = prediction.get("usage", {})
        if usage.get("truncated") or usage.get("state_tokens_dropped", 0):
            raise ValueError("Laya could not read the complete input. Supply a shorter excerpt; no classification was returned.")
        try:
            category = answers["category"]["choice"]
            severity = answers["severity"]["choice"]
            investigation = answers["needs_investigation"]["noul"]
            scores = {key: answers[key]["answer_confidence"] for key in QUESTIONS}
            if category not in QUESTIONS["category"]["criteria"] or severity not in QUESTIONS["severity"]["criteria"]:
                raise ValueError("unknown choice")
            for number in [investigation, *scores.values()]:
                if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or not 0 <= number <= 1:
                    raise ValueError("invalid probability")
            input_tokens = usage["input_tokens"]
            if isinstance(input_tokens, bool) or not isinstance(input_tokens, int) or input_tokens < 0:
                raise ValueError("invalid token usage")
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("Laya returned an invalid triage result; no classification was returned.") from error
        uncertain = category == "unknown" or min(scores.values()) < MIN_CONFIDENCE
        response = "\n".join([
            f"Category: {category.capitalize()}",
            f"Severity: {severity.capitalize()}",
            f"Needs investigation: {'Yes' if investigation >= 0.5 else 'No'}",
            f"Uncertain: {'Yes' if uncertain else 'No'}",
            "Model confidence: " + "; ".join(f"{key.replace('_', ' ')} {score:.0%}" for key, score in scores.items()),
            "Classification only; no actions were taken.",
            "Treat as provisional and request human review." if uncertain else "",
        ]).rstrip()
        return ChatResult(
            response=response, provider_id=PROVIDER_ID, model=DEFAULT_MODEL,
            input_tokens=input_tokens, output_tokens=0, total_tokens=input_tokens,
            # State length alone excludes the question heads; don't invent a
            # context-window reading or count formatted output as generated tokens.
            context_tokens=None,
        )


_triage = LayaTriage()


def has_api_key() -> bool:
    """Compatibility with agent_config: this local provider needs no API key."""
    return True


def is_available() -> bool:
    return importlib.util.find_spec("laya") is not None


def prepare() -> None:
    _triage.prepare()


async def run_chat(
    question: str, history: list[dict[str, Any]], model: str | None,
    enabled_extensions: list[str], request_id: str | None = None, depth: int = 0,
    on_event: Any = None, caveman: bool = False,
) -> ChatResult:
    if model and model != DEFAULT_MODEL:
        raise ValueError(f"Laya triage only supports {DEFAULT_MODEL}.")
    if cancellation.is_cancelled(request_id):
        raise ChatCancelled()
    result = await anyio.to_thread.run_sync(_triage.classify, question)
    if cancellation.is_cancelled(request_id):
        raise ChatCancelled()
    if on_event is not None:
        await on_event(step_event("token", text=result.response))
    return result


def run_interpret(text: str, model: str | None = None) -> ChatResult:
    raise ValueError("Laya triage does not support summarization or free-form text generation. Use ask with an issue excerpt.")
