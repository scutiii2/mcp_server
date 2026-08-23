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
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.services.llm import staged_plans_store
from src.services.llm.base import ChatResult, ToolCallRecord
from src.services.mcp_client import call_tool, list_tools


# All six guardrail constants live together here, right after the imports,
# rather than scattered across the file in whatever order each phase was
# added in (that scattering is exactly why the call-budget under-counting
# bug - see _execute_steps - was invisible to any single phase's review:
# each phase's own reviewer only ever saw its own constant in isolation).
# Every cap fails into "produce a usable degraded result," never into
# raising out of the turn - consistent with every existing guardrail in
# ollama_provider.py.

# Caps the Filter phase's own output - the point is keeping the Enumerate
# phase's prompt small (see module docstring), not just narrowing
# relevance.
_MAX_FILTERED_TOOLS = 8

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

# Caps a single tool_call step's own internal tool-calling rounds (mirrors
# ollama_provider._MAX_TOOL_CALL_ROUNDS's value).
_MAX_STEP_TOOL_ROUNDS = 6

# Caps Enumerate + every real Execute-phase Ollama call combined, this
# turn. _execute_steps charges each step's *actual* round count against
# this (a tool_call step's own internal rounds, up to
# _MAX_STEP_TOOL_ROUNDS; a reasoning step is always exactly 1), not a flat
# 1 per step - otherwise this budget could never actually fire.
_MAX_TOTAL_CALLS = 20

# This module's own provider id, as recorded in staged_plans_store rows
# (see run()'s save() call below) and in every ChatResult it returns. A
# saved plan is only resumable when its provider_id AND model both match
# this turn's (see run()'s resume check) - both, not just model, per the
# design spec's phase-0 resume rule.
_PROVIDER_ID = "ollama"


def _tool_keywords(tool: Any) -> list[str]:
    """A tool with no `meta`, or a `meta` without a "keywords" entry, both
    mean "not annotated" - not "no keywords" - see _filter_tools for why
    that's treated as always-relevant (fail open) rather than
    always-excluded."""
    meta = getattr(tool, "meta", None) or {}
    keywords = meta.get("keywords")
    return keywords if isinstance(keywords, list) else []


_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    """Regex tokenization (not str.split()) so trailing/attached
    punctuation - e.g. the "cpu?" that "how's the CPU?".lower().split()
    would produce - never prevents a match against a bare keyword like
    "cpu"."""
    return set(_TOKEN_PATTERN.findall(text.lower()))


def _tool_name_tokens(tool: Any) -> set[str]:
    """Tokens derived from the tool's own declared name, split on
    underscores/hyphens and lowercased. Matched against in addition to
    meta["keywords"] so a step whose `detail` names a tool explicitly (as
    _ENUMERATE_SYSTEM_PROMPT instructs every tool_call step to do) always
    survives filtering - independent of whether that tool has any
    keywords declared at all."""
    name = getattr(tool, "name", "") or ""
    return _tokenize(name.replace("_", " ").replace("-", " "))


def _filter_tools(tools: list[Any], text: str) -> list[Any]:
    """Deterministic, dependency-free relevance filter: tokenize `text`
    (the top-level Filter phase calls this with the user's question; the
    Execute phase calls it again with a single step's own `detail` - see
    _execute_tool_call_step), keep any tool with at least one token in
    common with its own declared keywords OR its own name's tokens, plus
    every tool with no declared keywords and no name-token match either
    (fail-open - an unannotated extension tool must never become silently
    uncallable just because nobody keyword-tagged it and its name doesn't
    happen to appear in the text, it's only less tightly filtered). Ranks
    matched tools by match count (most relevant first; Python's sort is
    stable, so ties keep original order), unlabeled tools after those, and
    caps the combined list at _MAX_FILTERED_TOOLS - bounding the Enumerate
    phase's own prompt is the actual point of this filter, so the cap
    applies even to fail-open tools.

    Falls back to the first _MAX_FILTERED_TOOLS of `tools` unfiltered if
    every tool gets dropped. Confirmed live: every built-in tool declares
    keywords (test_tool_keywords.py enforces this), so a capability
    question like "give me the list of tools you have" - whose own words
    share no token with any tool-specific keyword ("host", "health",
    "otp", ...) - matches nothing and drops every labeled tool, leaving
    Enumerate a genuinely empty tool list for exactly the question most
    likely to ask about them. Downstream phases then have no grounding but
    to claim there are none. An empty result is never more useful than an
    unfiltered one, so treat "nothing matched" as "filtering doesn't apply
    here" rather than "there's nothing to offer."
    """
    text_tokens = _tokenize(text)

    scored: list[tuple[int, Any]] = []
    unlabeled: list[Any] = []
    for tool in tools:
        keywords = _tool_keywords(tool)
        match_tokens = {keyword.lower() for keyword in keywords} | _tool_name_tokens(tool)
        match_count = len(match_tokens & text_tokens)
        if match_count > 0:
            scored.append((match_count, tool))
        elif not keywords:
            unlabeled.append(tool)
        # else: a labeled tool with zero overlap (by keyword or by its own
        # name) is dropped.

    scored.sort(key=lambda pair: pair[0], reverse=True)
    ranked = [tool for _, tool in scored] + unlabeled
    if not ranked and tools:
        return tools[:_MAX_FILTERED_TOOLS]
    return ranked[:_MAX_FILTERED_TOOLS]


