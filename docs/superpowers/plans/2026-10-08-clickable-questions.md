# Clickable Questions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The agent can stop mid-answer and ask the user 1-4 clickable questions (single or multi-select, plus a free-text "Other"); the user answers or skips and the agent continues.

**Architecture:** A new local tool `ask_user` in ai_agent, handled in each provider's async tool loop next to `approvals.review`. It emits `question_request`, waits on a broker keyed by `(request_id, step_id)` (with a keep-alive heartbeat, no short timeout, 60-minute safety cap), and is answered through a new `answer_question` MCP tool. ember_api forwards the events, remembers the pending question for late joiners, and exposes `POST /api/chats/{id}/questions`. ember_web shows a `QuestionCard` inline in the live answer. It is a copy of the tool-approval flow with a question instead of allow/deny.

**Tech Stack:** Python 3 + FastMCP (ai_agent), FastAPI (ember_api), pytest; Vue 3 + TypeScript + Pinia, Vitest (ember_web).

**Spec:** `docs/superpowers/specs/2026-10-08-clickable-questions-design.md`

## Global Constraints

- Tool name exactly `ask_user`. Limits: 1-4 questions; 2-4 options per question; header at most 12 characters; question at most 300; option label at most 80, unique within a question (case-insensitive); option description at most 200; "Other" text at most 500.
- Events: `question_request` `{id, questions}`, `question_resolved` `{id, outcome}` with outcome one of `answered`, `skipped`, `timeout`, `cancelled`. `keepalive` is an ai_agent-only event that ember_api drops.
- Wait limits: `MAX_WAIT_SECONDS = 3600.0`, `KEEPALIVE_SECONDS = 20.0`, `POLL_SECONDS = 0.5`.
- Only the top-level agent (depth 0) is offered `ask_user`, and only when the caller sent `ask_user=True`. A delegated agent never gets it.
- Turn request field `can_ask: bool = False`; ember_web always sends `true`, `chat_cli` sends nothing.
- Answer payload: `answers: [{"selected": [str], "other": str | null}]`, aligned with the questions by index, plus `skipped: bool`.
- ember_web: theme tokens only (no hardcoded colors), no raw `v-html`, no constructor parameter properties or enums, pages in `src/views/`, components in `src/components/`.
- This user commits only after verification passes AND they agree; push only when asked. Stage only the files each task names (other uncommitted work may exist). Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` (or the executing agent's own trailer).
- Run ai_agent tests from `apps/ai_agent/`; ember_api tests from `apps/ember_api/` with `.venv_ember_api\Scripts\python -m pytest`; ember_web checks from `apps/ember_web/`. Find the ai_agent test command in `apps/ai_agent/tests/README.md` before the first run.

## Differences from the spec (decided while planning)

1. `POST /api/chats/{id}/questions` answers like `/approvals`: 404 when no answer is running, 409 when nothing is waiting, 422 for an invalid answer, `{"answered": true}` on success. (The spec said `answered: false`; the 404/409 route already has client handling in the approvals flow.)
2. ember_api does not require ai_agent to be deployed first. When `can_ask` is true the gateway calls `status` and sends `ask_user` only if it reports `user_questions: true`; an older agent just never gets the tool.
3. The text given to the model lists each question's full text, not its header: `- <question>: <answer>`.
4. The gateway method that sends the answers is `answer_question(...)` (Protocol, `McpAgentGateway`, `FakeAgent`), not `answer(...)`: `FakeAgent.answer` already exists as the canned response text. `TurnRegistry.answer(...)` keeps its name.
5. No Playwright flow for a held question: the e2e fake streams a finished body in one response and cannot hold a stream open. e2e only gets the new route so its "unknown call" guard stays quiet. The flow is covered by store and component tests.

## File Structure

ai_agent (`apps/ai_agent/`):
- Create `src/agents/ask_user.py` - tool name, schema, validation.
- Create `src/core/questions.py` - policy, broker, `ask`, `handle`, answer text.
- Modify `src/llm/anthropic_provider.py`, `src/llm/openai_provider.py` - offer the tool, handle the call.
- Modify `src/agents/agent_config.py` - bind the policy per turn.
- Modify `src/server.py` - `ask_user` argument, `answer_question` tool, `status` flag.
- Create `tests/test_ask_user.py`, `tests/test_questions.py`.

ember_api (`apps/ember_api/`):
- Create `src/services/question_answers.py` - `clamp_questions`, `check_answers`.
- Modify `src/services/agent_gateway.py`, `src/services/turns.py`, `src/routes/chats.py`, `README.md`.
- Modify `tests/conftest.py` (FakeAgent), `tests/test_agent_gateway.py`.
- Create `tests/test_questions.py`.

ember_web (`apps/ember_web/`):
- Modify `src/api/types.ts`, `src/api/ChatsClient.ts`, `src/stores/chat.ts`.
- Create `src/components/QuestionCard.vue`, `src/components/QuestionCard.test.ts`, `src/utils/askUserStep.ts`, `src/utils/askUserStep.test.ts`, `src/stores/chat.questions.test.ts`.
- Modify `src/components/MessageList.vue`, `src/components/ToolSteps.vue`, `src/views/ChatView.vue`, `e2e/fakeApi.ts`, `README.md`.

---

### Task 1: `ask_user` schema and the question broker (ai_agent)

**Files:**
- Create: `apps/ai_agent/src/agents/ask_user.py`
- Create: `apps/ai_agent/src/core/questions.py`
- Test: `apps/ai_agent/tests/test_ask_user.py`, `apps/ai_agent/tests/test_questions.py`

**Interfaces:**
- Produces (used by Task 2):
  - `ask_user.TOOL_NAME: str`, `ask_user.tool_description() -> str`, `ask_user.tool_parameters() -> dict`, `ask_user.validate(arguments: Any) -> tuple[list[dict] | None, str | None]` (cleaned questions or an error text).
  - `questions.QuestionPolicy(enabled: bool = False)`, `questions.bind(policy) -> Token`, `questions.reset(token)`, `questions.current() -> QuestionPolicy`.
  - `questions.Answer(outcome: str, answers: tuple[dict, ...] = ())`, `questions.QuestionBroker(timeout, poll, keepalive)` with `async wait(request_id, step_id, on_event=None) -> Answer` and `answer(request_id, step_id, answers, skipped) -> bool`, module singleton `questions.BROKER`.
  - `questions.format_answers(questions, answers) -> str`, `async questions.ask(request_id, step_id, questions, on_event) -> str`, `async questions.handle(name, request_id, step_id, arguments, on_event) -> tuple[str, bool] | None` (None unless `name == "ask_user"`; `(result_text, ok)` otherwise).
  - Constants `NO_CHANNEL`, `NOT_OFFERED`, `SKIPPED`, `TIMED_OUT`, `MAX_WAIT_SECONDS`, `KEEPALIVE_SECONDS`, `POLL_SECONDS`.

- [ ] **Step 1: Write the failing schema tests**

Create `apps/ai_agent/tests/test_ask_user.py`:

```python
"""ask_user.py: the tool the top-level agent uses to ask the user clickable questions."""

from __future__ import annotations

from src.agents import ask_user


def question(**changes):
    base = {
        "header": "Format",
        "question": "Which format do you want?",
        "options": [{"label": "CSV"}, {"label": "JSON", "description": "Structured"}],
    }
    return {**base, **changes}


def test_a_valid_call_is_cleaned_and_defaults_to_single_select() -> None:
    cleaned, error = ask_user.validate({"questions": [question()]})

    assert error is None
    assert cleaned == [
        {
            "header": "Format",
            "question": "Which format do you want?",
            "multi_select": False,
            "options": [{"label": "CSV"}, {"label": "JSON", "description": "Structured"}],
        }
    ]


def test_surrounding_whitespace_is_trimmed_and_multi_select_is_kept() -> None:
    cleaned, _ = ask_user.validate(
        {"questions": [question(header=" Pick ", question=" Which? ", multi_select=True)]}
    )

    assert (cleaned[0]["header"], cleaned[0]["question"], cleaned[0]["multi_select"]) == ("Pick", "Which?", True)


def test_bad_calls_come_back_as_an_error_text_for_the_model() -> None:
    too_many = [question() for _ in range(ask_user.MAX_QUESTIONS + 1)]
    cases = {
        "not an object": "nope",
        "no questions key": {},
        "questions is not a list": {"questions": "x"},
        "no questions": {"questions": []},
        "too many questions": {"questions": too_many},
        "a question is not an object": {"questions": ["x"]},
        "empty header": {"questions": [question(header=" ")]},
        "header too long": {"questions": [question(header="x" * (ask_user.HEADER_MAX + 1))]},
        "empty question": {"questions": [question(question="")]},
        "question too long": {"questions": [question(question="x" * (ask_user.TEXT_MAX + 1))]},
        "multi_select not a bool": {"questions": [question(multi_select="yes")]},
        "one option": {"questions": [question(options=[{"label": "A"}])]},
        "five options": {"questions": [question(options=[{"label": str(i)} for i in range(5)])]},
        "option not an object": {"questions": [question(options=["A", "B"])]},
        "empty label": {"questions": [question(options=[{"label": ""}, {"label": "B"}])]},
        "label too long": {"questions": [question(options=[{"label": "x" * (ask_user.LABEL_MAX + 1)}, {"label": "B"}])]},
        "duplicate labels": {"questions": [question(options=[{"label": "A"}, {"label": "a"}])]},
        "description too long": {
            "questions": [question(options=[{"label": "A", "description": "x" * (ask_user.DESCRIPTION_MAX + 1)}, {"label": "B"}])]
        },
    }
    for name, arguments in cases.items():
        cleaned, error = ask_user.validate(arguments)
        assert cleaned is None and isinstance(error, str) and error, name


def test_the_schema_matches_the_limits() -> None:
    schema = ask_user.tool_parameters()
    items = schema["properties"]["questions"]

    assert schema["required"] == ["questions"]
    assert (items["minItems"], items["maxItems"]) == (1, ask_user.MAX_QUESTIONS)
    options = items["items"]["properties"]["options"]
    assert (options["minItems"], options["maxItems"]) == (ask_user.MIN_OPTIONS, ask_user.MAX_OPTIONS)
    assert items["items"]["properties"]["header"]["maxLength"] == ask_user.HEADER_MAX
    assert "sparingly" in ask_user.tool_description()
```

- [ ] **Step 2: Run to verify it fails**

Run (from `apps/ai_agent/`): `python -m pytest tests/test_ask_user.py -q` (use the interpreter named in `tests/README.md`).
Expected: FAIL (`ImportError: cannot import name 'ask_user'`).

- [ ] **Step 3: Write `ask_user.py`**

Create `apps/ai_agent/src/agents/ask_user.py`:

```python
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
```

- [ ] **Step 4: Run to verify the schema tests pass**

Run: `python -m pytest tests/test_ask_user.py -q`
Expected: PASS.

- [ ] **Step 5: Write the failing broker tests**

Create `apps/ai_agent/tests/test_questions.py`:

```python
"""questions.py: asking the user clickable questions - the policy, the broker that
waits for the answer, the ask()/handle() helpers the providers call, and both
providers' tool loops. Plain sync tests around asyncio.run(), like test_approvals.py."""

from __future__ import annotations

import asyncio

import pytest

from src.agents import ask_user
from src.core import questions
from src.llm import cancellation
from src.llm.base_provider import ChatCancelled

REQUEST = "req-q"
QUESTIONS = [
    {
        "header": "Format",
        "question": "Which format?",
        "multi_select": False,
        "options": [{"label": "CSV"}, {"label": "JSON"}],
    },
    {
        "header": "Extras",
        "question": "Which extras?",
        "multi_select": True,
        "options": [{"label": "Totals"}, {"label": "Chart"}],
    },
]
ANSWERS = [{"selected": ["CSV"], "other": None}, {"selected": ["Totals", "Chart"], "other": "and a title"}]


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    cancellation.clear(REQUEST)
    monkeypatch.setattr(questions, "BROKER", questions.QuestionBroker(timeout=3.0, poll=0.05, keepalive=0.1))
    yield
    cancellation.clear(REQUEST)


def run(coro):
    return asyncio.run(coro)


class Recorder:
    """An on_event that keeps every event, and answers a question when told how."""

    def __init__(self, answers=None, skipped=False) -> None:
        self.events: list[dict] = []
        self._answers = answers
        self._skipped = skipped

    async def __call__(self, event: dict) -> None:
        self.events.append(event)
        if event["type"] == "question_request" and (self._answers is not None or self._skipped):
            asyncio.get_running_loop().call_soon(
                questions.BROKER.answer, REQUEST, event["id"], self._answers or [], self._skipped
            )

    def types(self) -> list[str]:
        return [e["type"] for e in self.events]


# --- the policy ------------------------------------------------------------------------


def test_the_default_policy_offers_nothing() -> None:
    assert questions.current().enabled is False


def test_bind_and_reset_restore_the_previous_policy() -> None:
    token = questions.bind(questions.QuestionPolicy(True))
    assert questions.current().enabled is True

    questions.reset(token)

    assert questions.current().enabled is False


# --- the broker -------------------------------------------------------------------------


def test_wait_returns_the_answers_or_a_skip() -> None:
    async def scenario():
        broker = questions.QuestionBroker(timeout=5, poll=0.05)
        loop = asyncio.get_running_loop()
        loop.call_soon(broker.answer, REQUEST, "s1", ANSWERS, False)
        first = await broker.wait(REQUEST, "s1")
        loop.call_soon(broker.answer, REQUEST, "s1", [], True)
        second = await broker.wait(REQUEST, "s1")
        return first, second

    first, second = run(scenario())

    assert (first.outcome, list(first.answers)) == ("answered", ANSWERS)
    assert second.outcome == "skipped"


