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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chat_app.services.llm import staged_plans_store
from chat_app.services.llm.base import ChatResult, ToolCallRecord
from chat_app.services.mcp_client import call_tool, list_tools


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


_MAX_STEP_TOOL_ROUNDS = 6  # mirrors ollama_provider._MAX_TOOL_CALL_ROUNDS's value

_EXECUTE_TOOL_CALL_SYSTEM_PROMPT = (
    "Complete this one step of a larger plan. Call a tool if it helps; "
    "otherwise answer directly. Be concise - this result feeds a later "
    "step, not the user."
)


def _tool_schemas_for(tools: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.inputSchema or {"type": "object", "properties": {}},
            },
        }
        for tool in tools
    ]


def _execute_tool_call_step(
    client: Any,
    model_name: str,
    detail: str,
    all_tools: list[Any],
    tools_used: list[str],
    tool_calls_log: list[ToolCallRecord],
) -> str:
    """Runs one bounded tool-calling round trip for a single plan step,
    scoped to just this step's own filtered tools (tighter than the
    original question - see _filter_tools) - small-context is the whole
    point of breaking Execute into per-step calls (see module docstring).
    Returns the step's result text: either the model's own plain-text
    reply (no tool needed after all), or a summary of the tool result(s)
    it actually called.
    """
    step_tools = _filter_tools(all_tools, detail)
    tool_schemas = _tool_schemas_for(step_tools)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _EXECUTE_TOOL_CALL_SYSTEM_PROMPT},
        {"role": "user", "content": detail},
    ]

    for _ in range(_MAX_STEP_TOOL_ROUNDS):
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            tools=tool_schemas if tool_schemas else None,
            extra_body={"options": {"num_ctx": _NUM_CTX, "num_predict": _NUM_PREDICT}},
        )
        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None) or []

        if not tool_calls:
            return message.content or ""

        messages.append({"role": "assistant", "content": message.content, "tool_calls": tool_calls})
        for call in tool_calls:
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except Exception:
                arguments = {}
            tools_used.append(call.function.name)
            try:
                result_text = call_tool(call.function.name, arguments)
            except Exception as error:
                result_text = f"Tool '{call.function.name}' failed: {error}"
            tool_calls_log.append(ToolCallRecord(name=call.function.name, arguments=arguments, result=result_text))
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result_text})

    return "Reached maximum tool-call rounds for this step without a final answer."


def _results_summary(results: list[dict[str, Any]]) -> str:
    if not results:
        return "(none yet)"
    return "\n".join(f"- {r['detail']}: {r['result']}" for r in results)


def _execute_reasoning_step(client: Any, model_name: str, detail: str, prior_results_summary: str) -> str:
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": "Complete this one reasoning step of a larger plan, concisely."},
            {"role": "user", "content": f"Prior results so far:\n{prior_results_summary}\n\nThis step: {detail}"},
        ],
        extra_body={"options": {"num_ctx": _NUM_CTX, "num_predict": _NUM_PREDICT}},
    )
    return response.choices[0].message.content or ""


@dataclass
class _AskUserPause:
    step_index: int
    question: str


def _execute_steps(
    client: Any,
    model_name: str,
    all_tools: list[Any],
    plan: list[dict[str, str]],
    step_index: int,
    results: list[dict[str, Any]],
    tools_used: list[str],
    tool_calls_log: list[ToolCallRecord],
    calls_budget: int,
) -> tuple["_AskUserPause | None", int]:
    """Walks `plan` from `step_index` onward, appending each step's
    {"detail", "result"} to `results` in place. Stops early, without
    consuming a step, once `calls_budget` calls have been made - the
    overall per-turn call budget (see run() in a later task) - leaving
    whatever steps didn't run simply absent from `results`; Conclude still
    works from whatever's there. A tool_call step's own internal rounds
    (see _execute_tool_call_step) are bounded separately by
    _MAX_STEP_TOOL_ROUNDS and only ever count as one call against this
    budget, to keep the budget accounting simple.

    Returns (pause_or_none, calls_used) - calls_used is how many
    Execute-phase steps this invocation actually completed, for the caller
    to subtract from its own remaining per-turn budget.
    """
    calls_used = 0
    for index in range(step_index, len(plan)):
        if calls_used >= calls_budget:
            break
        step = plan[index]

        if step["type"] == "ask_user":
            return _AskUserPause(step_index=index, question=step["detail"]), calls_used

        if step["type"] == "tool_call":
            result_text = _execute_tool_call_step(
                client, model_name, step["detail"], all_tools, tools_used, tool_calls_log
            )
        else:  # "reasoning" - the only remaining member of _STEP_TYPES
            result_text = _execute_reasoning_step(client, model_name, step["detail"], _results_summary(results))

        calls_used += 1
        results.append({"detail": step["detail"], "result": result_text})

    return None, calls_used