_STEP_TYPES = {"tool_call", "reasoning", "ask_user"}

# The next-to-last sentence guards a failure mode confirmed live
# (qwen2.5:3b, "give me the list of tools you have"): once _filter_tools's
# fail-open fallback (see its docstring) started showing Enumerate the
# real tool list for exactly this kind of question, the model planned a
# "tool_call" step per tool to "demonstrate" them - get_host_health_tool
# (guessing "zima", the example name from the tool's own description),
# then request_otp_tool and verify_otp_tool with missing/null arguments,
# all three failing. Nothing here previously told it that a question
# ABOUT its tools isn't a reason to USE one - same gap
# _LOCAL_MODEL_TOOL_GUIDANCE closes for ollama_provider.py's plain loop
# (recursive_chain models get that one for free, since recursive_chain is
# just extra rounds on the same conversation - it's only staged_pipeline,
# with its own separate per-phase prompts, that needed its own copy).
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
    "you can continue - detail is the exact question to ask. If the user "
    "is only asking what tools you have, what you can do, or to list or "
    "describe your tools, that is a question ABOUT them, not a reason to "
    'use one - plan a single "reasoning" step, not a "tool_call" step. '
    "Keep the plan short: as few steps as the question actually needs."
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


# Defense-in-depth alongside _ENUMERATE_SYSTEM_PROMPT's own guard above:
# this is what actually runs for EVERY tool_call step, including
# _fallback_plan's single step (Enumerate's JSON came back unparsable or
# malformed - easy for a 3B model) - so even when Enumerate still produces
# a tool_call step for a listing/capability question, the model executing
# it gets told not to call a tool just because it's in scope.
_EXECUTE_TOOL_CALL_SYSTEM_PROMPT = (
    "Complete this one step of a larger plan. Call a tool if it helps; "
    "otherwise answer directly. If this step is only asking what tools "
    "are available or to list or describe them, that is a question ABOUT "
    "your tools, not a reason to call one - answer directly using the "
    "names and descriptions of the tools you were given. Be concise - "
    "this result feeds a later step, not the user."
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
) -> tuple[str, int]:
    """Runs one bounded tool-calling round trip for a single plan step,
    scoped to just this step's own filtered tools (tighter than the
    original question - see _filter_tools) - small-context is the whole
    point of breaking Execute into per-step calls (see module docstring).

    Returns (result_text, rounds_used). result_text is either the model's
    own plain-text reply (no tool needed after all), or a summary of the
    tool result(s) it actually called. rounds_used is how many real Ollama
    calls this step actually made (one per loop iteration, up to
    _MAX_STEP_TOOL_ROUNDS) - the caller (_execute_steps) charges this real
    count against the per-turn call budget instead of a flat 1 per step,
    since a single step can make up to _MAX_STEP_TOOL_ROUNDS real calls on
    its own.
    """
    step_tools = _filter_tools(all_tools, detail)
    tool_schemas = _tool_schemas_for(step_tools)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _EXECUTE_TOOL_CALL_SYSTEM_PROMPT},
        {"role": "user", "content": detail},
    ]

    rounds_used = 0
    for _ in range(_MAX_STEP_TOOL_ROUNDS):
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            tools=tool_schemas if tool_schemas else None,
            extra_body={"options": {"num_ctx": _NUM_CTX, "num_predict": _NUM_PREDICT}},
        )
        rounds_used += 1
        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None) or []

        if not tool_calls:
            return message.content or "", rounds_used

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

    return "Reached maximum tool-call rounds for this step without a final answer.", rounds_used


def _results_summary(results: list[dict[str, Any]]) -> str:
    if not results:
        return "(none yet)"
    return "\n".join(f"- {r['detail']}: {r['result']}" for r in results)