def test_answer_is_false_when_nothing_is_waiting_and_counts_once() -> None:
    async def scenario():
        broker = questions.QuestionBroker(timeout=5, poll=0.05)
        before = broker.answer(REQUEST, "s1", ANSWERS, False)
        waiter = asyncio.create_task(broker.wait(REQUEST, "s1"))
        await asyncio.sleep(0)
        first = broker.answer(REQUEST, "s1", ANSWERS, False)
        second = broker.answer(REQUEST, "s1", ANSWERS, False)
        await waiter
        return before, first, second

    assert run(scenario()) == (False, True, False)


def test_an_unanswered_question_times_out_at_the_safety_cap() -> None:
    async def scenario():
        return await questions.QuestionBroker(timeout=0.2, poll=0.05).wait(REQUEST, "s1")

    assert run(scenario()).outcome == "timeout"


def test_stop_ends_the_wait() -> None:
    async def scenario():
        asyncio.get_running_loop().call_later(0.1, cancellation.cancel, REQUEST)
        return await questions.QuestionBroker(timeout=5, poll=0.05).wait(REQUEST, "s1")

    cancellation.register(REQUEST)
    assert run(scenario()).outcome == "cancelled"


def test_a_second_wait_on_the_same_step_replaces_the_first_which_reads_as_skipped() -> None:
    async def scenario():
        broker = questions.QuestionBroker(timeout=5, poll=0.05)
        first = asyncio.create_task(broker.wait(REQUEST, "s1"))
        await asyncio.sleep(0.01)
        second = asyncio.create_task(broker.wait(REQUEST, "s1"))
        await asyncio.sleep(0.01)
        broker.answer(REQUEST, "s1", ANSWERS, False)
        return (await first).outcome, (await second).outcome

    assert run(scenario()) == ("skipped", "answered")


def test_a_keepalive_event_is_sent_while_waiting() -> None:
    async def scenario():
        rec = Recorder()
        broker = questions.QuestionBroker(timeout=5, poll=0.02, keepalive=0.05)
        waiter = asyncio.create_task(broker.wait(REQUEST, "s1", rec))
        await asyncio.sleep(0.3)
        broker.answer(REQUEST, "s1", [], True)
        await waiter
        return rec.types()

    types = run(scenario())

    assert types and set(types) == {"keepalive"} and len(types) >= 2


# --- the answer text ---------------------------------------------------------------------


def test_format_answers_names_each_question_and_what_was_chosen() -> None:
    text = questions.format_answers(QUESTIONS, ANSWERS)

    assert text == (
        "The user answered:\n"
        "- Which format?: CSV\n"
        "- Which extras?: Totals, Chart; other: and a title"
    )


def test_format_answers_handles_only_other_and_missing_answers() -> None:
    text = questions.format_answers(QUESTIONS, [{"selected": [], "other": "XML"}])

    assert text == "The user answered:\n- Which format?: other: XML\n- Which extras?: (no answer)"


# --- ask() ------------------------------------------------------------------------------


def test_ask_emits_request_then_resolved_and_returns_the_answer_text() -> None:
    rec = Recorder(answers=ANSWERS)

    text = run(questions.ask(REQUEST, "s1", QUESTIONS, rec))

    assert text == questions.format_answers(QUESTIONS, ANSWERS)
    assert rec.types() == ["question_request", "question_resolved"]
    assert rec.events[0]["id"] == "s1" and rec.events[0]["questions"] == QUESTIONS
    assert rec.events[1]["outcome"] == "answered"


def test_ask_tells_the_model_when_the_user_skips() -> None:
    rec = Recorder(skipped=True)

    assert run(questions.ask(REQUEST, "s1", QUESTIONS, rec)) == questions.SKIPPED
    assert rec.events[-1]["outcome"] == "skipped"


def test_ask_tells_the_model_when_the_cap_runs_out(monkeypatch) -> None:
    monkeypatch.setattr(questions, "BROKER", questions.QuestionBroker(timeout=0.2, poll=0.05, keepalive=10))
    rec = Recorder()

    assert run(questions.ask(REQUEST, "s1", QUESTIONS, rec)) == questions.TIMED_OUT
    assert rec.events[-1]["outcome"] == "timeout"


def test_ask_has_no_channel_without_an_event_sink_or_a_request_id() -> None:
    assert run(questions.ask(REQUEST, "s1", QUESTIONS, None)) == questions.NO_CHANNEL
    assert run(questions.ask(None, "s1", QUESTIONS, Recorder())) == questions.NO_CHANNEL


def test_stop_while_a_question_is_open_ends_the_step_and_cancels_the_turn() -> None:
    cancellation.register(REQUEST)
    rec = Recorder()

    async def stopper(event: dict) -> None:
        await rec(event)
        if event["type"] == "question_request":
            asyncio.get_running_loop().call_later(0.05, cancellation.cancel, REQUEST)

    with pytest.raises(ChatCancelled):
        run(questions.ask(REQUEST, "s1", QUESTIONS, stopper))

    assert rec.types() == ["question_request", "question_resolved", "step_end"]
    assert rec.events[-1]["ok"] is False


# --- handle() -----------------------------------------------------------------------------


def test_handle_ignores_every_other_tool() -> None:
    assert run(questions.handle("tool_srv_stopApp", REQUEST, "s1", {}, Recorder())) is None


def test_handle_refuses_the_tool_when_it_was_not_offered() -> None:
    rec = Recorder()

    result = run(questions.handle(ask_user.TOOL_NAME, REQUEST, "s1", {"questions": QUESTIONS}, rec))

    assert result == (questions.NOT_OFFERED, False)
    assert rec.events == []


def test_handle_gives_a_bad_call_back_to_the_model_without_asking_the_user() -> None:
    rec = Recorder()
    token = questions.bind(questions.QuestionPolicy(True))
    try:
        text, ok = run(questions.handle(ask_user.TOOL_NAME, REQUEST, "s1", {"questions": []}, rec))
    finally:
        questions.reset(token)

    assert ok is False and "1 to 4" in text
    assert rec.events == []


def test_handle_asks_and_returns_the_answers_as_the_tool_result() -> None:
    rec = Recorder(answers=ANSWERS)
    token = questions.bind(questions.QuestionPolicy(True))
    try:
        result = run(questions.handle(ask_user.TOOL_NAME, REQUEST, "s1", {"questions": QUESTIONS}, rec))
    finally:
        questions.reset(token)

    assert result == (questions.format_answers(QUESTIONS, ANSWERS), True)
```

- [ ] **Step 6: Run to verify it fails**

Run: `python -m pytest tests/test_questions.py -q`
Expected: FAIL (`cannot import name 'questions'`).

- [ ] **Step 7: Write `questions.py`**

Create `apps/ai_agent/src/core/questions.py`:

```python
"""Asking the user clickable questions (the ask_user tool).

Same shape as approvals.py: a provider's tool loop calls `handle()` for the
ask_user tool; it emits a ``question_request`` event to the caller and waits on
a broker until the user answers through the ``answer_question`` MCP tool.

Unlike an approval there is no short timeout: the user may be deciding, so the
wait lasts until they answer, skip or press Stop. While it waits it sends a
``keepalive`` event every `KEEPALIVE_SECONDS` so no proxy or read timeout sees
an idle stream. A question left open for `MAX_WAIT_SECONDS` counts as no answer,
so an abandoned browser cannot hold a turn forever.

The policy travels in a ContextVar like approvals.py's, set per ask() call; a
delegated agent never gets an enabled policy.
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any

from src.agents import ask_user
from src.llm import cancellation
from src.llm.base_provider import ChatCancelled, OnEvent, step_event

MAX_WAIT_SECONDS = 3600.0
KEEPALIVE_SECONDS = 20.0
POLL_SECONDS = 0.5

NO_CHANNEL = "There is no way to ask the user a question from here, so nothing was asked. Continue with your best judgement."
NOT_OFFERED = "ask_user is not available in this conversation, so nothing was asked. Continue with your best judgement."
SKIPPED = "The user skipped these questions. Continue with your best judgement and say what you assumed."
TIMED_OUT = "The user did not answer in time. Continue with your best judgement and say what you assumed."


@dataclass
class QuestionPolicy:
    enabled: bool = False


_policy: ContextVar[QuestionPolicy] = ContextVar("question_policy", default=QuestionPolicy())


def bind(policy: QuestionPolicy) -> Token:
    return _policy.set(policy)


def reset(token: Token) -> None:
    _policy.reset(token)


def current() -> QuestionPolicy:
    return _policy.get()


@dataclass(frozen=True)
class Answer:
    # answered | skipped | timeout | cancelled
    outcome: str
    answers: tuple[dict[str, Any], ...] = ()


class QuestionBroker:
    """The questions waiting on a user, keyed by (request_id, step_id).

    `answer()` and `wait()` both run on the server's event loop (the
    `answer_question` MCP tool is async), so futures are set and awaited on the
    same loop."""

    def __init__(
        self,
        timeout: float = MAX_WAIT_SECONDS,
        poll: float = POLL_SECONDS,
        keepalive: float = KEEPALIVE_SECONDS,
    ) -> None:
        self._timeout = timeout
        self._poll = poll
        self._keepalive = keepalive
        self._pending: dict[tuple[str, str], asyncio.Future[Answer]] = {}

    async def wait(self, request_id: str, step_id: str, on_event: OnEvent | None = None) -> Answer:
        """The user's answer, or a skip, `timeout` or `cancelled`. A second
        wait on the same step replaces the first, which then reads as skipped."""
        loop = asyncio.get_running_loop()
        key = (request_id, step_id)
        previous = self._pending.get(key)
        if previous is not None and not previous.done():
            previous.set_result(Answer("skipped"))
        future: asyncio.Future[Answer] = loop.create_future()
        self._pending[key] = future
        deadline = loop.time() + self._timeout
        next_keepalive = loop.time() + self._keepalive
        try:
            while True:
                if cancellation.is_cancelled(request_id):
                    return Answer("cancelled")
                now = loop.time()
                remaining = deadline - now
                if remaining <= 0:
                    return Answer("timeout")
                if on_event is not None and now >= next_keepalive:
                    await on_event(step_event("keepalive"))
                    next_keepalive = now + self._keepalive
                try:
                    return await asyncio.wait_for(asyncio.shield(future), min(self._poll, remaining))
                except asyncio.TimeoutError:
                    continue
        finally:
            if self._pending.get(key) is future:
                del self._pending[key]

    def answer(self, request_id: str, step_id: str, answers: list[dict[str, Any]], skipped: bool) -> bool:
        """Answers a pending question. False when there is none: unknown step,
        already answered, or the turn moved on."""
        future = self._pending.get((request_id, step_id))
        if future is None or future.done():
            return False
        future.set_result(Answer("skipped") if skipped else Answer("answered", tuple(answers)))
        return True


BROKER = QuestionBroker()


def format_answers(asked: list[dict[str, Any]], answers: Any) -> str:
    """What the model is told the user chose, one line per question."""
    given = list(answers or [])
    lines = ["The user answered:"]
    for index, question in enumerate(asked):
        entry = given[index] if index < len(given) and isinstance(given[index], dict) else {}
        chosen = [str(label) for label in entry.get("selected") or []]
        other = str(entry.get("other") or "").strip()
        parts = [", ".join(chosen)] if chosen else []
        if other:
            parts.append(f"other: {other}")
        lines.append(f"- {question['question']}: {'; '.join(parts) or '(no answer)'}")
    return "\n".join(lines)


async def ask(
    request_id: str | None,
    step_id: str,
    asked: list[dict[str, Any]],
    on_event: OnEvent | None,
) -> str:
    """Puts the questions to the user and returns the text the model gets as
    the tool's result. Raises ChatCancelled if the user stops the turn while
    it waits."""
    if on_event is None or not request_id:
        return NO_CHANNEL
    await on_event(step_event("question_request", id=step_id, questions=asked))
    answer = await BROKER.wait(request_id, step_id, on_event)
    await on_event(step_event("question_resolved", id=step_id, outcome=answer.outcome))
    if answer.outcome == "cancelled":
        await on_event(step_event("step_end", id=step_id, ok=False, result="Stopped before it was answered."))
        raise ChatCancelled()
    if answer.outcome == "answered":
        return format_answers(asked, answer.answers)
    return TIMED_OUT if answer.outcome == "timeout" else SKIPPED


async def handle(
    name: str,
    request_id: str | None,
    step_id: str,
    arguments: Any,
    on_event: OnEvent | None,
) -> tuple[str, bool] | None:
    """None when `name` is not the ask_user tool (the caller carries on as for
    any other tool). Otherwise (the tool's result text, whether it succeeded)."""
    if name != ask_user.TOOL_NAME:
        return None
    if not current().enabled:
        return NOT_OFFERED, False
    asked, problem = ask_user.validate(arguments)
    if asked is None:
        return str(problem), False
    return await ask(request_id, step_id, asked, on_event), True
```

- [ ] **Step 8: Run to verify they pass**

Run: `python -m pytest tests/test_ask_user.py tests/test_questions.py -q`
Expected: PASS. If `test_stop_ends_the_wait` fails because `cancellation.cancel` needs a registered id, keep the `cancellation.register(REQUEST)` line shown there (look at `src/llm/cancellation.py` for the exact functions: `register`, `cancel`, `is_cancelled`, `clear`).

- [ ] **Step 9: Commit (ask the user first)**

```bash
git add apps/ai_agent/src/agents/ask_user.py apps/ai_agent/src/core/questions.py apps/ai_agent/tests/test_ask_user.py apps/ai_agent/tests/test_questions.py
git commit -m "feat(ai_agent): ask_user tool schema and question broker"
```

---

### Task 2: Wire `ask_user` into the providers, agent_config and server (ai_agent)

**Files:**
- Modify: `apps/ai_agent/src/llm/anthropic_provider.py` (imports ~line 46-48; `_tool_schemas` ~227-255; shortlist ~277; tool loop ~365-382)
- Modify: `apps/ai_agent/src/llm/openai_provider.py` (imports; `_tool_schemas` ~203-232; shortlist ~283; tool loop ~376-392)
- Modify: `apps/ai_agent/src/agents/agent_config.py` (imports line 20; `run_chat` 88-173)
- Modify: `apps/ai_agent/src/server.py` (`ask` ~169-275, `status` ~306, new tool after `decide` ~322)
- Test: `apps/ai_agent/tests/test_questions.py` (append)

**Interfaces:**
- Consumes (Task 1): everything under Produces there.
- Produces (used by Tasks 3-4): MCP `ask(..., ask_user: bool = False)`; MCP tool `answer_question(request_id: str, step_id: str, answers: list[dict] | None = None, skipped: bool = False) -> {"answered": bool}`; `status()` now includes `"user_questions": True`; events `question_request`, `question_resolved`, `keepalive` flow through `on_event`.

- [ ] **Step 1: Write the failing tests**

Append to `apps/ai_agent/tests/test_questions.py`. First extend the imports at the top with:

```python
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from src import server
from src.core import approvals
from src.llm import anthropic_provider, openai_provider
from src.llm.base_provider import ChatResult
```

then add:

```python
# --- the providers' tool loops ----------------------------------------------------------------

ASK_ARGUMENTS = {"questions": QUESTIONS}


def _anthropic_client(arguments):
    tool_block = MagicMock(type="tool_use", input=arguments, id="t1")
    tool_block.name = ask_user.TOOL_NAME
    first = MagicMock(stop_reason="tool_use", content=[tool_block])
    first.usage.input_tokens = 10
    first.usage.output_tokens = 5
    second = MagicMock(stop_reason="end_turn", content=[])
    second.usage.input_tokens = 3
    second.usage.output_tokens = 1

    def round_cm(chunks, final):
        async def gen():
            for chunk in chunks:
                yield chunk

        stream = MagicMock()
        stream.text_stream = gen()
        stream.get_final_message = AsyncMock(return_value=final)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=stream)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    client = MagicMock()
    client.messages.stream = MagicMock(side_effect=[round_cm([], first), round_cm(["Done"], second)])
    return client