_MAX_TOTAL_CALLS = 20  # Enumerate + every Execute-phase step combined, this turn

_CONCLUDE_SYSTEM_PROMPT = (
    "Write the final answer to the user's original question, using the "
    "step results below. Plain, natural language only - never JSON, never "
    "a numbered step-by-step transcript. This is the only thing the user "
    "will see."
)


def _conclude(client: Any, model_name: str, question: str, results: list[dict[str, Any]]) -> str:
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": _CONCLUDE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Original question: {question}\n\nStep results:\n{_results_summary(results)}",
            },
        ],
        extra_body={"options": {"num_ctx": _NUM_CTX, "num_predict": _NUM_PREDICT}},
    )
    return response.choices[0].message.content or ""


def run(
    client: Any,
    question: str,
    history: list[dict[str, Any]],
    model_name: str,
    chat_id: str | None,
    enabled_extensions: list[str] | None,
    db_path: Path,
) -> ChatResult:
    """The pipeline's entry point - see module docstring for the five
    phases. `history` is intentionally unused here: each phase's own
    prompt is deliberately small (see module docstring), unlike
    ollama_provider._tool_loop's single continuous conversation, so the
    prior transcript plays no role in these calls. total_tokens is left at
    ChatResult's own default (None, meaning "not reported") - a known
    simplification for this first version rather than plumbing usage
    accumulation across five separate call sites.
    """
    tools_used: list[str] = []
    tool_calls_log: list[Any] = []
    all_tools = list_tools(enabled_extensions)

    resumed = staged_plans_store.get(db_path, chat_id) if chat_id else None
    if resumed is not None and resumed.model == model_name:
        plan = resumed.plan
        results = resumed.results
        # The paused ask_user step's own slot never got a result (that's
        # what paused it) - this turn's `question` IS the user's answer to
        # it, so it becomes that step's result before Execute continues.
        results.append({"detail": plan[resumed.step_index]["detail"], "result": question})
        step_index = resumed.step_index + 1
        calls_used_so_far = 1  # the paused turn's own Enumerate call
    else:
        # No resumable plan (none saved, expired, or saved under a
        # different model) - start fresh.
        filtered = _filter_tools(all_tools, question)
        plan = _enumerate_plan(client, model_name, question, filtered)
        results = []
        step_index = 0
        calls_used_so_far = 1  # the Enumerate call just made

    calls_budget = max(_MAX_TOTAL_CALLS - calls_used_so_far, 0)
    pause, _ = _execute_steps(
        client, model_name, all_tools, plan, step_index, results, tools_used, tool_calls_log, calls_budget
    )

    if pause is not None:
        # No chat_id means this pause can't be persisted - the question is
        # still returned as the answer (the turn still works), it just
        # can't be resumed automatically; the user's next message starts a
        # fresh Enumerate instead, which naturally treats their answer as
        # a new question.
        if chat_id:
            staged_plans_store.save(db_path, chat_id, "ollama", model_name, plan, pause.step_index, results)
        return ChatResult(
            response=pause.question,
            tools_used=tools_used,
            tool_calls=tool_calls_log,
            provider_id="ollama",
            model=model_name,
        )

    if chat_id:
        staged_plans_store.delete(db_path, chat_id)
    answer = _conclude(client, model_name, question, results)
    return ChatResult(
        response=answer,
        tools_used=tools_used,
        tool_calls=tool_calls_log,
        provider_id="ollama",
        model=model_name,
    )
