# ember multi-agent (Phase 2) — design

Date: 2026-10-04
Status: approved in brainstorming, awaiting spec review
Scope: `ember_api/` and `ember_web/`. Depends on the registry, event and usage
contracts in `2026-10-04-ai-agent-multi-agent-design.md` (Phase 1). Phase 1 is
implemented and verified before this phase starts.

## Goal

ember always talks to the main (entry) agent, so the agent dropdown goes away.
While a turn runs, the user sees live which agent is working (orchestrator,
then the specialist it delegated to). Usage shows tokens per agent, provider and
gateway, with date and time.

## Non-goals

- chat_app changes (being sunset).
- Letting users pick a specialist directly.
- Polling. Live activity uses the existing `/events` SSE stream.

## ember_api

### Entry agent

`AgentDirectory` (`src/services/agent_directory.py`):

- `AgentEntry` gains `entry: bool`, `orchestrator: bool` and `focus: str`, read
  from the registry with defaults `False`, `False`, `""` when absent.
- New `entry()` returns, in order: the registered agent with `entry: true`; else
  the first registered agent with `orchestrator: true`; else `claude-agent` if
  registered; else `None`. The fallbacks let this phase work against an
  ai_agent registry written before Phase 1.
- `all()` and `get()` are unchanged and still back the proxy allow-list.

Routes:

- `POST /chats/{id}/turns` (`start_turn`) and `POST /chats/{id}/summarize`
  (`summarize_chat`) use `entry()` instead of the request's `agent_id`. When
  `entry()` is `None` they return `503` with detail `"No agent is running"`.
- `TurnRequest.agent_id` and `SummarizeRequest.agent_id` become optional and are
  ignored, so an older ember_web that still sends them works.
- An existing chat saved with another `agent_id` (for example `openai-agent`)
  is answered by the entry agent on its next turn, and the chat's `agent_id` is
  updated to the entry agent's id. Saved messages keep their own `agent` field.
- Routes that act on a running turn (status, cancel, decide) keep accepting any
  registered id, so a turn started before a change of entry agent can still be
  cancelled or answered.
- `GET /api/agents` is removed. New `GET /api/agent` (under the `/api/` prefix) returns `{id, label}` of
  the entry agent, or `503` as above.

### Live activity relay

`src/services/turns.py`:

- The relayed event allowlist adds `agent_start`, `agent_end` and
  `agent_token`. Their `agent_id`, `agent_label`, `delegated_by`, `question`,
  `step_id`, `ok`, `text` and `at` keys pass through. `question` is capped at
  500 characters and `text` chunks at 4,000 characters before relay.
- Each turn keeps an `active_agents` stack: push on `agent_start`, pop the
  matching `step_id` on `agent_end`. Only delegated agents are on the stack
  (outermost first); the browser prepends the entry agent's own label.
- The turn snapshot (sent to a browser that connects or reconnects mid-turn)
  includes `active_agents: [{agent_id, label, since, step_id}]`, so it shows who
  is working without replaying every event. Steps are keyed `(agent_id, id)`,
  since two agents can reuse the same step id.
- `agent_token` text is not saved with the answer. Only the final answer and
  steps are saved, as today. Saved steps keep the `agent_id` and `agent_label`
  stamped by Phase 1.

### Usage

- Alembic migration in `migrations/versions/` adds nullable columns to
  `usage_records`: `agent_id` (String 120), `provider_id` (String 60),
  `gateway` (String 60), `started_at` (DateTime), `finished_at` (DateTime),
  `delegated_by` (String 120). Downgrade drops them.
- `usage_rows()` (`src/services/usage_service.py`) maps the new `agent_usage`
  fields. For new rows, the existing `agent` column holds `agent_id` when
  present, else `provider_id` as today. Old rows are not rewritten.
- `AgentUsageIn` (`src/routes/chats.py`) accepts the new fields as optional.
- `_agent_usage` (`src/services/turns.py`) includes `agent_label`,
  `provider_id`, `gateway`, `started_at` and `finished_at` when known.