def anthropic_turn(monkeypatch, recorder, dispatch, enabled=True, approval_mode="off"):
    client = _anthropic_client(ASK_ARGUMENTS)
    monkeypatch.setattr(anthropic_provider, "_get_client", lambda: client)
    monkeypatch.setattr(anthropic_provider, "_dispatch", dispatch)
    monkeypatch.setattr(anthropic_provider, "_tool_schemas", lambda enabled_extensions=None, roster=(): [])

    async def scenario():
        policy = questions.bind(questions.QuestionPolicy(enabled))
        approval = approvals.bind(approvals.ApprovalPolicy(approval_mode))
        try:
            return await anthropic_provider.run_chat("which?", [], request_id=REQUEST, on_event=recorder)
        finally:
            approvals.reset(approval)
            questions.reset(policy)

    return run(scenario()), client


def test_anthropic_asks_the_user_and_feeds_the_answers_back(monkeypatch) -> None:
    dispatch = Mock(return_value="never")
    rec = Recorder(answers=ANSWERS)

    result, client = anthropic_turn(monkeypatch, rec, dispatch)

    assert result.response == "Done"
    dispatch.assert_not_called()
    steps = [t for t in rec.types() if t in ("step_start", "question_request", "question_resolved", "step_end")]
    assert steps == ["step_start", "question_request", "question_resolved", "step_end"]
    expected = questions.format_answers(QUESTIONS, ANSWERS)
    sent = client.messages.stream.call_args_list[1].kwargs["messages"][-1]["content"][0]
    assert sent["content"] == expected
    assert result.tool_calls[0].result == expected


def test_anthropic_is_not_gated_by_tool_approval(monkeypatch) -> None:
    rec = Recorder(answers=ANSWERS)

    anthropic_turn(monkeypatch, rec, Mock(), approval_mode="ask")

    assert "approval_request" not in rec.types()


def test_anthropic_refuses_the_tool_when_it_was_not_offered(monkeypatch) -> None:
    rec = Recorder()

    result, _ = anthropic_turn(monkeypatch, rec, Mock(), enabled=False)

    assert "question_request" not in rec.types()
    assert result.tool_calls[0].result == questions.NOT_OFFERED


def test_anthropic_stop_while_a_question_is_open_cancels_the_turn(monkeypatch) -> None:
    rec = Recorder()

    async def stopper(event: dict) -> None:
        await rec(event)
        if event["type"] == "question_request":
            asyncio.get_running_loop().call_later(0.05, cancellation.cancel, REQUEST)

    with pytest.raises(ChatCancelled):
        anthropic_turn(monkeypatch, stopper, Mock())

    assert rec.types()[-1] == "step_end"


def test_anthropic_offers_the_schema_only_when_enabled() -> None:
    with patch("src.llm.anthropic_provider.list_tools", return_value=[]):
        off = anthropic_provider._tool_schemas([], ())
        token = questions.bind(questions.QuestionPolicy(True))
        try:
            on = anthropic_provider._tool_schemas([], ())
        finally:
            questions.reset(token)

    assert [s["name"] for s in off] == []
    assert [s["name"] for s in on] == [ask_user.TOOL_NAME]
    assert on[0]["input_schema"] == ask_user.tool_parameters()


def _openai_client(arguments):
    import json

    def stream_cm(deltas, final):
        events = [SimpleNamespace(type="response.output_text.delta", delta=text) for text in deltas]

        async def _aiter():
            for event in events:
                yield event

        stream = MagicMock()
        stream.__aiter__ = Mock(return_value=_aiter())
        stream.get_final_response = AsyncMock(return_value=final)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=stream)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    call = SimpleNamespace(
        type="function_call", call_id="call-1", name=ask_user.TOOL_NAME, arguments=json.dumps(arguments)
    )
    one = SimpleNamespace(usage=SimpleNamespace(total_tokens=10), output=[call])
    two = SimpleNamespace(usage=SimpleNamespace(total_tokens=2), output=[], output_text="Done")
    return SimpleNamespace(responses=SimpleNamespace(stream=Mock(side_effect=[stream_cm([], one), stream_cm(["Done"], two)])))


def openai_turn(monkeypatch, recorder, enabled=True):
    monkeypatch.setenv("GPT_API_KEY", "sk-test")
    dispatch = Mock(return_value="never")

    async def scenario():
        policy = questions.bind(questions.QuestionPolicy(enabled))
        try:
            with patch("src.llm.openai_provider._get_client", return_value=_openai_client(ASK_ARGUMENTS)), \
                 patch("src.llm.openai_provider._dispatch", dispatch), \
                 patch("src.llm.openai_provider.list_tools", return_value=[]):
                return await openai_provider.run_chat("which?", [], request_id=REQUEST, on_event=recorder)
        finally:
            questions.reset(policy)

    return run(scenario()), dispatch


def test_openai_asks_the_user_and_feeds_the_answers_back(monkeypatch) -> None:
    rec = Recorder(answers=ANSWERS)

    result, dispatch = openai_turn(monkeypatch, rec)

    assert result.response == "Done"
    dispatch.assert_not_called()
    request = [e for e in rec.events if e["type"] == "question_request"][0]
    assert (request["id"], request["questions"]) == ("call-1", QUESTIONS)
    assert result.tool_calls[0].result == questions.format_answers(QUESTIONS, ANSWERS)


def test_openai_refuses_the_tool_when_it_was_not_offered(monkeypatch) -> None:
    rec = Recorder()

    result, _ = openai_turn(monkeypatch, rec, enabled=False)

    assert "question_request" not in rec.types()
    assert result.tool_calls[0].result == questions.NOT_OFFERED


def test_openai_offers_the_schema_only_when_enabled() -> None:
    with patch("src.llm.openai_provider.list_tools", return_value=[]):
        off = openai_provider._tool_schemas([], ())
        token = questions.bind(questions.QuestionPolicy(True))
        try:
            on = openai_provider._tool_schemas([], ())
        finally:
            questions.reset(token)

    assert [s["name"] for s in off] == []
    assert [s["name"] for s in on] == [ask_user.TOOL_NAME]
    assert on[0]["parameters"] == ask_user.tool_parameters()


# --- ask() / answer_question / agent_config ------------------------------------------------------------


def _result() -> ChatResult:
    return ChatResult(response="ok", provider_id="anthropic", model="m", total_tokens=1)


def _ask_kwargs(**arguments) -> dict:
    async def scenario():
        with patch("src.server.agent_config.run_chat", new_callable=AsyncMock, return_value=_result()) as run_chat, \
             patch("src.server.agent_config.status", return_value={"context_window": 1, "model": "m"}):
            await server.ask("q", request_id="r", **arguments)
        return run_chat.call_args.kwargs

    return run(scenario())


def test_ask_passes_ask_user_on_and_defaults_it_off() -> None:
    assert _ask_kwargs(ask_user=True)["ask_user"] is True
    assert _ask_kwargs()["ask_user"] is False


def test_run_chat_enables_the_policy_for_a_top_level_turn_only() -> None:
    from src.agents import agent_config

    seen: list[bool] = []

    async def fake_provider_run_chat(*args, **kwargs):
        seen.append(questions.current().enabled)
        return _result()

    with patch.object(agent_config._PROVIDER_MODULE, "run_chat", fake_provider_run_chat):
        run(agent_config.run_chat("q", [], [], request_id=REQUEST, ask_user=True))
        run(agent_config.run_chat("q", [], [], request_id=REQUEST, ask_user=False))
        run(agent_config.run_chat("q", [], [], request_id=REQUEST, depth=1, ask_user=True))

    assert seen == [True, False, False]
    assert questions.current().enabled is False


def test_answer_question_answers_a_pending_question() -> None:
    async def scenario():
        waiter = asyncio.create_task(questions.BROKER.wait(REQUEST, "s1"))
        await asyncio.sleep(0)
        answered = await server.answer_question(REQUEST, "s1", ANSWERS, False)
        return answered, await waiter

    answered, answer = run(scenario())

    assert answered == {"answered": True}
    assert (answer.outcome, list(answer.answers)) == ("answered", ANSWERS)


def test_answer_question_can_skip_and_reports_when_nothing_is_waiting() -> None:
    async def scenario():
        waiter = asyncio.create_task(questions.BROKER.wait(REQUEST, "s1"))
        await asyncio.sleep(0)
        skipped = await server.answer_question(REQUEST, "s1", None, True)
        return skipped, (await waiter).outcome, await server.answer_question(REQUEST, "s1", None, True)

    assert run(scenario()) == ({"answered": True}, "skipped", {"answered": False})


def test_status_says_questions_are_understood() -> None:
    with patch("src.server.agent_config.status", return_value={"available": True}):
        assert server.status()["user_questions"] is True
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_questions.py -q`
Expected: the new tests FAIL (`_tool_schemas` offers nothing; `ask() got an unexpected keyword 'ask_user'`; `server.answer_question` missing; tool calls go to `dispatch`).

- [ ] **Step 3: anthropic provider**

In `apps/ai_agent/src/llm/anthropic_provider.py`:

Imports: change `from src.agents import agent_routing, agent_spec, delegation` to
`from src.agents import agent_routing, agent_spec, ask_user, delegation` and `from src.core import approvals` to `from src.core import approvals, questions`.

In `_tool_schemas`, after the `if roster:` block and before `return schemas`:

```python
    # Only the top-level agent of a turn whose caller can show questions.
    if questions.current().enabled:
        schemas.append(
            {
                "name": ask_user.TOOL_NAME,
                "description": ask_user.tool_description(),
                "input_schema": ask_user.tool_parameters(),
                "display_label": None,
            }
        )
```

Change the shortlist call to keep the tool:

```python
    schemas = await tool_selection.shortlist_schemas(question, schemas, {delegation.TOOL_NAME, ask_user.TOOL_NAME})
```

In the tool loop replace this segment (from the `# With approvals on` comment through the `ok = False` of the `except`) with:

```python
                # ask_user waits for the user's answers, not for an approval: it
                # is not gated by tool approval and never reaches _dispatch.
                asked = await questions.handle(block.name, request_id, step_id, block.input, on_event)
                if asked is not None:
                    result_text, ok = asked
                else:
                    # With approvals on, the user answers before anything runs; a
                    # refusal is handed to the model as this step's result.
                    declined = await approvals.review(
                        request_id, step_id, block.name, labels.get(block.name), block.input, on_event
                    )
                    if declined is not None:
                        result_text, ok = declined, False
                    else:
                        try:
                            result_text = await dispatch_with_progress(_dispatch, on_event, step_id, block.name, block.input, depth)
                            ok = True
                        except Exception as error:
                            result_text = f"Tool '{block.name}' failed: {error}"
                            ok = False
```

(the following `if on_event: await on_event(step_event("step_end", ...))` stays as is).

- [ ] **Step 4: openai provider**

In `apps/ai_agent/src/llm/openai_provider.py` make the same three kinds of change.

Imports: add `ask_user` to the `from src.agents import ...` line that imports `delegation`, and `questions` to the `from src.core import approvals` line (check the exact import lines at the top of the file first).

In `_tool_schemas`, after the `if roster:` block:

```python
    # Only the top-level agent of a turn whose caller can show questions.
    if questions.current().enabled:
        schemas.append(
            {
                "type": "function",
                "name": ask_user.TOOL_NAME,
                "description": ask_user.tool_description(),
                "parameters": ask_user.tool_parameters(),
                "display_label": None,
            }
        )
```

Shortlist: `await tool_selection.shortlist_schemas(question, schemas, {delegation.TOOL_NAME, ask_user.TOOL_NAME})`.

Tool loop: replace the segment from `# With approvals on` through the `ok = False` of the `except` with:

```python
                # ask_user waits for the user's answers, not for an approval: it
                # is not gated by tool approval and never reaches _dispatch.
                asked = await questions.handle(call.name, request_id, step_id, arguments, on_event)
                if asked is not None:
                    result_text, ok = asked
                else:
                    # With approvals on, the user answers before anything runs; a
                    # refusal is handed to the model as this step's result.
                    declined = await approvals.review(
                        request_id, step_id, call.name, labels.get(call.name), arguments, on_event
                    )
                    if declined is not None:
                        result_text, ok = declined, False
                    else:
                        try:
                            result_text = await dispatch_with_progress(_dispatch, on_event, step_id, call.name, arguments, depth)
                            ok = True
                        except Exception as error:
                            result_text = f"Tool '{call.name}' failed: {error}"
                            ok = False
```

