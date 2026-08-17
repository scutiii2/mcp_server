"""Staged enumerate-execute-conclude pipeline for Ollama models that opt in
via ModelOption.staged_pipeline (see infra/app_config.py). Replaces
ollama_provider.py's single _tool_loop with five phases - Resume check,
Filter, Enumerate, Execute, Conclude - each a small, separately-billed
Ollama call, so no individual request needs a weak model's full reasoning
budget. See
docs/superpowers/specs/2026-08-17-ollama-staged-pipeline-design.md for the
full design.
"""

from __future__ import annotations

import json
from typing import Any


# Caps the Filter phase's own output - the point is keeping the Enumerate
# phase's prompt small (see module docstring), not just narrowing
# relevance.
_MAX_FILTERED_TOOLS = 8


def _tool_keywords(tool: Any) -> list[str]:
    """A tool with no `meta`, or a `meta` without a "keywords" entry, both
    mean "not annotated" - not "no keywords" - see _filter_tools for why
    that's treated as always-relevant (fail open) rather than
    always-excluded."""
    meta = getattr(tool, "meta", None) or {}
    keywords = meta.get("keywords")
    return keywords if isinstance(keywords, list) else []


def _filter_tools(tools: list[Any], question: str) -> list[Any]:
    """Deterministic, dependency-free relevance filter: lowercase-tokenize
    `question`, keep any tool with at least one token in common with its
    own declared keywords, plus every tool with no declared keywords at
    all (fail-open - an unannotated extension tool must never become
    silently uncallable just because nobody keyword-tagged it, it's only
    less tightly filtered). Ranks matched tools by match count (most
    relevant first; Python's sort is stable, so ties keep original order),
    unlabeled tools after those, and caps the combined list at
    _MAX_FILTERED_TOOLS - bounding the Enumerate phase's own prompt is the
    actual point of this filter, so the cap applies even to fail-open
    tools.
    """
    question_tokens = set(question.lower().split())

    scored: list[tuple[int, Any]] = []
    unlabeled: list[Any] = []
    for tool in tools:
        keywords = _tool_keywords(tool)
        if not keywords:
            unlabeled.append(tool)
            continue
        match_count = len({keyword.lower() for keyword in keywords} & question_tokens)
        if match_count > 0:
            scored.append((match_count, tool))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    ranked = [tool for _, tool in scored] + unlabeled
    return ranked[:_MAX_FILTERED_TOOLS]


# Mirrors ollama_provider.py's own tuning (not imported from there -
# ollama_provider.py imports this module to dispatch into it, so the
# reverse import would be circular). Same values, same reasoning: Ollama's
# small default context window needs raising, and nothing bounds a
# hallucinating small model's completion length by default - see
# ollama_provider.py's module-level comments on _NUM_CTX/_NUM_PREDICT for
# the full story.
_NUM_CTX = 8192
_NUM_PREDICT = 1024

# Caps the Enumerate phase's own output.
_MAX_PLAN_STEPS = 8

_STEP_TYPES = {"tool_call", "reasoning", "ask_user"}

_ENUMERATE_SYSTEM_PROMPT = (
    "You are planning how to answer a question, not answering it yet. "
    "Given the question and the tools available, return a JSON array of "
    "steps needed to answer it - nothing else, no prose before or after "
    "the array. Each step is an object: "
    '{"type": "tool_call" | "reasoning" | "ask_user", "detail": "..."}. '
    'Use "tool_call" for a step that needs one of the listed tools (name '
    'the tool and what to pass it in detail). Use "reasoning" for a step '
    'that just needs you to think something through with no tool. Use '
    '"ask_user" for a step where you must ask the user a question before '
    "you can continue - detail is the exact question to ask. Keep the "
    "plan short: as few steps as the question actually needs."
)


def _tool_summaries(tools: list[Any]) -> str:
    return "\n".join(f"- {tool.name}: {tool.description or ''}" for tool in tools)


def _fallback_plan(question: str) -> list[dict[str, str]]:
    """A single tool_call step wrapping the raw question - what a plan
    degrades to whenever Enumerate's response can't be trusted (unparsable
    JSON, wrong shape, too many steps, an unrecognized step type). Never a
    hard failure - same "degrade into something usable" spirit as
    ollama_provider._extract_fallback_tool_call."""
    return [{"type": "tool_call", "detail": question}]


def _parse_plan(content: str, question: str) -> list[dict[str, str]]:
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return _fallback_plan(question)

    if not isinstance(parsed, list) or not parsed or len(parsed) > _MAX_PLAN_STEPS:
        return _fallback_plan(question)

    steps: list[dict[str, str]] = []
    for entry in parsed:
        if not isinstance(entry, dict):
            return _fallback_plan(question)
        step_type = entry.get("type")
        detail = entry.get("detail")
        if step_type not in _STEP_TYPES or not isinstance(detail, str) or not detail.strip():
            return _fallback_plan(question)
        steps.append({"type": step_type, "detail": detail})
    return steps


def _enumerate_plan(client: Any, model_name: str, question: str, filtered_tools: list[Any]) -> list[dict[str, str]]:
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": _ENUMERATE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Tools available:\n{_tool_summaries(filtered_tools)}\n\nQuestion: {question}",
            },
        ],
        extra_body={"options": {"num_ctx": _NUM_CTX, "num_predict": _NUM_PREDICT}},
    )
    content = response.choices[0].message.content or ""
    return _parse_plan(content, question)