def _execute_reasoning_step(
    client: Any, model_name: str, detail: str, prior_results_summary: str, tools_summary: str
) -> str:
    """`tools_summary` (see run()) is the only reason a reasoning step can
    correctly answer a question about the assistant's own tools - Enumerate
    is otherwise the *only* phase shown any tool names/descriptions at all
    (see module docstring for the full call sequence), so without this a
    "reasoning" step (which is exactly what Enumerate plans for a
    capability question like "what tools do you have" - nothing needs to
    be *called*) had zero grounding and could only fabricate an answer.
    Confirmed live: qwen2.5:3b claimed "I don't have any tools at all" this
    way despite tools being configured and offered.
    """
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": "Complete this one reasoning step of a larger plan, concisely."},
            {
                "role": "user",
                "content": (
                    f"Tools available to you:\n{tools_summary}\n\n"
                    f"Prior results so far:\n{prior_results_summary}\n\nThis step: {detail}"
                ),
            },
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
    tools_summary: str,
    plan: list[dict[str, str]],
    step_index: int,
    results: list[dict[str, Any]],
    tools_used: list[str],
    tool_calls_log: list[ToolCallRecord],
    calls_budget: int,
) -> tuple["_AskUserPause | None", int]:
    """Walks `plan` from `step_index` onward, appending each step's
    {"detail", "result"} to `results` in place. Stops early, without
    consuming a step, once `calls_budget` real Ollama calls have been made
    - the overall per-turn call budget - leaving whatever steps didn't run
    simply absent from `results`; Conclude still works from whatever's
    there. A tool_call step's own internal rounds (see
    _execute_tool_call_step, bounded by _MAX_STEP_TOOL_ROUNDS) are charged
    against this budget at their real count, not a flat 1 per step -
    a step can make up to _MAX_STEP_TOOL_ROUNDS real calls on its own, and
    undercounting that would let the budget check never actually fire. A
    reasoning step is always exactly 1 real call.

    Returns (pause_or_none, calls_used) - calls_used is the real number of
    Ollama calls this invocation actually made across every step it
    completed, for the caller to subtract from its own remaining per-turn
    budget.
    """
    calls_used = 0
    for index in range(step_index, len(plan)):
        if calls_used >= calls_budget:
            break
        step = plan[index]

        if step["type"] == "ask_user":
            return _AskUserPause(step_index=index, question=step["detail"]), calls_used

        if step["type"] == "tool_call":
            result_text, step_calls = _execute_tool_call_step(
                client, model_name, step["detail"], all_tools, tools_used, tool_calls_log
            )
        else:  # "reasoning" - the only remaining member of _STEP_TYPES
            result_text = _execute_reasoning_step(
                client, model_name, step["detail"], _results_summary(results), tools_summary
            )
            step_calls = 1

        calls_used += step_calls
        results.append({"detail": step["detail"], "result": result_text})

    return None, calls_used


_CONCLUDE_SYSTEM_PROMPT = (
    "Write the final answer to the user's original question, using the "
    "step results below. Plain, natural language only - never JSON, never "
    "a numbered step-by-step transcript. This is the only thing the user "
    "will see."
)


def _conclude(client: Any, model_name: str, question: str, results: list[dict[str, Any]], tools_summary: str) -> str:
    """`tools_summary` (see run()): same reasoning as
    _execute_reasoning_step - Conclude is the phase that actually writes
    what the user sees, and previously had no way to answer a question
    about the assistant's own tools since nothing upstream of it (besides
    Enumerate, which never speaks to the user) was ever shown the tool
    list."""
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": _CONCLUDE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Tools available to you:\n{tools_summary}\n\n"
                    f"Original question: {question}\n\nStep results:\n{_results_summary(results)}"
                ),
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
    # Full inventory (not the Enumerate-only `filtered` list below), for
    # _execute_reasoning_step and _conclude - see both docstrings. Neither
    # of those calls is frequent enough (at most one reasoning step, and
    # exactly one Conclude, per turn) for the context-budget concern that
    # motivates filtering Enumerate's own prompt to matter here.
    tools_summary = _tool_summaries(all_tools)

    resumed = staged_plans_store.get(db_path, chat_id) if chat_id else None
    if resumed is not None and resumed.provider_id == _PROVIDER_ID and resumed.model == model_name:
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
        client, model_name, all_tools, tools_summary, plan, step_index, results, tools_used, tool_calls_log,
        calls_budget,
    )

    if pause is not None:
        # No chat_id means this pause can't be persisted - the question is
        # still returned as the answer (the turn still works), it just
        # can't be resumed automatically; the user's next message starts a
        # fresh Enumerate instead, which naturally treats their answer as
        # a new question.
        if chat_id:
            staged_plans_store.save(db_path, chat_id, _PROVIDER_ID, model_name, plan, pause.step_index, results)
        return ChatResult(
            response=pause.question,
            tools_used=tools_used,
            tool_calls=tool_calls_log,
            provider_id=_PROVIDER_ID,
            model=model_name,
        )

    if chat_id:
        staged_plans_store.delete(db_path, chat_id)
    answer = _conclude(client, model_name, question, results, tools_summary)
    return ChatResult(
        response=answer,
        tools_used=tools_used,
        tool_calls=tool_calls_log,
        provider_id=_PROVIDER_ID,
        model=model_name,
    )
