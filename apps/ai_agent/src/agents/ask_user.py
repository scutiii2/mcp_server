"""ask_user - lets the top-level agent stop and ask the user clickable questions.

Not an mcp_server tool: like delegate_to_agent it is local to ai_agent. The
providers offer it only when the caller said it can show questions (see
core/questions.py), and never to a delegated agent, which has no channel to the
user. This module holds only the tool's name, schema and argument checking; the
waiting for an answer lives in core/questions.py.
"""

from __future__ import annotations

from typing import Any

TOOL_NAME = "ask_user"
MAX_QUESTIONS = 4
MIN_OPTIONS = 2
MAX_OPTIONS = 4
HEADER_MAX = 12
TEXT_MAX = 300
LABEL_MAX = 80
DESCRIPTION_MAX = 200


def tool_description() -> str:
    return (
        "Ask the user one to four multiple-choice questions and wait for their answers. "
        "Use it sparingly: only when the request is ambiguous or a choice is really the user's to make, "
        "never to confirm routine steps or to ask what you can work out yourself. "
        "Give 2 to 4 distinct options per question, put your recommended option first, and keep labels short. "
        "The user can always type their own answer, so do not add an 'Other' option. "
        "Set multi_select true only when several options may be chosen together."
    )


def tool_parameters() -> dict[str, Any]:
    option = {
        "type": "object",
        "properties": {
            "label": {"type": "string", "maxLength": LABEL_MAX, "description": "Short choice text the user clicks."},
            "description": {"type": "string", "maxLength": DESCRIPTION_MAX, "description": "Optional: what choosing it means."},
        },
        "required": ["label"],
    }
    item = {
        "type": "object",
        "properties": {
            "header": {"type": "string", "maxLength": HEADER_MAX, "description": "Very short label for the question (a chip)."},
            "question": {"type": "string", "maxLength": TEXT_MAX, "description": "The complete question."},
            "multi_select": {"type": "boolean", "description": "Allow choosing several options. Default false."},
            "options": {"type": "array", "minItems": MIN_OPTIONS, "maxItems": MAX_OPTIONS, "items": option},
        },
        "required": ["header", "question", "options"],
    }
    return {
        "type": "object",
        "properties": {"questions": {"type": "array", "minItems": 1, "maxItems": MAX_QUESTIONS, "items": item}},
        "required": ["questions"],
    }


def _text(value: Any, limit: int) -> str | None:
    """The trimmed text, or None when it is not a string, empty, or too long."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text if text and len(text) <= limit else None


def _option(raw: Any) -> tuple[dict[str, str] | None, str | None]:
    if not isinstance(raw, dict):
        return None, "each option must be an object with a label"
    label = _text(raw.get("label"), LABEL_MAX)
    if label is None:
        return None, f"each option needs a label of 1 to {LABEL_MAX} characters"
    option = {"label": label}
    description = raw.get("description")
    if description not in (None, ""):
        text = _text(description, DESCRIPTION_MAX)
        if text is None:
            return None, f"an option description must be 1 to {DESCRIPTION_MAX} characters"
        option["description"] = text
    return option, None


def _question(raw: Any) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(raw, dict):
        return None, "each question must be an object"
    header = _text(raw.get("header"), HEADER_MAX)
    if header is None:
        return None, f"each question needs a header of 1 to {HEADER_MAX} characters"
    text = _text(raw.get("question"), TEXT_MAX)
    if text is None:
        return None, f"each question needs question text of 1 to {TEXT_MAX} characters"
    multi_select = raw.get("multi_select", False)
    if not isinstance(multi_select, bool):
        return None, "multi_select must be true or false"
    raw_options = raw.get("options")
    if not isinstance(raw_options, list) or not MIN_OPTIONS <= len(raw_options) <= MAX_OPTIONS:
        return None, f"each question needs {MIN_OPTIONS} to {MAX_OPTIONS} options"
    options: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw_option in raw_options:
        option, problem = _option(raw_option)
        if option is None:
            return None, problem
        key = option["label"].lower()
        if key in seen:
            return None, "option labels must be different within a question"
        seen.add(key)
        options.append(option)
    return {"header": header, "question": text, "multi_select": multi_select, "options": options}, None


def validate(arguments: Any) -> tuple[list[dict[str, Any]] | None, str | None]:
    """The cleaned questions, or (None, the error text the model gets back)."""
    if not isinstance(arguments, dict) or not isinstance(arguments.get("questions"), list):
        return None, f"ask_user needs a 'questions' list of 1 to {MAX_QUESTIONS} questions."
    raw = arguments["questions"]
    if not 1 <= len(raw) <= MAX_QUESTIONS:
        return None, f"ask_user needs 1 to {MAX_QUESTIONS} questions, not {len(raw)}."
    cleaned: list[dict[str, Any]] = []
    for item in raw:
        question, problem = _question(item)
        if question is None:
            return None, f"Invalid ask_user call: {problem}."
        cleaned.append(question)
    return cleaned, None
