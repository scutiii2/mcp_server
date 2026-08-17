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