If other providers exist with the same loop (`Grep` for `approvals.review(` in `src/llm/`; the earlier search found only these two), apply the same change.

- [ ] **Step 5: agent_config**

In `apps/ai_agent/src/agents/agent_config.py`: change `from src.core import approvals, tool_filter` to `from src.core import approvals, questions, tool_filter`; add `ask_user: bool = False,` after `disabled_tools` in the `run_chat` signature; add to the docstring: `ask_user: the caller can show the user clickable questions (core/questions.py); only a top-level turn (depth 0) is offered the tool.`; bind and reset:

```python
    approval_token = approvals.bind(policy)
    question_token = questions.bind(questions.QuestionPolicy(ask_user and depth == 0))
```
and in `finally`, before `approvals.reset(approval_token)`:
```python
        questions.reset(question_token)
```

- [ ] **Step 6: server**

In `apps/ai_agent/src/server.py`:

- Add `ask_user: bool = False,` to `ask()`'s parameters after `reasoning_effort` and before `ctx`, and to the docstring: `ask_user: the caller can show the user clickable questions and send their answers back through answer_question(); only then is the ask_user tool offered (top-level turns only).`
- Pass it through: in the `agent_config.run_chat(...)` call add `ask_user=ask_user,` next to `disabled_tools=disabled_tools,`.
- In `status()`: `return {**agent_config.status(), "tool_approval": True, "tool_filter": True, "user_questions": True}` and extend its docstring with `user_questions` says ask() understands ask_user.
- After the `decide` tool add:

```python
@mcp.tool()
async def answer_question(
    request_id: str,
    step_id: str,
    answers: list[dict[str, Any]] | None = None,
    skipped: bool = False,
) -> dict[str, Any]:
    """Answers the questions an ask() call raised with a `question_request`
    event: `answers` has one entry per question, in order, each
    {"selected": [option labels], "other": typed text or null}; or pass
    skipped=True to decline. Returns {"answered": False} when nothing is
    waiting for that request and step - unknown, already answered, or the
    turn ended."""
    return {"answered": questions.BROKER.answer(request_id, step_id, answers or [], skipped)}
```
and add `questions` to the `from src.core import ...` line at the top of `ask`'s module (the existing line imports `approvals, internal_auth, usage_log`; check line 74 of `server.py`, it is a local import inside a function, so also add `questions` where `approvals` is imported at module level, and find that with Grep `import approvals`).

- [ ] **Step 7: Run to verify they pass**

Run: `python -m pytest tests/test_questions.py tests/test_approvals.py -q`
Expected: PASS (approvals tests prove the shared loop edit did not break them).

- [ ] **Step 8: Run the whole ai_agent suite**

Run: `python -m pytest -q`
Expected: PASS. A test that lists the MCP tools of `server` or asserts the exact `status()` dict may need `answer_question` / `user_questions` added; fix such expectations only.

- [ ] **Step 9: Commit (ask the user first)**

```bash
git add apps/ai_agent/src apps/ai_agent/tests/test_questions.py
git commit -m "feat(ai_agent): offer ask_user to top-level turns and answer it through answer_question"
```

(Check `git status` first: stage only files this task changed. Add other test files by name if Step 8 needed edits.)

---

### Task 3: Gateway, turns and snapshot (ember_api)

**Files:**
- Create: `apps/ember_api/src/services/question_answers.py`
- Modify: `apps/ember_api/src/services/agent_gateway.py` (Protocol ~46-67, `ask` ~114-159, after `decide` ~172)
- Modify: `apps/ember_api/src/services/turns.py` (`TurnOptions` 73-85, `Turn` 111-165, `answer`/`pending_question` near 276-291, `_publish` 351-386, `on_event` ~434, gateway.ask call ~443, `_clamped` ~575)
- Modify: `apps/ember_api/tests/conftest.py` (`FakeAgent` ~85-215)
- Test: `apps/ember_api/tests/test_agent_gateway.py` (edit + append), `apps/ember_api/tests/test_questions.py` (create; Task 4 appends route tests)

**Interfaces:**
- Consumes (Task 2): MCP `ask(..., ask_user)`, `answer_question`, `status.user_questions`.
- Produces (used by Task 4):
  - `question_answers.clamp_questions(raw: Any) -> list[dict]`; `question_answers.check_answers(questions: list[dict], answers: list[dict]) -> str | None` (an error message or None).
  - `AgentGateway.ask(..., ask_user: bool = False)`; `AgentGateway.answer_question(url, caller, request_id, step_id, answers: list[dict], skipped: bool) -> bool`.
  - `TurnOptions.can_ask: bool = False`; `Turn.pending_questions: dict[str, dict]` (step id -> `{"id", "questions"}`); snapshot key `"questions"`; `TurnRegistry.pending_question(account_id, chat_id, step_id) -> dict | None`; `async TurnRegistry.answer(account_id, chat_id, step_id, answers, skipped) -> bool`.
  - `FakeAgent`: attrs `questions: list[dict]`, `answers: list[tuple]`, `answer_result`, `answer_error`; `asks[...]["ask_user"]`.

- [ ] **Step 1: Write the failing service tests**

Create `apps/ember_api/tests/test_questions.py`:

```python
"""Clickable questions: the clamping and checking helpers, the turn's pending
question and snapshot, and (Task 4) the answer route."""

from __future__ import annotations

from src.services import question_answers as qa

QUESTIONS = [
    {
        "header": "Format",
        "question": "Which format?",
        "multi_select": False,
        "options": [{"label": "CSV"}, {"label": "JSON", "description": "Structured"}],
    },
    {
        "header": "Extras",
        "question": "Which extras?",
        "multi_select": True,
        "options": [{"label": "Totals"}, {"label": "Chart"}, {"label": "Title"}],
    },
]


# --- clamp_questions -------------------------------------------------------------------


def test_clamp_keeps_a_good_request_as_it_is() -> None:
    assert qa.clamp_questions(QUESTIONS) == QUESTIONS


def test_clamp_cuts_long_text_and_extra_questions_and_options() -> None:
    raw = [
        {
            "header": "h" * 40,
            "question": "q" * 500,
            "multi_select": "truthy",
            "options": [{"label": "l" * 200, "description": "d" * 400}] + [{"label": f"o{i}"} for i in range(8)],
        }
    ] * 6

    clamped = qa.clamp_questions(raw)

    assert len(clamped) == qa.MAX_QUESTIONS
    first = clamped[0]
    assert len(first["header"]) == qa.HEADER_MAX and len(first["question"]) == qa.QUESTION_MAX
    assert first["multi_select"] is True
    assert len(first["options"]) == qa.MAX_OPTIONS
    assert len(first["options"][0]["label"]) == qa.LABEL_MAX
    assert len(first["options"][0]["description"]) == qa.DESCRIPTION_MAX


def test_clamp_drops_anything_that_is_not_a_question() -> None:
    assert qa.clamp_questions("nope") == []
    assert qa.clamp_questions([1, None, {"header": "x"}]) == []
    assert qa.clamp_questions([{"header": "x", "question": "y", "options": ["A", {"label": "B"}, {"nolabel": 1}]}]) == [
        {"header": "x", "question": "y", "multi_select": False, "options": [{"label": "B"}]}
    ]


# --- check_answers ---------------------------------------------------------------------


def ok(selected, other=None):
    return {"selected": selected, "other": other}


def test_a_complete_answer_passes() -> None:
    assert qa.check_answers(QUESTIONS, [ok(["CSV"]), ok(["Totals", "Chart"], "and a title")]) is None


def test_other_alone_is_an_answer() -> None:
    assert qa.check_answers(QUESTIONS, [ok([], "XML"), ok(["Title"])]) is None


def test_bad_answers_are_described() -> None:
    cases = {
        "too few answers": [ok(["CSV"])],
        "too many answers": [ok(["CSV"]), ok(["Chart"]), ok(["Title"])],
        "nothing chosen": [ok([]), ok(["Chart"])],
        "blank other only": [ok([], "   "), ok(["Chart"])],
        "an unknown label": [ok(["XML"]), ok(["Chart"])],
        "two for a single-select": [ok(["CSV", "JSON"]), ok(["Chart"])],
        "the same label twice": [ok(["CSV"]), ok(["Chart", "Chart"])],
    }
    for name, answers in cases.items():
        problem = qa.check_answers(QUESTIONS, answers)
        assert isinstance(problem, str) and problem, name
```

- [ ] **Step 2: Run to verify it fails**

Run (from `apps/ember_api/`): `.venv_ember_api\Scripts\python -m pytest tests/test_questions.py -q`
Expected: FAIL (`ImportError: cannot import name 'question_answers'`).

- [ ] **Step 3: Write `question_answers.py`**

Create `apps/ember_api/src/services/question_answers.py`:

```python
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
```

- [ ] **Step 4: Run to verify the helper tests pass**

Run: `.venv_ember_api\Scripts\python -m pytest tests/test_questions.py -q`
Expected: PASS.

- [ ] **Step 5: Gateway - failing tests**

In `apps/ember_api/tests/test_agent_gateway.py`:

In `_build_agent`, add `ask_user: bool = False,` to the fake `ask` signature (after `disabled_tools`, before `ctx`), add `"ask_user": ask_user,` to the returned dict, include the new flag in `status` (`{"tool_approval": True, "tool_filter": True, "user_questions": True}`), and add a tool after `decide`:

```python
    @mcp.tool()
    def answer_question(
        request_id: str, step_id: str, answers: list[dict] | None = None, skipped: bool = False
    ) -> dict[str, Any]:
        return {"answered": (request_id, step_id) == ("r1", "s1"), "echo": {"answers": answers, "skipped": skipped}}
```

Append tests at the end of the file:

```python
# --- clickable questions -----------------------------------------------------------------


def test_ask_sends_ask_user_when_the_agent_understands_it(agent_url: str) -> None:
    result = _ask(McpAgentGateway(None), agent_url, ask_user=True)

    assert result["ask_user"] is True


def test_ask_leaves_ask_user_out_by_default(agent_url: str) -> None:
    assert _ask(McpAgentGateway(None), agent_url)["ask_user"] is False


def test_an_agent_that_does_not_know_ask_user_just_does_not_get_it(old_agent_url: str) -> None:
    result = _ask(McpAgentGateway(None), old_agent_url, ask_user=True)

    assert result["ask_user"] is False  # the question tool is simply not offered; the turn still runs


def test_answer_reports_whether_the_question_was_waiting(agent_url: str) -> None:
    gateway = McpAgentGateway(None)
    answers = [{"selected": ["CSV"], "other": None}]

    assert asyncio.run(gateway.answer_question(agent_url, CALLER, "r1", "s1", answers, False)) is True
    assert asyncio.run(gateway.answer_question(agent_url, CALLER, "r1", "nope", [], True)) is False
```

Run: `.venv_ember_api\Scripts\python -m pytest tests/test_agent_gateway.py -q`
Expected: FAIL (`unexpected keyword argument 'ask_user'`, `no attribute 'answer'`).

- [ ] **Step 6: Gateway - implementation**

In `apps/ember_api/src/services/agent_gateway.py`:

Protocol `ask`: add `ask_user: bool = False,` after `disabled_tools`; add after `decide` in the Protocol:

```python
    async def answer_question(
        self, url: str, caller: Caller, request_id: str, step_id: str, answers: list[dict[str, Any]], skipped: bool
    ) -> bool: ...
```

In `McpAgentGateway.ask` add `ask_user=False,` to the signature and, before `return await self._call(url, caller, "ask", ...)`:

```python
        if ask_user:
            # Not fail-closed like approvals: an agent from before this existed
            # simply does not get the question tool, and the turn still runs.
            status = await self._call(url, caller, "status", {})
            if status.get("user_questions"):
                arguments["ask_user"] = True
```

After `decide` add:

```python
    async def answer_question(self, url, caller, request_id, step_id, answers, skipped):
        """Sends the user's answers to a question the agent raised for this turn.
        False when nothing was waiting (already answered, or the turn ended)."""
        result = await self._call(
            url,
            caller,
            "answer_question",
            {"request_id": request_id, "step_id": step_id, "answers": answers, "skipped": skipped},
        )
        return bool(result.get("answered"))
```

Run: `.venv_ember_api\Scripts\python -m pytest tests/test_agent_gateway.py -q` - Expected: PASS.

- [ ] **Step 7: FakeAgent support**

In `apps/ember_api/tests/conftest.py`, in `FakeAgent`:

Add fields after `decide_error`:

```python
    # A question this fake "asks" during a turn (the questions list of an ask_user call).
    questions: list[dict] = field(default_factory=list)
    answers: list[tuple] = field(default_factory=list)  # (request_id, step_id, answers, skipped)
    answer_result: bool | None = None  # force answer_question()'s result
    answer_error: str | None = None
    _asking: dict = field(default_factory=dict)
```

`ask(...)`: add `ask_user=False,` to the signature, `"ask_user": ask_user,` to the recorded dict, and after the `for index, tool in enumerate(self.tool_calls): ...` loop:

```python
        if self.questions:
            await self._ask_user("q1", request_id, on_event)
```

Add methods:

```python
    async def _ask_user(self, step_id, request_id, on_event):
        await on_event(
            {"type": "step_start", "id": step_id, "tool": "ask_user", "label": None, "arguments": {"questions": self.questions}}
        )
        waiting = asyncio.get_running_loop().create_future()
        self._asking[(request_id, step_id)] = waiting
        await on_event({"type": "question_request", "id": step_id, "questions": self.questions})
        outcome = await waiting
        del self._asking[(request_id, step_id)]
        await on_event({"type": "question_resolved", "id": step_id, "outcome": outcome})
        await on_event({"type": "step_end", "id": step_id, "ok": outcome != "cancelled", "result": f"outcome: {outcome}"})

    async def answer_question(self, url, caller, request_id, step_id, answers, skipped):
        if self.answer_error:
            raise AgentCallError(self.answer_error)
        self.answers.append((request_id, step_id, answers, skipped))
        waiting = self._asking.get((request_id, step_id))
        known = waiting is not None and not waiting.done()
        if self.answer_result is not None:
            known = self.answer_result
        if known and waiting is not None and not waiting.done():
            waiting.set_result("skipped" if skipped else "answered")
        return known
```

