from __future__ import annotations

import asyncio

import pytest

from src.services.ticket_laya import TicketLaya


class FakeTransport:
    def __init__(self, answers=None, error=None, delay=0.0):
        self.answers, self.error, self.delay, self.payloads = answers, error, delay, []

    async def ask(self, payload):
        self.payloads.append(payload)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.answers


def laya(transport, timeout=1.0):
    return TicketLaya(transport, min_confidence=0.7, timeout=timeout)


NEW = {"title": "Email fails", "description": "x" * 2000}
OLD = {"title": "Cannot send mail", "description": "SMTP is not configured"}


def noul(value, uncertain=False):
    return {"answers": {"same": {"type": "noul", "noul": value, "answer_confidence": 0.9, "uncertain": uncertain}}}


def test_same_issue_yes_no_and_uncertain():
    assert asyncio.run(laya(FakeTransport(noul(0.93))).same_issue(NEW, OLD)) == "yes"
    assert asyncio.run(laya(FakeTransport(noul(0.08))).same_issue(NEW, OLD)) == "no"
    assert asyncio.run(laya(FakeTransport(noul(0.6, uncertain=True))).same_issue(NEW, OLD)) == "uncertain"


def test_same_issue_payload_is_a_clipped_noul_question():
    transport = FakeTransport(noul(0.9))
    asyncio.run(laya(transport).same_issue(NEW, OLD))

    payload = transport.payloads[0]
    assert payload["min_confidence"] == 0.7
    assert payload["questions"]["same"]["type"] == "noul"
    assert "Email fails" in payload["text"] and "Cannot send mail" in payload["text"]
    assert len(payload["text"]) < 1500  # 2000-char description was clipped
    assert set(payload["questions"]["same"]["criteria"]) == {"false", "true"}


def test_same_issue_propagates_transport_errors_and_timeouts():
    with pytest.raises(RuntimeError):
        asyncio.run(laya(FakeTransport(error=RuntimeError("down"))).same_issue(NEW, OLD))
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(laya(FakeTransport(noul(0.9), delay=0.5), timeout=0.01).same_issue(NEW, OLD))


def choice(value, uncertain=False):
    return {"answers": {"tag": {"type": "choice", "choice": value, "probabilities": {}, "answer_confidence": 0.9, "uncertain": uncertain}}}


TAGS = {"config": "Settings are wrong.", "ui": "Interface glitches."}


def test_pick_tag_returns_choice_or_none_when_uncertain():
    assert asyncio.run(laya(FakeTransport(choice("config"))).pick_tag(NEW, TAGS)) == "config"
    assert asyncio.run(laya(FakeTransport(choice("config", uncertain=True))).pick_tag(NEW, TAGS)) is None
    assert asyncio.run(laya(FakeTransport(choice("not-a-tag"))).pick_tag(NEW, TAGS)) is None


def test_pick_tag_payload_is_a_choice_question_over_the_vocabulary():
    transport = FakeTransport(choice("ui"))
    asyncio.run(laya(transport).pick_tag(NEW, TAGS))

    question = transport.payloads[0]["questions"]["tag"]
    assert question["type"] == "choice" and question["criteria"] == TAGS
