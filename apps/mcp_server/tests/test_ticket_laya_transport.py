from __future__ import annotations

import json

import pytest

from src.services.ticket_laya_transport import parse_laya_reply


def test_parses_the_response_string_of_ai_agents_ask_result():
    inner = {"answers": {"same": {"type": "noul", "noul": 0.9, "answer_confidence": 0.8, "uncertain": False}}, "uncertain": False}

    assert parse_laya_reply({"response": json.dumps(inner), "tools_used": []}) == inner


@pytest.mark.parametrize(
    "payload",
    [{}, {"response": ""}, {"response": "not json"}, {"response": "[1]"}, {"response": json.dumps({"no": "answers"})}],
)
def test_rejects_anything_that_is_not_a_laya_answer(payload):
    with pytest.raises(ValueError):
        parse_laya_reply(payload)