- Usage API (`src/routes/usage.py`): add `group_by` with values `agent`,
  `provider`, `gateway`, `model` (default keeps today's output), and optional
  `agent` and `provider` filters. Row listings include `started_at`,
  `finished_at` and `created_at`. All times are UTC ISO-8601; the browser shows
  local time.
- New `GET /api/usage/records` lists the account's usage rows, newest first,
  with the same `days`, `since`, `agent` and `provider` filters and `limit`
  1-500 (default 100).
- The `/api/usage` report gains `group_by` and `groups: [{key, tokens,
  input_tokens, output_tokens, turns}]`, biggest first; a missing value is
  grouped as `unknown`.

## ember_web

Each step below is proposed for approval before it is made.

1. **Remove the agent picker.** Delete `src/components/AgentPicker.vue` and
   `src/stores/agents.ts`. Remove `agent_id` from requests in
   `src/api/ChatsClient.ts` and `src/api/AiAgentClient.ts`, and from
   `src/api/types.ts`. `src/services/ConversationStorage.ts` still reads an old
   saved `agent` field but no longer writes it. The header shows
   "Talking to <label>" from `GET /api/agent`.
2. **Live activity.** `src/stores/chat.ts` handles `agent_start`, `agent_end`
   and the snapshot's `active_agents`, keeping the stack per running turn. New
   `src/components/AgentActivity.vue` sits above the streaming answer and shows
   the stack as a breadcrumb, for example `Ember → Calculator · 3s`, using
   `ElapsedTime.vue` for the innermost agent. It is hidden when only the entry
   agent is working with no tool step, and removed when the turn ends.
3. **Steps per agent.** `src/components/ToolSteps.vue` shows an agent badge on
   each step whose `agent_id` is not the entry agent. `agent_token` text is
   shown in a collapsible "<label> is working" block inside the matching
   `delegate_to_agent` step (by `step_id`), never in the main answer.
4. **Answer usage.** The existing per-agent token breakdown on an answer shows
   the agent label, provider and gateway.
5. **Usage page.** Add a group-by selector (agent, provider, gateway, model) and
   columns for agent, provider, gateway, and date/time.

## Errors

| Case | Behavior |
|---|---|
| No entry agent registered | New turn and summarize return 503; ember_web shows "No agent is running" in place of the input hint and keeps the draft. |
| Entry agent changes between turns | Next turn goes to the new entry agent; chat's `agent_id` updates. |
| `agent_end` never arrives (specialist crash) | The stack is cleared when the turn's `final` or `error` event arrives. |
| Unknown event type from a newer ai_agent | Dropped by the relay, as today. |
| Old usage rows without new columns | Shown with "—" in new columns; grouped under their `agent` value. |

## Known limits

- Saved answers from before keep their old agent id. The browser shows that id
  as is, since only the entry agent's label is known.

## Testing

ember_api (pytest):

- `entry()` with an entry agent, with only an orchestrator, with only
  `claude-agent`, and with none.
- `start_turn` and `summarize_chat` ignore `agent_id`, use the entry agent, and
  return 503 when there is none; an old chat's `agent_id` is updated.
- `GET /api/agent`; `GET /api/agents` returns 404.
- Relay forwards the new events with caps; snapshot `active_agents` across
  start, nested start, end, and final without end.
- Migration upgrade and downgrade.
- `usage_rows()` mapping with and without new fields; usage `group_by` and filters.

ember_web (vitest):

- Chat store: stack handling, snapshot restore, clearing on final and error.
- `AgentActivity.vue` rendering for one and two levels.
- `ToolSteps.vue` badges and the collapsible agent text.
- No picker rendered; requests carry no `agent_id`.
- Usage page group-by.

End-to-end (Playwright, existing test): a turn shows the activity indicator and
the answer renders without a picker.