and in `cancel`, next to the existing loop over `self._waiting`:

```python
        for (waiting_request, _step), waiting in list(self._asking.items()):
            if waiting_request == request_id and not waiting.done():
                waiting.set_result("cancelled")
```

- [ ] **Step 8: Turns - failing tests**

Append to `apps/ember_api/tests/test_questions.py` (add imports at the top: `from fastapi.testclient import TestClient`, `from tests.conftest import FakeAgent`, `from tests.test_registration import as_admin`, `from tests.test_turns import events, new_id, start, wait_until`):

```python
# --- the turn: events, pending question, snapshot ----------------------------------------------


def waiting_question(client: TestClient, agent: FakeAgent, chat_id: str) -> None:
    """Starts a turn whose agent asks QUESTIONS and waits for the answer."""
    agent.questions = QUESTIONS
    start(client, chat_id, "which format?", can_ask=True)
    wait_until(lambda: bool(agent._asking))


def test_the_agent_is_told_the_browser_can_ask_only_when_it_says_so(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)

    start(client, new_id(), "plain")
    wait_until(lambda: len(agent.asks) == 1)
    start(client, new_id(), "asking", can_ask=True)
    wait_until(lambda: len(agent.asks) == 2)

    assert [a["ask_user"] for a in agent.asks] == [False, True]


def test_a_waiting_question_is_part_of_the_snapshot_and_clears_when_answered(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    waiting_question(client, agent, chat_id)
    registry = client.app.state.turns
    account_id = client.get("/api/auth/me").json()["id"]
    turn = registry.get(account_id, chat_id)

    assert turn.snapshot()["questions"] == [{"id": "q1", "questions": QUESTIONS}]
    assert registry.pending_question(account_id, chat_id, "q1") == {"id": "q1", "questions": QUESTIONS}
    assert registry.pending_question(account_id, chat_id, "other") is None

    answered = asyncio.run_coroutine_threadsafe(
        registry.answer(account_id, chat_id, "q1", [{"selected": ["CSV"], "other": None}], False), agent.loop
    ).result(5)
    wait_until(lambda: not turn.pending_questions)

    assert answered is True
    assert agent.answers[0][1:] == ("q1", [{"selected": ["CSV"], "other": None}], False)
    assert turn.snapshot()["questions"] == []
    wait_until(lambda: turn.status != "running")
```

Add `import asyncio` at the top of the file. Before running, check how the app exposes the `TurnRegistry` (`Grep` for `TurnRegistry(` in `src/app.py` and `get_turns` in `src/deps.py`) and replace `client.app.state.turns` with the real attribute in the two tests that use it. `agent.loop` is set by `FakeAgent.ask` only when `hold=True`, so also set `self.loop = asyncio.get_running_loop()` as the first line of `FakeAgent._ask_user` (Step 7).

Add one more test:

```python
def test_an_oversized_question_is_cut_down_before_it_is_shown(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    agent.questions = [
        {"header": "h" * 40, "question": "q" * 900, "multi_select": False, "options": [{"label": "A"}, {"label": "B"}]}
    ]
    start(client, chat_id, "go", can_ask=True)
    wait_until(lambda: bool(agent._asking))
    registry = client.app.state.turns
    account_id = client.get("/api/auth/me").json()["id"]

    shown = registry.pending_question(account_id, chat_id, "q1")["questions"][0]

    assert len(shown["header"]) == qa.HEADER_MAX and len(shown["question"]) == qa.QUESTION_MAX
```

Run: `.venv_ember_api\Scripts\python -m pytest tests/test_questions.py -q`
Expected: the turn tests FAIL (`can_ask` is ignored; no `pending_questions`).

- [ ] **Step 9: Turns - implementation**

In `apps/ember_api/src/services/turns.py`:

