"""Clickable questions, ember_api's side: cutting a question the agent sent down
to sizes a browser should show, and checking the answer a browser sends back
against the question that is waiting."""

from __future__ import annotations

from typing import Any

MAX_QUESTIONS = 4
MAX_OPTIONS = 4
HEADER_MAX = 12
QUESTION_MAX = 300
LABEL_MAX = 80
DESCRIPTION_MAX = 200
OTHER_MAX = 500


def clamp_questions(raw: Any) -> list[dict[str, Any]]:
    """The questions of a `question_request` event, bounded. ai_agent already
    validated them; this keeps a misbehaving agent from sending the browser
    anything large or oddly shaped."""
    if not isinstance(raw, list):
        return []
    questions: list[dict[str, Any]] = []
    for item in raw[:MAX_QUESTIONS]:
        if not isinstance(item, dict):
            continue
        header, text = item.get("header"), item.get("question")
        if not isinstance(header, str) or not isinstance(text, str) or not header or not text:
            continue
        options: list[dict[str, str]] = []
        for option in item.get("options") if isinstance(item.get("options"), list) else []:
            if not isinstance(option, dict) or not isinstance(option.get("label"), str) or not option["label"]:
                continue
            entry = {"label": option["label"][:LABEL_MAX]}
            description = option.get("description")
            if isinstance(description, str) and description:
                entry["description"] = description[:DESCRIPTION_MAX]
            options.append(entry)
            if len(options) == MAX_OPTIONS:
                break
        questions.append(
            {
                "header": header[:HEADER_MAX],
                "question": text[:QUESTION_MAX],
                "multi_select": bool(item.get("multi_select")),
                "options": options,
            }
        )
    return questions


def check_answers(questions: list[dict[str, Any]], answers: list[dict[str, Any]]) -> str | None:
    """None when `answers` fits the waiting `questions`, otherwise what is wrong."""
    if len(answers) != len(questions):
        return f"Answer all {len(questions)} question{'s' if len(questions) != 1 else ''}, or skip."
    for number, (question, answer) in enumerate(zip(questions, answers), start=1):
        labels = {option["label"] for option in question["options"]}
        selected = list(answer.get("selected") or [])
        other = str(answer.get("other") or "").strip()
        if not selected and not other:
            return f"Choose an option or type an answer for question {number}."
        if len(set(selected)) != len(selected):
            return f"Question {number}: an option was chosen twice."
        unknown = [label for label in selected if label not in labels]
        if unknown:
            return f"Question {number}: {unknown[0]!r} is not one of its options."
        if not question.get("multi_select") and len(selected) > 1:
            return f"Question {number}: choose only one option."
    return None
