"""A stand-in for the real Laya engine: tests inject it into LayaClient."""

from __future__ import annotations

import time
from typing import Any


class FakeEngine:
    """Answers every question. Defaults: choice -> first option, score -> 1.0,
    noul -> 0.8. `raw` maps a question id to a full raw answer to return as is
    (for invalid-output tests); `scores` and `noul` map ids to values."""

    def __init__(
        self,
        pick: str | None = None,
        confidence: float = 0.9,
        delay: float = 0.0,
        usage: dict | None = None,
        scores: dict[str, float] | None = None,
        noul: dict[str, float] | None = None,
        raw: dict[str, dict] | None = None,
        fail: bool = False,
    ) -> None:
        self.pick, self.confidence, self.delay = pick, confidence, delay
        self.usage = usage if usage is not None else {"input_tokens": 10}
        self.scores, self.noul, self.raw, self.fail = scores or {}, noul or {}, raw or {}, fail
        self.calls: list[tuple[str, dict]] = []

    def predict(self, text: str, questions: dict[str, Any], max_len: int = 512) -> dict[str, Any]:
        self.calls.append((text, questions))
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("engine failure")
        answers = {}
        for qid, spec in questions.items():
            if qid in self.raw:
                answers[qid] = self.raw[qid]
                continue
            if spec["type"] == "choice":
                keys = list(spec["criteria"])
                choice = self.pick if self.pick in keys else keys[0]
                spread = (1 - self.confidence) / (len(keys) - 1)
                probabilities = {key: (self.confidence if key == choice else spread) for key in keys}
                answers[qid] = {"choice": choice, "probabilities": probabilities, "answer_confidence": self.confidence}
            elif spec["type"] == "score":
                answers[qid] = {"score": self.scores.get(qid, 1.0), "answer_confidence": self.confidence}
            else:
                answers[qid] = {"noul": self.noul.get(qid, 0.8), "answer_confidence": self.confidence}
        return {"answers": answers, "usage": self.usage}
