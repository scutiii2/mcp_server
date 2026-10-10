"""Laya as an advisory ticket classifier: pairwise "same issue?" and tag choice.

Laya has a 512-token window, so every request is short: each report is a title
plus the first 500 characters of its description. Answers are advisory; an
uncertain answer is never acted on. Transport errors and timeouts propagate so
the caller can fall back to "no grouping".
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

_CLIP = 500
_SAME_ISSUE = {
    "type": "noul",
    "instructions": (
        "Do Report A and Report B describe the same underlying problem or the same requested feature? "
        "Different people may word it differently."
    ),
    "criteria": {
        "false": "They are about different problems or features.",
        "true": "They are about the same problem or the same requested feature.",
    },
}


class LayaTransport(Protocol):
    async def ask(self, payload: dict[str, Any]) -> dict[str, Any]: ...


def _report(label: str, ticket: dict[str, Any]) -> str:
    title = str(ticket.get("title", ""))[:120]
    return f"{label}: {title}. {str(ticket.get('description', ''))[:_CLIP]}"


class TicketLaya:
    def __init__(self, transport: LayaTransport, *, min_confidence: float, timeout: float) -> None:
        self._transport = transport
        self._min_confidence = min_confidence
        self._timeout = timeout

    async def _ask(self, text: str, questions: dict[str, Any]) -> dict[str, Any]:
        payload = {"text": text, "questions": questions, "min_confidence": self._min_confidence}
        reply = await asyncio.wait_for(self._transport.ask(payload), self._timeout)
        return reply["answers"]

    async def same_issue(self, new: dict[str, Any], existing: dict[str, Any]) -> str:
        text = f"{_report('Report A', new)}\n\n{_report('Report B', existing)}"
        answer = (await self._ask(text, {"same": _SAME_ISSUE}))["same"]
        if answer.get("uncertain"):
            return "uncertain"
        return "yes" if float(answer["noul"]) >= 0.5 else "no"

    async def pick_tag(self, ticket: dict[str, Any], tags: dict[str, str]) -> str | None:
        question = {
            "type": "choice",
            "instructions": "Which tag best describes this support ticket?",
            "criteria": dict(tags),
        }
        answer = (await self._ask(_report("Ticket", ticket), {"tag": question}))["tag"]
        choice = answer.get("choice")
        if answer.get("uncertain") or choice not in tags:
            return None
        return choice