Import: `from src.services import question_answers` (next to the other `from src.services import ...` lines; follow the file's existing import style).

`TurnOptions`: add after `disabled_tools`:

```python
    # The browser can show the agent's clickable questions and send answers back.
    can_ask: bool = False
```

`Turn`: add after `pending_approvals`:

```python
    # Questions waiting for the user's answer, by step id: {id, questions}.
    pending_questions: dict[str, dict[str, Any]] = field(default_factory=dict)
```

`Turn.snapshot()`: add `"questions": [dict(q) for q in self.pending_questions.values()],` after `"approvals"`.

Add method after `record_approval`:

```python
    def record_question(self, event: dict[str, Any]) -> None:
        """Remembers questions that wait for the user, so a browser that joins
        late (or reloads) still gets them."""
        step_id = str(event.get("id") or "")
        if not step_id:
            return
        self.pending_questions[step_id] = {"id": step_id, "questions": event.get("questions") or []}
```

`TurnRegistry`: add after `decide`:

```python
    def pending_question(self, account_id: int, chat_id: str, step_id: str) -> dict[str, Any] | None:
        """The question set of this step that is waiting for an answer, if any."""
        turn = self.get(account_id, chat_id)
        if turn is None or turn.status != "running":
            return None
        return turn.pending_questions.get(step_id)

    async def answer(
        self, account_id: int, chat_id: str, step_id: str, answers: list[dict[str, Any]], skipped: bool
    ) -> bool:
        """Sends the user's answers (or a skip) for a waiting question of this
        account's running turn. False when it is not waiting (unknown, already
        answered, or the turn moved on). The agent then reports the outcome as a
        `question_resolved` event, which clears it for every watcher."""
        turn = self.get(account_id, chat_id)
        if turn is None or turn.status != "running" or step_id not in turn.pending_questions:
            return False
        return await self._gateway.answer_question(turn.agent.url, turn.caller, turn.request_id, step_id, answers, skipped)
```

`_publish`: in the `step_end` branch add `turn.pending_questions.pop(str(event.get("id") or ""), None)` after the approvals pop; add two branches after `approval_resolved`:

```python
            elif kind == "question_request":
                turn.activity = "waiting for your answer"
                turn.record_question(event)
            elif kind == "question_resolved":
                turn.activity = ""
                turn.pending_questions.pop(str(event.get("id") or ""), None)
```

and in the terminal branch add `turn.pending_questions.clear()` next to `turn.pending_approvals.clear()`.

`on_event` whitelist: add `"question_request", "question_resolved",` to the tuple of forwarded types.

The `self._gateway.ask(...)` call: add `ask_user=turn.options.can_ask,` after `disabled_tools=...`.

`_clamped`: add before `return event`:

```python
    if kind == "question_request":
        return {**event, "questions": question_answers.clamp_questions(event.get("questions"))}
```

- [ ] **Step 10: Route pass-through for the tests**

The tests call `start(client, chat_id, "...", can_ask=True)` which posts `can_ask` in the JSON body. Until Task 4 the route ignores it (extra field accepted?). Pydantic ignores unknown fields by default, so the `ask_user` assertions in Step 8 would fail for `True`. Add the field now in `apps/ember_api/src/routes/chats.py` `TurnRequest` (after `disabled_tools` validators... place it right after `ask_before_tools`/`allowed_tools`):

```python
    # The browser can show the agent's clickable questions (answers go to
    # POST /api/chats/{id}/questions). Off for clients that cannot, e.g. chat_cli.
    can_ask: bool = False
```
and in `start_turn`'s `TurnOptions(...)` add `can_ask=body.can_ask,`.

- [ ] **Step 11: Run to verify they pass**

Run: `.venv_ember_api\Scripts\python -m pytest tests/test_questions.py tests/test_agent_gateway.py tests/test_turns.py -q`
Expected: PASS.

- [ ] **Step 12: Whole ember_api suite**

Run: `.venv_ember_api\Scripts\python -m pytest -q`
Expected: PASS.

- [ ] **Step 13: Commit (ask the user first)**

```bash
git add apps/ember_api/src/services/question_answers.py apps/ember_api/src/services/agent_gateway.py apps/ember_api/src/services/turns.py apps/ember_api/src/routes/chats.py apps/ember_api/tests/conftest.py apps/ember_api/tests/test_agent_gateway.py apps/ember_api/tests/test_questions.py
git commit -m "feat(ember_api): carry the agent's clickable questions through a turn"
```

---

### Task 4: `POST /api/chats/{id}/questions` (ember_api)

**Files:**
- Modify: `apps/ember_api/src/routes/chats.py` (new models near `ApprovalRequest` ~246; route after `decide_approval` ~755)
- Test: `apps/ember_api/tests/test_questions.py` (append)
- Modify: `apps/ember_api/README.md`

**Interfaces:**
- Consumes (Task 3): `TurnRegistry.pending_question`, `TurnRegistry.answer`, `question_answers.check_answers`, `OTHER_MAX`.
- Produces (used by Task 5): `POST /api/chats/{chat_id}/questions` with `{step_id, skipped?, answers?}` returning `{"answered": true}`; errors 404 (no answer running), 409 (nothing waiting / already answered), 422 (invalid answer), 502 (agent unreachable).

- [ ] **Step 1: Write the failing tests**

Append to `apps/ember_api/tests/test_questions.py` (add `from tests.test_admin import login, make_member` and `from tests.conftest import FakeEmailSender` to the imports):

```python
# --- POST /api/chats/{id}/questions ----------------------------------------------------------------


def answer(client: TestClient, chat_id: str, **body):
    return client.post(f"/api/chats/{chat_id}/questions", json={"step_id": "q1", **body})


GOOD = [ok(["CSV"]), ok(["Totals", "Chart"], "and a title")]


def test_answering_needs_login(client: TestClient) -> None:
    assert answer(client, new_id(), skipped=True).status_code == 401


def test_answering_needs_chat_use(client: TestClient, email: FakeEmailSender) -> None:
    make_member(client, email, verify=False)
    login(client, "alice")

    assert answer(client, new_id(), skipped=True).status_code == 403


def test_answering_with_no_running_answer_is_404(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)

    assert answer(client, new_id(), skipped=True).status_code == 404


def test_answering_a_question_that_is_not_waiting_is_409(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    agent.hold = True
    start(client, chat_id, "no question here")
    wait_until(lambda: len(agent.asks) == 1)

    assert answer(client, chat_id, skipped=True).status_code == 409
    agent.release()


def test_a_valid_answer_reaches_the_agent_and_lets_the_turn_finish(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    waiting_question(client, agent, chat_id)

    response = answer(client, chat_id, answers=GOOD)

    assert response.status_code == 200
    assert response.json() == {"answered": True}
    assert agent.answers[0][1:] == ("q1", GOOD, False)
    stream = events(client, chat_id)
    assert [e["type"] for e in stream if e["type"] in ("question_resolved", "final")] == ["question_resolved", "final"]
    assert next(e for e in stream if e["type"] == "question_resolved")["outcome"] == "answered"


def test_skipping_needs_no_answers(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    waiting_question(client, agent, chat_id)

    response = answer(client, chat_id, skipped=True)

    assert response.status_code == 200
    assert agent.answers[0][1:] == ("q1", [], True)
    stream = events(client, chat_id)
    assert next(e for e in stream if e["type"] == "question_resolved")["outcome"] == "skipped"


def test_an_invalid_answer_is_422_and_changes_nothing(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    waiting_question(client, agent, chat_id)
    bad = {
        "too few": [ok(["CSV"])],
        "unknown label": [ok(["XML"]), ok(["Chart"])],
        "two for a single-select": [ok(["CSV", "JSON"]), ok(["Chart"])],
        "nothing chosen": [ok([]), ok(["Chart"])],
    }

    for name, answers in bad.items():
        response = answer(client, chat_id, answers=answers)
        assert response.status_code == 422, name
        assert response.json()["detail"], name
    assert agent.answers == []
    assert answer(client, chat_id, answers=GOOD).status_code == 200  # still waiting, and answerable


def test_body_limits_are_enforced(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    waiting_question(client, agent, chat_id)

    too_long = [ok(["CSV"], "x" * (qa.OTHER_MAX + 1)), ok(["Chart"])]
    assert answer(client, chat_id, answers=too_long).status_code == 422
    assert client.post(f"/api/chats/{chat_id}/questions", json={"skipped": True}).status_code == 422
    assert client.post(f"/api/chats/{chat_id}/questions", json={"step_id": "q1", "answers": "x"}).status_code == 422
    assert agent.answers == []
    answer(client, chat_id, skipped=True)


def test_a_second_answer_to_the_same_question_is_409(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    waiting_question(client, agent, chat_id)
    assert answer(client, chat_id, answers=GOOD).status_code == 200
    events(client, chat_id)  # the turn is over

    assert answer(client, chat_id, answers=GOOD).status_code in (404, 409)


def test_the_agent_saying_nothing_is_waiting_is_409(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    waiting_question(client, agent, chat_id)
    agent.answer_result = False

    assert answer(client, chat_id, answers=GOOD).status_code == 409
    agent.answer_result = None
    answer(client, chat_id, skipped=True)


def test_an_unreachable_agent_is_502(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    waiting_question(client, agent, chat_id)
    agent.answer_error = "agent down"

    assert answer(client, chat_id, answers=GOOD).status_code == 502
    agent.answer_error = None
    answer(client, chat_id, skipped=True)


def test_another_account_cannot_answer(client: TestClient, agent: FakeAgent, email: FakeEmailSender) -> None:
    as_admin(client)
    chat_id = new_id()
    waiting_question(client, agent, chat_id)
    make_member(client, email)
    login(client, "alice")

    assert answer(client, chat_id, skipped=True).status_code == 404
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv_ember_api\Scripts\python -m pytest tests/test_questions.py -q`
Expected: the route tests FAIL (404/405 for the missing route).

- [ ] **Step 3: Implement the route**

In `apps/ember_api/src/routes/chats.py`:

Import: add `question_answers` to the `from src.services import ...` line (it currently reads `from src.services import suggestions, summarization` if the prompt-suggestion work is merged, otherwise `from src.services import summarization`).

Models, after `ApprovalRequest`:

```python
class QuestionAnswerIn(BaseModel):
    # The labels of the options chosen, and the user's own typed answer.
    selected: list[str] = Field(default_factory=list, max_length=question_answers.MAX_OPTIONS)
    other: str | None = Field(default=None, max_length=question_answers.OTHER_MAX)


class QuestionRequest(BaseModel):
    # The question set being answered: the `id` of a question_request event.
    step_id: str = Field(min_length=1, max_length=200)
    # Decline to answer; the agent then goes on with its best judgement.
    skipped: bool = False
    # One entry per question, in order (ignored when skipped).
    answers: list[QuestionAnswerIn] = Field(default_factory=list, max_length=question_answers.MAX_QUESTIONS)
```

Route, after `decide_approval`:

```python
@router.post("/{chat_id}/questions")
async def answer_questions(
    body: QuestionRequest,
    chat_id: str = ChatId,
    account: Account = Depends(require_chat),
    turns: TurnRegistry = Depends(get_turns),
) -> dict[str, bool]:
    """Answers (or skips) the questions the running answer is waiting on (the
    `id` of a `question_request` event). Only the chat's own account can; once
    answered nothing else can answer them. The answer text is not logged: it
    is the user's own words, kept only in the chat's saved steps."""
    if not turns.is_running(account.id, chat_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No answer is being written for this chat")
    pending = turns.pending_question(account.id, chat_id, body.step_id)
    if pending is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Nothing is waiting for that answer")
    answers = [answer.model_dump() for answer in body.answers] if not body.skipped else []
    if not body.skipped:
        problem = question_answers.check_answers(pending["questions"], answers)
        if problem is not None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problem)
    try:
        answered = await turns.answer(account.id, chat_id, body.step_id, answers, body.skipped)
    except AgentCallError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error
    if not answered:
        raise HTTPException(status.HTTP_409_CONFLICT, "Nothing is waiting for that answer")
    return {"answered": True}
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv_ember_api\Scripts\python -m pytest tests/test_questions.py -q`
Expected: PASS. If `test_a_second_answer_to_the_same_question_is_409` flakes between 404 and 409 it is by design (the turn may be gone or still replayed); the assertion allows both.

- [ ] **Step 5: README**

In `apps/ember_api/README.md`, in the API table next to `POST /api/chats/{id}/approvals`, add (match the existing column layout):

```
| `POST /api/chats/{id}/questions` | `chat.use` | Answers or skips the clickable questions the running answer waits on (`question_request` event): `{step_id, skipped?, answers?: [{selected, other}]}`. 404 no answer running, 409 nothing waiting, 422 invalid answer. |
```

and in the turn request description add that `can_ask: true` lets the agent ask clickable questions (clients that cannot show them, such as `chat_cli`, leave it out), and in the events list add `question_request` / `question_resolved` (and that the snapshot carries `questions`).

- [ ] **Step 6: Whole suite**

Run: `.venv_ember_api\Scripts\python -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit (ask the user first)**

```bash
git add apps/ember_api/src/routes/chats.py apps/ember_api/tests/test_questions.py apps/ember_api/README.md
git commit -m "feat(ember_api): POST /api/chats/{id}/questions answers the agent's clickable questions"
```

---

### Task 5: Types, client and chat store (ember_web)

**Files:**
- Modify: `apps/ember_web/src/api/types.ts` (after `ApprovalDecision` ~88; `TurnEvent` ~92-110)
- Modify: `apps/ember_web/src/api/ChatsClient.ts` (`TurnStart` ~36-52; `chatsClient` after `decide` ~106)
- Modify: `apps/ember_web/src/stores/chat.ts` (state ~173; snapshot ~444; events ~467-485; `unfollow` ~540-553; `send` ~687-697; actions ~956; return ~1160)
- Test: `apps/ember_web/src/stores/chat.questions.test.ts` (create); existing store tests that assert the `startTurn` payload

**Interfaces:**
- Consumes (Task 4): `POST /api/chats/{id}/questions`.
- Produces (used by Task 6): types `QuestionOption`, `Question`, `PendingQuestion`, `QuestionAnswer`; `chatsClient.answerQuestion(id, stepId, payload: {answers: QuestionAnswer[]; skipped: boolean}) -> Promise<{answered: boolean}>`; store `pendingQuestions: Ref<PendingQuestion[]>`, `answeringQuestions: Ref<string[]>`, `answerQuestion(stepId, answers)`, `skipQuestion(stepId)`.

- [ ] **Step 1: Types and client**

In `apps/ember_web/src/api/types.ts` after `ApprovalDecision`:

```ts
/** One choice of a question the agent asks. */
export interface QuestionOption {
  label: string;
  description?: string;
}

/** One question the agent asks. The page always adds an "Other" typed answer. */
export interface Question {
  /** A very short label (a chip). */
  header: string;
  question: string;
  multi_select: boolean;
  options: QuestionOption[];
}

/** Questions that wait for the user's answer before the agent goes on. */
export interface PendingQuestion {
  /** The step's id: what an answer names. */
  id: string;
  questions: Question[];
}

/** The answer to one question: the labels chosen and/or the user's own words. */
export interface QuestionAnswer {
  selected: string[];
  other: string | null;
}
```

In `TurnEvent`: extend the snapshot variant with `questions?: PendingQuestion[];` and add two variants after `approval_resolved`:

```ts
  | { type: "question_request"; id: string; questions: Question[] }
  | { type: "question_resolved"; id: string; outcome: string }
```

In `apps/ember_web/src/api/ChatsClient.ts`: import `QuestionAnswer` from `./types` (extend the existing import), add to `TurnStart`:

```ts
  /** This page can show the agent's clickable questions and send answers back. */
  can_ask?: boolean;
```

and to `chatsClient` after `decide`:

```ts
  /** Answers (or skips) the questions the running answer waits on (a question_request's id). */
  answerQuestion: (id: string, stepId: string, payload: { answers: QuestionAnswer[]; skipped: boolean }) =>
    apiRequest<{ answered: boolean }>("POST", `${path(id)}/questions`, { step_id: stepId, ...payload }),
```

- [ ] **Step 2: Write the failing store tests**

Create `apps/ember_web/src/stores/chat.questions.test.ts`, with the same mock/setup header as `chat.suggestion.test.ts` / `chat.notify.test.ts` (copy their `vi.mock` blocks, including `AccountCapabilitiesClient` if present in the repo's current `chat.notify.test.ts`, the `ACCOUNT`, `summary`, `TWO`, `emit/endStream/fire`, `storeWith`, `running` helpers and the `beforeEach` that mocks `watchTurn`), adding `answerQuestion: vi.fn()` to the mocked `chatsClient`. Then:

```ts
import { ApiError } from "../api/http";

const QUESTIONS = [
  { header: "Format", question: "Which format?", multi_select: false, options: [{ label: "CSV" }, { label: "JSON" }] },
];
const ANSWERS = [{ selected: ["CSV"], other: null }];

const ask = (id = "q1") => fire({ type: "question_request", id, questions: QUESTIONS });

describe("the agent's questions", () => {
  it("appear when the agent asks and say so in the activity line", async () => {
    const chat = await running();

    ask();

    expect(chat.pendingQuestions).toEqual([{ id: "q1", questions: QUESTIONS }]);
    expect(chat.activity).toContain("waiting for your answer");
  });

  it("are not added twice for the same step", async () => {
    const chat = await running();

    ask();
    ask();

    expect(chat.pendingQuestions).toHaveLength(1);
  });

  it("come back from a snapshot (a reload in the middle of a question)", async () => {
    const chat = await running();

    fire({ type: "snapshot", text: "", activity: "", questions: [{ id: "q1", questions: QUESTIONS }] });

    expect(chat.pendingQuestions).toEqual([{ id: "q1", questions: QUESTIONS }]);
  });

  it("go when the agent reports them resolved, and when their step ends", async () => {
    const chat = await running();
    ask("q1");
    ask("q2");

    fire({ type: "question_resolved", id: "q1", outcome: "answered" });
    expect(chat.pendingQuestions.map((q) => q.id)).toEqual(["q2"]);
    fire({ type: "step_end", id: "q2", ok: true, result: "x" });

    expect(chat.pendingQuestions).toEqual([]);
  });

  it("are sent with the answers and stay (buttons off) until the agent confirms", async () => {
    const chat = await running();
    ask();
    client.answerQuestion.mockResolvedValue({ answered: true });

    await chat.answerQuestion("q1", ANSWERS);

    expect(client.answerQuestion).toHaveBeenCalledWith("c1", "q1", { answers: ANSWERS, skipped: false });
    expect(chat.answeringQuestions).toEqual(["q1"]);
    expect(chat.pendingQuestions).toHaveLength(1);
    fire({ type: "question_resolved", id: "q1", outcome: "answered" });
    expect(chat.pendingQuestions).toEqual([]);
    expect(chat.answeringQuestions).toEqual([]);
  });

  it("can be skipped", async () => {
    const chat = await running();
    ask();
    client.answerQuestion.mockResolvedValue({ answered: true });

    await chat.skipQuestion("q1");

    expect(client.answerQuestion).toHaveBeenCalledWith("c1", "q1", { answers: [], skipped: true });
  });

  it("are not sent twice while the first answer is on its way", async () => {
    const chat = await running();
    ask();
    client.answerQuestion.mockResolvedValue({ answered: true });

    await chat.answerQuestion("q1", ANSWERS);
    await chat.answerQuestion("q1", ANSWERS);

    expect(client.answerQuestion).toHaveBeenCalledOnce();
  });

  it("are dropped quietly when the server says nothing is waiting any more", async () => {
    const chat = await running();
    ask();
    client.answerQuestion.mockRejectedValue(new ApiError(409, "Nothing is waiting for that answer"));

    await chat.answerQuestion("q1", ANSWERS);

    expect(chat.pendingQuestions).toEqual([]);
    expect(chat.answeringQuestions).toEqual([]);
    expect(chat.sendError).toBe("");
  });

  it("give their buttons back and show the error for any other failure", async () => {
    const chat = await running();
    ask();
    client.answerQuestion.mockRejectedValue(new ApiError(502, "agent down"));

    await chat.answerQuestion("q1", ANSWERS);

    expect(chat.pendingQuestions).toHaveLength(1);
    expect(chat.answeringQuestions).toEqual([]);
    expect(chat.sendError).toBe("agent down");
  });

  it("are cleared when the answer ends or another chat is opened", async () => {
    const chat = await running({ c1: TWO, c2: TWO });
    ask();

    await chat.selectChat("c2");

    expect(chat.pendingQuestions).toEqual([]);
  });

  it("let every turn say it can show questions", async () => {
    await running();

    expect(client.startTurn.mock.calls[0]![1]).toMatchObject({ can_ask: true });
  });
});
```

(`ApiError` is exported by `../api/http`; confirm its constructor signature with `Grep` for `class ApiError` and adapt the two `new ApiError(...)` calls to it. `running()` accepts a chats map as in `chat.suggestion.test.ts`; if the copy of `running` in your header takes no argument, give it the same optional parameter.)

- [ ] **Step 3: Run to verify they fail**

Run (from `apps/ember_web/`): `npx vitest run src/stores/chat.questions.test.ts`
Expected: FAIL (`chat.pendingQuestions` undefined).

- [ ] **Step 4: Store implementation**

In `apps/ember_web/src/stores/chat.ts`:

Imports: add `PendingQuestion`, `QuestionAnswer` to the type import from `../api/types`.

State, after `deciding`:

```ts
  // Questions the agent asked that wait for the user's answer, and the ones
  // whose answer was sent but not yet confirmed by the agent.
  const pendingQuestions = ref<PendingQuestion[]>([]);
  const answeringQuestions = ref<string[]>([]);
```

Snapshot case: after `pendingApprovals.value = event.approvals ?? [];` add `pendingQuestions.value = event.questions ?? [];`.

Event cases: after `approval_resolved`:

```ts
      case "question_request":
        activity.value = "waiting for your answer ...";
        if (!pendingQuestions.value.some((q) => q.id === event.id)) {
          pendingQuestions.value.push({ id: event.id, questions: event.questions });
        }
        break;
      case "question_resolved":
        activity.value = "";
        dropQuestion(event.id);
        break;
```

In the `step_end` case, after `dropApproval(event.id);` add `dropQuestion(event.id);`.

Next to `dropApproval`:

```ts
  function dropQuestion(id: string): void {
    pendingQuestions.value = pendingQuestions.value.filter((q) => q.id !== id);
    answeringQuestions.value = answeringQuestions.value.filter((a) => a !== id);
  }
```

In `unfollow()` after `deciding.value = [];` add:

```ts
    pendingQuestions.value = [];
    answeringQuestions.value = [];
```

In `send()`'s `chatsClient.startTurn(id, {...})` payload add `can_ask: true,` after `caveman: caveman.value,`.

Actions, after `decideApproval`:

```ts
  /** Answers (or skips) the questions the running answer waits on. The card
   * stays (its buttons off) until the agent confirms with a question_resolved event. */
  async function sendQuestionAnswer(stepId: string, answers: QuestionAnswer[], skipped: boolean): Promise<void> {
    const conversation = active.value;
    const waiting = pendingQuestions.value.find((q) => q.id === stepId);
    if (!conversation || !waiting || answeringQuestions.value.includes(stepId)) return;
    const started = generation;
    answeringQuestions.value = [...answeringQuestions.value, stepId];
    sendError.value = "";
    try {
      await chatsClient.answerQuestion(conversation.id, stepId, { answers, skipped });
    } catch (err) {
      if (started !== generation) return;
      if (err instanceof ApiError && (err.status === 404 || err.status === 409)) {
        // Already answered (maybe in another tab), or the answer ended: nothing is waiting.
        dropQuestion(stepId);
      } else {
        answeringQuestions.value = answeringQuestions.value.filter((a) => a !== stepId);
        sendError.value = errorMessage(err);
      }
    }
  }

  function answerQuestion(stepId: string, answers: QuestionAnswer[]): Promise<void> {
    return sendQuestionAnswer(stepId, answers, false);
  }

  function skipQuestion(stepId: string): Promise<void> {
    return sendQuestionAnswer(stepId, [], true);
  }
```

Return object: add `pendingQuestions, answeringQuestions, answerQuestion, skipQuestion,` after `decideApproval`.

- [ ] **Step 5: Run to verify they pass**

Run: `npx vitest run src/stores/chat.questions.test.ts`
Expected: PASS.

- [ ] **Step 6: Fix existing tests that pin the turn payload**

Run: `npx vitest run src/stores`
If a test fails on `startTurn` called with an exact object (`toHaveBeenCalledWith(... { question, caveman, ... })`), add `can_ask: true` to the expected object there (find them with `Grep` for `startTurn).toHaveBeenCalledWith|startTurn.mock.calls`). Expected afterwards: PASS.

- [ ] **Step 7: Commit (ask the user first)**

```bash
git add apps/ember_web/src/api/types.ts apps/ember_web/src/api/ChatsClient.ts apps/ember_web/src/stores/chat.ts apps/ember_web/src/stores/chat.questions.test.ts
git add -u apps/ember_web/src/stores
git commit -m "feat(ember_web): track the agent's clickable questions in the chat store"
```

---

### Task 6: QuestionCard, saved-step rendering, wiring (ember_web)

**Files:**
- Create: `apps/ember_web/src/components/QuestionCard.vue`, `apps/ember_web/src/components/QuestionCard.test.ts`
- Create: `apps/ember_web/src/utils/askUserStep.ts`, `apps/ember_web/src/utils/askUserStep.test.ts`
- Modify: `apps/ember_web/src/components/MessageList.vue` (props ~21-49, emits ~50-57, template after the approvals loop ~410)
- Modify: `apps/ember_web/src/components/ToolSteps.vue` (script ~77; template ~91-103)
- Modify: `apps/ember_web/src/views/ChatView.vue` (`storeToRefs` block ~33-65, `<MessageList>` ~366-389)
- Modify: `apps/ember_web/e2e/fakeApi.ts`, `apps/ember_web/README.md`
- Test: `apps/ember_web/src/components/MessageList.test.ts` (append)

**Interfaces:**
- Consumes (Task 5): types and store members above.
- Produces: `QuestionCard` props `{ pending: PendingQuestion; answering: boolean }`, emits `answer: [stepId: string, answers: QuestionAnswer[]]` and `skip: [stepId: string]`; `askUserStep.describeAskUser(step: ToolStep): string[] | null`; `MessageList` props `questions?: PendingQuestion[]`, `answeringQuestions?: string[]`, emits `answer-question`, `skip-question`.

- [ ] **Step 1: Write the failing saved-step helper test**

Create `apps/ember_web/src/utils/askUserStep.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import type { ToolStep } from "../api/types";
import { describeAskUser } from "./askUserStep";

