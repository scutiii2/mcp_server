from __future__ import annotations

from pydantic import BaseModel

from src import tool_response


class _ReportResult(BaseModel):
    name: str
    report: str


class _MessageResult(BaseModel):
    name: str
    message: str


class _BareResult(BaseModel):
    name: str
    count: int
    tags: list[str]


def test_report_field_becomes_the_visible_text():
    result = _ReportResult(name="zima", report="zima: healthy, 40% disk used")

    call_result = tool_response.respond(result)

    assert len(call_result.content) == 1
    assert call_result.content[0].text == "zima: healthy, 40% disk used"


def test_message_field_becomes_the_visible_text_when_no_report_field():
    result = _MessageResult(name="zima", message="zima restarted")

    call_result = tool_response.respond(result)

    assert call_result.content[0].text == "zima restarted"


def test_structured_content_always_carries_the_full_model():
    result = _ReportResult(name="zima", report="zima: healthy")

    call_result = tool_response.respond(result)

    assert call_result.structuredContent == {"name": "zima", "report": "zima: healthy"}


def test_neither_field_falls_back_to_field_lines_not_json():
    result = _BareResult(name="zima", count=2, tags=["a", "b"])

    call_result = tool_response.respond(result)

    text = call_result.content[0].text
    assert "{" not in text
    assert "name: zima" in text
    assert "count: 2" in text
    assert "- a" in text and "- b" in text
