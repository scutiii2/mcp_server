# Clickable questions from the agent

Date: 2026-10-08. Status: draft, awaiting review.

## Goal

While answering, the agent can stop and ask the user one to four questions with
clickable options, as Claude Code does. The user clicks (or types an "Other"
answer), submits, and the agent continues with the answers. The user may also
skip.

The prompt suggestion feature (merged separately) is unrelated to this one.

## Decisions

- **Shape**: one `ask_user` call carries 1 to 4 questions. Each has a short
  header, the question, 2 to 4 options (label plus optional description), and a
  `multi_select` flag. The UI always adds an "Other" free-text answer to every
  question; the agent never lists it.
- **No answer**: the card has a **Skip** button. There is no short timeout: the
  agent waits while the user is deciding. Stop cancels the whole turn, as for
  tool approvals.
- **Safety cap**: a question left open for **60 minutes** is treated as skipped
  (so an abandoned browser cannot hold a turn forever). Proposed value, to be
  confirmed.
- **Who may ask**: only the top-level agent of a turn (the entry agent). A
  delegated agent never gets the tool, because it has no channel to the user
  (same rule as tool approvals).
- **Who can answer**: only clients that say so. Each turn request carries
  `can_ask: bool` (default false). ember_web sends true. `chat_cli` sends
  nothing, so it never sees a tool it cannot answer, and its turns cannot hang.
- The mechanism copies tool approvals: an event out, a broker keyed by
  `(request_id, step_id)`, an MCP tool in, a REST route in front.

## ai_agent

### Tool definition: `src/agents/ask_user.py`

Same role as `delegation.py` for its schema only.

- `TOOL_NAME = "ask_user"`.
- Input schema:

  ```json
  {
    "questions": [
      {
        "header": "string, at most 12 characters (a short chip label)",
        "question": "string",
        "multi_select": "boolean, default false",
        "options": [{"label": "string", "description": "string, optional"}]
      }
    ]
  }
  ```

  `questions`: 1 to 4 items. `options`: 2 to 4 items per question. Labels are
  unique within a question.
- Description tells the model to use it sparingly: only when the request is
  ambiguous or a choice is the user's to make, never to confirm routine
  steps, and to put its recommended option first.
- `validate(arguments)` returns the cleaned questions or an error string. A
  bad call gives the model the error text as the tool result (no event, no
  wait).

### Broker and waiting: `src/core/questions.py`

Mirrors `core/approvals.py`.

- `QuestionPolicy(enabled: bool)` in a ContextVar (`bind`, `reset`,
  `current`). Set per `ask()` call from the new `ask_user` argument; a
  delegated call gets `enabled=False`.
- `QuestionBroker` (`BROKER`): `wait(request_id, step_id) -> Answer`,
  `answer(request_id, step_id, answers, skipped) -> bool`. Same rules as
  `ApprovalBroker`: answered once, a second wait replaces the first, the wait
  polls `cancellation.is_cancelled` every 0.5 s.
- `async ask(request_id, step_id, questions, on_event) -> str`:
  1. With no `on_event` or `request_id`, returns `NO_CHANNEL`.
  2. Emits `question_request` with `{id, questions}`.
  3. Waits. While waiting it emits `{"type": "keepalive"}` every 20 s so no
     proxy or read timeout sees an idle stream. ember_api ignores event types
     it does not forward.
  4. Emits `question_resolved` with `{id, outcome}` (`answered`, `skipped`,
     `timeout`, `cancelled`).
  5. Returns the text given to the model as the tool result. `cancelled`
     raises `ChatCancelled` after a `step_end` ("Stopped before it ran."), as
     approvals do.
- Text returned to the model:
  - answered: `The user answered:` then one line per question,
    `<header>: <chosen labels joined by ", ">` and, when given,
    `; other: <typed text>`.
  - skipped: `The user skipped these questions. Continue with your best judgement and say what you assumed.`
  - timeout: `The user did not answer in time. Continue with your best judgement and say what you assumed.`

### Provider loops

`anthropic_provider.py` and `openai_provider.py`: handle `ask_user` in the
async part of the tool loop, in the place where `approvals.review` is called
(`_dispatch` runs tools synchronously on a worker thread and cannot wait on the
event loop).

- Offer the schema only when `questions.current().enabled`.
- `ask_user` skips `approvals.review` (asking is not a risky tool) and is
  always kept by `tool_selection.shortlist_schemas` (add its name to the
  always-keep set next to `delegation.TOOL_NAME`).
- `step_start` and `step_end` are emitted as for any tool, so the call is part
  of the saved steps.

### Entry points: `src/server.py`

- `ask(..., ask_user: bool = False)` binds the policy. Delegated calls do not
  pass it.
- New MCP tool `answer_question(request_id, step_id, answers, skipped=False)`
  returning `{"answered": bool}`; `answers` is a list aligned with the
  questions, each `{"selected": [str], "other": str | null}`.
- `status` adds `"user_questions": true`, so a caller can tell an agent that
  understands `ask_user` from an older one.

### Tests

Broker (answer, skip, timeout cap with a short injected timeout, cancel, double
answer, replacement), `ask()` text for each outcome, schema validation (counts,
duplicate labels, header length), provider loop for both providers (tool
offered only when enabled, never to a delegated agent, result fed back,
`ChatCancelled` on Stop), `answer_question` tool, keepalive emitted while
waiting.