const step = (overrides: Partial<ToolStep> = {}): ToolStep => ({
  tool: "ask_user",
  label: "",
  ok: true,
  arguments: {
    questions: [
      { header: "Format", question: "Which format?", multi_select: false, options: [{ label: "CSV" }, { label: "JSON" }] },
      { header: "Extras", question: "Which extras?", multi_select: true, options: [{ label: "Totals" }, { label: "Chart" }] },
    ],
  },
  result: "The user answered:\n- Which format?: CSV\n- Which extras?: Totals, Chart; other: a title",
  ...overrides,
});

describe("describeAskUser", () => {
  it("is null for any other tool", () => {
    expect(describeAskUser(step({ tool: "tool_srv_stopApp" }))).toBeNull();
  });

  it("pairs each question with what was answered", () => {
    expect(describeAskUser(step())).toEqual([
      "Format: CSV",
      "Extras: Totals, Chart; other: a title",
    ]);
  });

  it("says when the user skipped or did not answer", () => {
    expect(describeAskUser(step({ result: "The user skipped these questions. Continue with your best judgement and say what you assumed." }))).toEqual([
      "Format: skipped",
      "Extras: skipped",
    ]);
    expect(describeAskUser(step({ result: "The user did not answer in time. Continue." }))).toEqual([
      "Format: no answer",
      "Extras: no answer",
    ]);
  });

  it("falls back to the headers alone when the answers cannot be read", () => {
    expect(describeAskUser(step({ result: "garbled", ok: false }))).toEqual(["Format", "Extras"]);
  });

  it("is null when the arguments are not questions", () => {
    expect(describeAskUser(step({ arguments: { nope: 1 } }))).toBeNull();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npx vitest run src/utils/askUserStep.test.ts`
Expected: FAIL (module not found).

- [ ] **Step 3: Write `askUserStep.ts`**

Create `apps/ember_web/src/utils/askUserStep.ts`:

```ts
import type { ToolStep } from "../api/types";

const PREFIX = "- ";

/** What a saved `ask_user` step shows instead of its raw JSON: one line per
 * question, "<header>: <what the user chose>". Null for any other step. The
 * answer lines are the text ai_agent gave the model ("- <question>: <answer>"),
 * read back by position. A question ends with "?", so the answer is what follows
 * the last "?: " of the line; a typed answer that itself contains "?: " is
 * shown cut (display only). */
export function describeAskUser(step: ToolStep): string[] | null {
  if (step.tool !== "ask_user") return null;
  const asked = step.arguments.questions;
  if (!Array.isArray(asked) || asked.length === 0) return null;
  const headers = asked.map((q) => {
    const header = q && typeof q === "object" ? (q as { header?: unknown }).header : undefined;
    return typeof header === "string" ? header : "Question";
  });
  const lines = step.result.split("
").filter((line) => line.startsWith(PREFIX));
  if (step.result.startsWith("The user answered:") && lines.length === headers.length) {
    return headers.map((header, i) => {
      const body = lines[i]!.slice(PREFIX.length);
      const at = body.lastIndexOf("?: ");
      const answer = at >= 0 ? body.slice(at + 3) : body.slice(body.indexOf(": ") + 2);
      return `${header}: ${answer}`;
    });
  }
  if (step.result.startsWith("The user skipped")) return headers.map((header) => `${header}: skipped`);
  if (step.result.startsWith("The user did not answer")) return headers.map((header) => `${header}: no answer`);
  return headers;
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `npx vitest run src/utils/askUserStep.test.ts`
Expected: PASS.

- [ ] **Step 5: Write the failing QuestionCard tests**

Create `apps/ember_web/src/components/QuestionCard.test.ts`:

```ts
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import type { PendingQuestion } from "../api/types";
import QuestionCard from "./QuestionCard.vue";

const PENDING: PendingQuestion = {
  id: "q1",
  questions: [
    {
      header: "Format",
      question: "Which format?",
      multi_select: false,
      options: [{ label: "CSV", description: "Plain text" }, { label: "JSON" }],
    },
    { header: "Extras", question: "Which extras?", multi_select: true, options: [{ label: "Totals" }, { label: "Chart" }] },
  ],
};

function mountCard(props: Record<string, unknown> = {}) {
  return mount(QuestionCard, { props: { pending: PENDING, answering: false, ...props } });
}

const option = (w: ReturnType<typeof mountCard>, q: number, label: string) =>
  w.findAll(".q")[q]!.findAll("button.opt").find((b) => b.text().startsWith(label))!;
const submit = (w: ReturnType<typeof mountCard>) => w.get("button.submit");
const skip = (w: ReturnType<typeof mountCard>) => w.get("button.skip");

describe("QuestionCard", () => {
  it("shows every question with its header, options and an Other choice", () => {
    const w = mountCard();

    expect(w.findAll(".q")).toHaveLength(2);
    expect(w.findAll(".q")[0]!.text()).toContain("Format");
    expect(w.findAll(".q")[0]!.text()).toContain("Which format?");
    expect(w.findAll(".q")[0]!.text()).toContain("Plain text");
    expect(w.findAll(".q")[0]!.findAll("button.opt").map((b) => b.text().split("\n")[0])).toEqual(
      expect.arrayContaining(["CSV", "JSON", "Other"]),
    );
  });

  it("starts with Submit off and Skip on", () => {
    const w = mountCard();

    expect((submit(w).element as HTMLButtonElement).disabled).toBe(true);
    expect((skip(w).element as HTMLButtonElement).disabled).toBe(false);
  });

  it("a single-select question keeps one choice at a time", async () => {
    const w = mountCard();

    await option(w, 0, "CSV").trigger("click");
    await option(w, 0, "JSON").trigger("click");

    expect(option(w, 0, "CSV").attributes("aria-pressed")).toBe("false");
    expect(option(w, 0, "JSON").attributes("aria-pressed")).toBe("true");
  });

  it("a multi-select question toggles choices on and off", async () => {
    const w = mountCard();

    await option(w, 1, "Totals").trigger("click");
    await option(w, 1, "Chart").trigger("click");
    await option(w, 1, "Totals").trigger("click");

    expect(option(w, 1, "Totals").attributes("aria-pressed")).toBe("false");
    expect(option(w, 1, "Chart").attributes("aria-pressed")).toBe("true");
  });

  it("Submit needs every question answered and then sends the answers in order", async () => {
    const w = mountCard();
    await option(w, 0, "CSV").trigger("click");
    expect((submit(w).element as HTMLButtonElement).disabled).toBe(true);
    await option(w, 1, "Totals").trigger("click");
    await option(w, 1, "Chart").trigger("click");
    expect((submit(w).element as HTMLButtonElement).disabled).toBe(false);

    await submit(w).trigger("click");

    expect(w.emitted("answer")).toEqual([
      ["q1", [{ selected: ["CSV"], other: null }, { selected: ["Totals", "Chart"], other: null }]],
    ]);
  });

  it("Other reveals a text box; typed text alone counts as an answer", async () => {
    const w = mountCard();
    expect(w.findAll("input[type=text]")).toHaveLength(0);

    await option(w, 0, "Other").trigger("click");
    await w.get(".q input[type=text]").setValue("  XML  ");
    await option(w, 1, "Chart").trigger("click");
    await submit(w).trigger("click");

    expect(w.emitted("answer")![0]).toEqual([
      "q1",
      [{ selected: [], other: "XML" }, { selected: ["Chart"], other: null }],
    ]);
  });

  it("Other with nothing typed is not an answer", async () => {
    const w = mountCard();
    await option(w, 0, "Other").trigger("click");
    await option(w, 1, "Chart").trigger("click");

    expect((submit(w).element as HTMLButtonElement).disabled).toBe(true);
  });

  it("choosing Other on a single-select question drops the listed choice", async () => {
    const w = mountCard();
    await option(w, 0, "CSV").trigger("click");

    await option(w, 0, "Other").trigger("click");

    expect(option(w, 0, "CSV").attributes("aria-pressed")).toBe("false");
    expect(option(w, 0, "Other").attributes("aria-pressed")).toBe("true");
  });

  it("Skip sends a skip, even with nothing chosen", async () => {
    const w = mountCard();

    await skip(w).trigger("click");

    expect(w.emitted("skip")).toEqual([["q1"]]);
  });

  it("turns every button off while the answer is on its way", () => {
    const w = mountCard({ answering: true });

    expect(w.findAll("button").every((b) => (b.element as HTMLButtonElement).disabled)).toBe(true);
  });

  it("shows the text of a question as text, never as markup", () => {
    const w = mountCard({
      pending: {
        id: "q1",
        questions: [{ header: "x", question: "<img src=x onerror=alert(1)>", multi_select: false, options: [{ label: "<b>A</b>" }, { label: "B" }] }],
      },
    });

    expect(w.find("img").exists()).toBe(false);
    expect(w.find("b").exists()).toBe(false);
    expect(w.text()).toContain("<img src=x onerror=alert(1)>");
  });
});
```

Run: `npx vitest run src/components/QuestionCard.test.ts`
Expected: FAIL (component missing).

- [ ] **Step 6: Write `QuestionCard.vue`**

Create `apps/ember_web/src/components/QuestionCard.vue`:

```vue
<script setup lang="ts">
import { computed, reactive } from "vue";
import type { PendingQuestion, QuestionAnswer } from "../api/types";

/** The clickable questions the agent asks mid-answer. One card per question
 * set: every question has its options as pills and an "Other" typed answer;
 * Submit needs every question answered, Skip declines all of them. The agent
 * confirms with a question_resolved event, which removes the card. */

const props = defineProps<{ pending: PendingQuestion; answering: boolean }>();
const emit = defineEmits<{
  answer: [stepId: string, answers: QuestionAnswer[]];
  skip: [stepId: string];
}>();

interface Choice {
  selected: string[];
  otherOn: boolean;
  otherText: string;
}

const choices = reactive<Choice[]>(props.pending.questions.map(() => ({ selected: [], otherOn: false, otherText: "" })));

function toggle(index: number, label: string): void {
  const choice = choices[index]!;
  const question = props.pending.questions[index]!;
  if (choice.selected.includes(label)) {
    choice.selected = choice.selected.filter((l) => l !== label);
  } else if (question.multi_select) {
    choice.selected = [...choice.selected, label];
  } else {
    choice.selected = [label];
    choice.otherOn = false;
  }
}

function toggleOther(index: number): void {
  const choice = choices[index]!;
  choice.otherOn = !choice.otherOn;
  if (choice.otherOn && !props.pending.questions[index]!.multi_select) choice.selected = [];
}

const complete = computed(() =>
  choices.every((c) => c.selected.length > 0 || (c.otherOn && c.otherText.trim() !== "")),
);

function submit(): void {
  if (!complete.value || props.answering) return;
  emit(
    "answer",
    props.pending.id,
    choices.map((c) => ({
      selected: [...c.selected],
      other: c.otherOn && c.otherText.trim() !== "" ? c.otherText.trim() : null,
    })),
  );
}
</script>

<template>
  <form class="question-card" :aria-label="'The agent has a question'" @submit.prevent="submit">
    <section v-for="(q, i) in pending.questions" :key="i" class="q">
      <header>
        <span class="chip">{{ q.header }}</span>
        <span v-if="q.multi_select" class="hint">choose any</span>
      </header>
      <p class="text">{{ q.question }}</p>
      <div class="options" role="group" :aria-label="q.question">
        <button
          v-for="o in q.options"
          :key="o.label"
          type="button"
          class="opt"
          :aria-pressed="choices[i]!.selected.includes(o.label)"
          :disabled="answering"
          @click="toggle(i, o.label)"
        >
          <span class="label">{{ o.label }}</span>
          <span v-if="o.description" class="desc">{{ o.description }}</span>
        </button>
        <button
          type="button"
          class="opt"
          :aria-pressed="choices[i]!.otherOn"
          :disabled="answering"
          @click="toggleOther(i)"
        >
          <span class="label">Other</span>
        </button>
      </div>
      <input
        v-if="choices[i]!.otherOn"
        v-model="choices[i]!.otherText"
        type="text"
        class="other"
        maxlength="500"
        placeholder="Type your own answer"
        :aria-label="`Your own answer to: ${q.question}`"
        :disabled="answering"
      />
    </section>
    <div class="buttons">
      <button type="submit" class="submit" :disabled="!complete || answering">Submit</button>
      <button type="button" class="skip" :disabled="answering" @click="emit('skip', pending.id)">Skip</button>
    </div>
    <p class="note">The agent waits for you. Skip lets it go on with its best guess.</p>
  </form>
</template>

<style scoped>
.question-card {
  display: grid;
  gap: 14px;
  padding: 10px 12px;
  border: 1px solid var(--accent);
  border-radius: var(--radius-lg);
  background: color-mix(in srgb, var(--accent) 6%, var(--surface));
}
.q {
  display: grid;
  gap: 6px;
}
header {
  display: flex;
  align-items: center;
  gap: 8px;
}
.chip {
  padding: 1px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  font-size: 0.75em;
  color: var(--muted);
}
.hint {
  font-size: 0.75em;
  color: var(--muted);
}
.text {
  margin: 0;
  font-size: 0.95em;
  overflow-wrap: anywhere;
}
.options {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.opt {
  display: grid;
  gap: 2px;
  max-width: 100%;
  padding: 6px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  text-align: left;
  cursor: pointer;
  font-size: 0.85em;
  color: var(--text);
  background: transparent;
}
.opt:hover:not(:disabled) {
  border-color: var(--accent);
}
.opt[aria-pressed="true"] {
  border-color: var(--accent);
  color: var(--accent-contrast);
  background: var(--accent);
}
.opt .desc {
  font-size: 0.85em;
  opacity: 0.8;
  overflow-wrap: anywhere;
}
.other {
  padding: 6px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  font: inherit;
  font-size: 0.9em;
  color: var(--text);
  background: var(--bg);
}
.other:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}
.buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.buttons button {
  padding: 5px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  cursor: pointer;
  font-size: 0.85em;
  color: var(--text);
  background: transparent;
}
.buttons .submit {
  border-color: var(--accent);
  color: var(--accent-contrast);
  background: var(--accent);
}
.buttons button:disabled,
.opt:disabled {
  cursor: default;
  opacity: 0.45;
}
.note {
  margin: 0;
  font-size: 0.75em;
  color: var(--muted);
}
</style>
```

- [ ] **Step 7: Run to verify QuestionCard passes**

Run: `npx vitest run src/components/QuestionCard.test.ts`
Expected: PASS. Adjust only selectors if the real DOM differs (the `.q`, `button.opt`, `button.submit`, `button.skip` class names are the contract between this component and its test). The "Other" label text in the "shows every question" test relies on `.opt` text beginning with the label; the description sits on a second line.

- [ ] **Step 8: MessageList wiring - failing test**

Append to `apps/ember_web/src/components/MessageList.test.ts` (it already defines `mountList`; reuse it):

```ts
describe("question cards", () => {
  const PENDING = {
    id: "q1",
    questions: [
      { header: "Format", question: "Which format?", multi_select: false, options: [{ label: "CSV" }, { label: "JSON" }] },
    ],
  };

  it("shows none without a question", () => {
    expect(mountList({ busy: true, questions: [] }).findAll(".question-card")).toHaveLength(0);
  });

  it("shows one card per waiting question set while an answer is running", () => {
    const wrapper = mountList({ busy: true, questions: [PENDING, { ...PENDING, id: "q2" }] });

    expect(wrapper.findAll(".question-card")).toHaveLength(2);
  });

  it("passes the answer and the skip up", async () => {
    const wrapper = mountList({ busy: true, questions: [PENDING] });

    await wrapper.find("button.opt").trigger("click");
    await wrapper.find("button.submit").trigger("click");
    await wrapper.find("button.skip").trigger("click");

    expect(wrapper.emitted("answer-question")).toEqual([["q1", [{ selected: ["CSV"], other: null }]]]);
    expect(wrapper.emitted("skip-question")).toEqual([["q1"]]);
  });

  it("turns the card's buttons off while its answer is on its way", () => {
    const wrapper = mountList({ busy: true, questions: [PENDING], answeringQuestions: ["q1"] });

    expect((wrapper.find("button.submit").element as HTMLButtonElement).disabled).toBe(true);
  });
});
```

Run: `npx vitest run src/components/MessageList.test.ts`
Expected: the new tests FAIL.

- [ ] **Step 9: MessageList implementation**

In `apps/ember_web/src/components/MessageList.vue`:

Imports: add `PendingQuestion`, `QuestionAnswer` to the type import from `../api/types`; `import QuestionCard from "./QuestionCard.vue";` with the other component imports.

Props, after `deciding?: string[];`:

```ts
  /** Questions the agent asked that wait for the user's answer, and the ones
   * already answered but not yet confirmed (their buttons are off). */
  questions?: PendingQuestion[];
  answeringQuestions?: string[];
```

Emits, after `decide`:

```ts
  "answer-question": [stepId: string, answers: QuestionAnswer[]];
  "skip-question": [stepId: string];
```

Template, right after the closing `</section>` of the approvals loop (before `<AgentActivity />`):

```vue
        <!-- The agent asked the user something and waits for the answer (no
             time limit: they may be deciding). Nothing continues until they
             answer or skip. -->
        <QuestionCard
          v-for="q in questions ?? []"
          :key="q.id"
          :pending="q"
          :answering="answeringQuestions?.includes(q.id) ?? false"
          @answer="(id, answers) => emit('answer-question', id, answers)"
          @skip="(id) => emit('skip-question', id)"
        />
```

- [ ] **Step 10: ChatView wiring**

In `apps/ember_web/src/views/ChatView.vue`: add `pendingQuestions,` and `answeringQuestions,` to the `storeToRefs(chat)` destructure (next to `pendingApprovals`), and on `<MessageList>` after `:deciding="deciding"`:

```vue
        :questions="pendingQuestions"
        :answering-questions="answeringQuestions"
        @answer-question="chat.answerQuestion"
        @skip-question="chat.skipQuestion"
```

- [ ] **Step 11: Saved `ask_user` steps read as questions and answers**

In `apps/ember_web/src/components/ToolSteps.vue`: add `import { describeAskUser } from "../utils/askUserStep";` and, in the script:

```ts
function askedLines(step: ToolStep): string[] | null {
  return describeAskUser(step);
}
```

In the template, replace the lines that print the tool code, the arguments and the result inside `<div class="detail">` so an `ask_user` step shows its questions and answers:

```vue
      <div class="detail">
        <template v-if="askedLines(step)">
          <p class="tool"><code>ask_user</code></p>
          <ul class="asked">
            <li v-for="(line, n) in askedLines(step)" :key="n">{{ line }}</li>
          </ul>
        </template>
        <template v-else>
          <p class="tool"><code>{{ step.tool }}</code></p>
          <pre v-if="argumentsText(step)">{{ argumentsText(step) }}</pre>
          <details v-if="workingText(step)" class="agent-text" open>
            <summary>{{ workingLabel(step) }} is working</summary>
            <pre>{{ workingText(step) }}</pre>
          </details>
          <template v-if="step.result">
            <MarkdownContent v-if="formatToolResult(step.result)" :text="formatToolResult(step.result) ?? ''" />
            <pre v-else>{{ step.result }}</pre>
          </template>
          <p v-else-if="step.ok === null" class="muted">{{ live ? "running ..." : "no result (the answer was stopped)" }}</p>
        </template>
      </div>
```

and a small style in the `<style scoped>` block:

```css
.asked {
  margin: 4px 0 0;
  padding-left: 18px;
  overflow-wrap: anywhere;
}
```

Also give the step title a readable default: in `toolTitle`'s source (`src/utils/toolTitles.ts`) check whether unknown tool names are prettified; if `ask_user` shows as "Ask user", leave it. Otherwise add the mapping the file's pattern uses so the step reads "Asked you a question".

- [ ] **Step 12: e2e fake API**

In `apps/ember_web/e2e/fakeApi.ts`, next to the other `/api/chats/...` routes (before the `/api/chats` list route), add:

```ts
    // The agent's clickable questions: the fake never asks one (its stream is a finished body), so any answer is refused.
    if (method === "POST" && /^\/api\/chats\/[^/]+\/questions$/.test(path)) {
      return json(route, { detail: "Nothing is waiting for that answer" }, 409);
    }
```

- [ ] **Step 13: Run everything**

From `apps/ember_web/`:
- `npx vitest run src/components/MessageList.test.ts src/components/QuestionCard.test.ts src/utils/askUserStep.test.ts src/stores` - Expected: PASS.
- `npm test` - Expected: all PASS.
- `npx vue-tsc -b --noEmit` - Expected: prints nothing.
- `npx vite build` - Expected: succeeds; delete `dist/` afterwards (`Remove-Item -Recurse -Force dist`).
- `npm run test:e2e` - Expected: PASS (install Playwright browsers only if missing and say so in the report).

- [ ] **Step 14: README**

In `apps/ember_web/README.md`, in the chat features list, add: "Clickable questions: the agent can stop mid-answer and ask 1-4 questions with options (single or multi choice) plus your own typed answer; answer or Skip and it goes on. There is no time limit while you decide. Stop cancels the answer." Match the list style around it.

- [ ] **Step 15: Hand over for manual testing, then commit (ask the user first)**

The user tests ember_web by hand (do not launch browser verification agents). Tell them how to check. Ask for a clarification the agent should raise, for example: "Plan a trip for me" in a chat whose entry agent is an orchestrator using a model that follows tool instructions, then:
1. A card with the agent's questions appears inside the live answer; options are pills; Other reveals a text box.
2. Submit stays off until every question is answered; Skip is always on.
3. After Submit the card disappears and the answer continues using your choices; the saved "Ran N tools" step reads "<header>: <answer>".
4. Leave a question open for a few minutes: the agent keeps waiting. Reload the page: the card comes back. Press Stop: the answer is cancelled.
5. `chat_cli` still works and is never asked a question.

```bash
git add apps/ember_web/src/components/QuestionCard.vue apps/ember_web/src/components/QuestionCard.test.ts apps/ember_web/src/utils/askUserStep.ts apps/ember_web/src/utils/askUserStep.test.ts apps/ember_web/src/components/MessageList.vue apps/ember_web/src/components/MessageList.test.ts apps/ember_web/src/components/ToolSteps.vue apps/ember_web/src/views/ChatView.vue apps/ember_web/e2e/fakeApi.ts apps/ember_web/README.md
git commit -m "feat(ember_web): clickable question cards for the agent's questions"
```

---

## Self-Review

**Spec coverage:**
- Shape (1-4 questions, multi-select, headers, descriptions, Other): Task 1 schema + Task 6 card.
- No short timeout, Skip, 60-minute cap, keepalive: Task 1 broker (`MAX_WAIT_SECONDS`, `KEEPALIVE_SECONDS`), Task 6 Skip button.
- Only the top-level agent, only when the caller can ask: `agent_config.run_chat` binds `ask_user and depth == 0` (Task 2); `can_ask` end to end (Tasks 3, 4, 5).
- Handled in the async provider loop, not `_dispatch`; exempt from approvals; kept by the shortlist: Task 2.
- ai_agent `ask(ask_user)`, `answer_question`, `status.user_questions`: Task 2.
- ember_api gateway, events, clamp, snapshot, answer route, validation, saved steps (no new storage), chat_cli unchanged: Tasks 3-4.
- ember_web types, client, store, card in the live answer, saved-step rendering, fake API, READMEs: Tasks 5-6. The ai_agent README is not updated here: add a line about `ask_user`/`answer_question` to `apps/ai_agent/README.md` if it documents `decide`/`approval_mode` (Task 2 Step 9, look for it with `Grep`).

**Placeholder scan:** no TBD/TODO. Steps that depend on facts not visible while planning say exactly what to look up and how (the `TurnRegistry` attribute name in Task 3 Step 8, `ApiError`'s constructor in Task 5 Step 2, the cancellation helpers in Task 1 Step 8, the toolTitles mapping in Task 6 Step 11).

**Type consistency:** `questions.ask/handle/BROKER/Answer/QuestionPolicy`, `ask_user.validate/TOOL_NAME` (Tasks 1-2); `answer_question(url, caller, request_id, step_id, answers, skipped)` (Tasks 3-4); `pending_question`/`answer` on the registry (Tasks 3-4); `PendingQuestion`, `QuestionAnswer`, `answerQuestion`/`skipQuestion`/`pendingQuestions`/`answeringQuestions` (Tasks 5-6); MessageList's `questions`/`answeringQuestions` props and `answer-question`/`skip-question` events (Task 6, wired in ChatView).

**Known soft spots to watch while executing:** (1) `askUserStep.describeAskUser` reads the model-facing answer text back by position, so a user's own typed answer containing `?: ` can confuse it; acceptable for a display-only summary. (2) The held-question flow has no end-to-end test (the e2e fake cannot hold a stream); the manual check list in Task 6 Step 15 covers it.