## ember_api

### Gateway

`AgentGateway.ask(..., ask_user: bool = False)` passes it through, and
`AgentGateway.answer(url, caller, request_id, step_id, answers, skipped) -> bool`
calls `answer_question`. `FakeAgent` in `tests/conftest.py` gets both, with a
way for tests to raise a question and wait for the answer, like its approval
support.

### Turns: `src/services/turns.py`

- `TurnOptions.can_ask: bool = False`; passed to `gateway.ask` as `ask_user`.
- `on_event` forwards `question_request` and `question_resolved` (clamped:
  header 12, question 300, label 80, description 200 characters, at most 4
  questions and 4 options each).
- `Turn.pending_questions: dict[str, dict]` set by `question_request`, cleared
  by `question_resolved` and when the turn ends. `Turn.snapshot()` adds
  `"questions": [...]`, so a late joiner or a reload still sees the question.
- `TurnRegistry.pending_question(account_id, chat_id, step_id)` and
  `TurnRegistry.answer(account_id, chat_id, step_id, answers, skipped) -> bool`
  (False when not waiting), like `decide`.

### Route: `routes/chats.py`

- `TurnRequest.can_ask: bool = False`.
- `POST /api/chats/{chat_id}/questions`, gate `chat.use`, JSON only:
  `{step_id: str, skipped: bool = false, answers: [{selected: [str], other: str | null}] = []}`.
  Validation against the pending question: when not skipped, one answer per
  question; each selected label must be one of that question's options; at most
  one selection unless `multi_select`; `other` at most 500 characters; every
  question needs a selection or non-empty `other`. Errors are 422 with a clear
  message. Returns `{answered: bool}`.
- The answer text lives only in the saved steps (below), not in the audit log.

### Saved chats

The `ask_user` call is a normal step (`tool: "ask_user"`, `arguments` = the
questions, `result` = the text returned to the model), so history shows what
was asked and answered with no new storage.

### chat_cli

No change. It does not send `can_ask`. A route test asserts that a turn
without `can_ask` never offers the tool (via `FakeAgent.asks[...]["ask_user"]`
being false).

### Tests

Route: 401, 403, unknown chat 404, `answered: false` when nothing is waiting,
every validation rule, skip, happy path, a second answer to the same question,
`can_ask` passed through. Turns: events forwarded and clamped, snapshot
includes pending questions, cleared on resolve and on turn end, answered by
another tab.

## ember_web

- `api/types.ts`: `TurnEvent` gains `question_request {id, questions}` and
  `question_resolved {id, outcome}`; snapshot gains `questions?`; new
  `PendingQuestion` and `QuestionAnswer` types.
- `api/ChatsClient.ts`: `startTurn` sends `can_ask: true`;
  `answerQuestion(id, stepId, {answers, skipped})`.
- `stores/chat.ts`: `pendingQuestions` and `answeringQuestions` (ids sent but
  not yet confirmed), `answerQuestion(stepId, answers)`, `skipQuestion(stepId)`,
  handling of both events and the snapshot, cleared with `unfollow()` like
  approvals. A failed or `answered: false` response drops the card silently
  (the question already ended), any other failure shows `sendError`.
- `components/QuestionCard.vue` (new, rendered inside `MessageList.vue` next to
  approvals, in the live answer):
  - per question: header chip, question text, options as pill buttons (single:
    radio behavior; multi: toggle), a final "Other" pill that reveals a text
    input;
  - **Submit** is enabled only when every question has a selection or typed
    text; **Skip** is always enabled; both disable while answering;
  - theme tokens only, the repo's radius scale, works at phone width;
  - keyboard: options are real buttons in tab order, Enter in the Other field
    submits when the form is complete.
- Saved steps of `ask_user` render in `ToolStep` as "Asked: <header>: <answer>"
  per question instead of the raw JSON (reads the saved arguments and result).
- `e2e/fakeApi.ts`: the new route, and a scripted turn that asks a question.
- READMEs of ember_api, ember_web and ai_agent updated.

### Tests (Vitest)

Store: card appears on event and on snapshot, cleared on resolve, answer sent
with the right payload, skip, late `answered: false`, other tab resolved it,
cleared on chat switch and account change. QuestionCard: single and multi
select, Other text, Submit gating, Skip, disabled while answering, saved step
rendering. `npx vue-tsc -b --noEmit` silent, `npx vite build` passes.

## Failure behaviour

- Stop during a question: the turn is cancelled (`cancelled` outcome).
- Browser closed or reloaded: the question comes back from the snapshot; if no
  one answers within 60 minutes it counts as skipped.
- ai_agent restarts: the turn ends in error as any other turn would.
- A malformed `ask_user` call from the model: the model gets the error text and
  can retry; the user sees nothing.
- An older ai_agent without `ask_user` would reject the unknown `ask_user`
  argument of `ask()`. Deploy ai_agent before ember_api. ember_api does not
  probe `status` per turn; the `user_questions` flag in `status` is for
  humans and tooling to check which version is running.

## Not included

- Voice, previews or side-by-side option panes, and answers to questions of
  a delegated agent.
- Support in `chat_cli` (it can adopt the same events later).
- Letting the user edit a submitted answer.
