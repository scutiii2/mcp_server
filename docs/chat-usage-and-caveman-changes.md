# Chat usage tracking, caveman mode and watchers

Summary of the changes made to `chat_app` and `ai_agent` on 2026-09-21,
after the config auto-generation work in `config-autogeneration-and-validation.md`.
Ported to branch `home` on 2026-09-25.

## 1. Context threshold lowered to 0.6

`AUTO_SUMMARIZE_THRESHOLD_RATIO` (`chat_app/src/services/summarization.py`) and
`CONTEXT_USAGE_THRESHOLD_RATIO` (`chat_app/src/pages/Chat/script.js`) went from
0.8 to 0.6. They must stay equal: the browser cannot share the Python constant.
`log_attachment` messages were already filtered out of the LLM history
(`_llm_history_from_messages`), so no change was needed there.

## 2. Caveman mode toggle

- A pill-style "CAVEMAN" switch sits next to the agent refresh button on the
  Chat page. The choice is kept in `localStorage` (`chat.caveman`).
- Each chat request carries `caveman`. It goes through `chat_api`,
  `ai_agent_client.ask` / `ask_stream`, the `ask` tool in `ai_agent/src/server.py`,
  `agent_config.run_chat` and both providers.
- The providers append `CAVEMAN_INSTRUCTIONS` (`ai_agent/src/llm/agent_roles.py`,
  via `system_prompt_for`) to the system prompt for that turn only. Prompt-level,
  not a regex filter, so code, errors and numbers are not mangled.
- The rules include two safety lines: never drop not/no/never/only/except, and
  use full sentences for warnings and irreversible actions.
- Not affected: slash commands (no LLM), `/interpret` summarization, and
  delegated agents (`delegate_to_agent` does not pass the flag).

## 3. Input/output tokens and per-agent usage

- `ChatResult` gained `input_tokens`, `output_tokens` (summed over all tool
  rounds) and `delegated_usage`. Both providers fill them.
- `delegation.py` collects the usage of every delegated agent in a context
  variable bound per turn by `agent_config.run_chat`.
- The `ask` result now has `input_tokens`, `output_tokens` and `agent_usage`: a
  list with the top-level agent first, then each delegated agent (with their own
  nested delegations). chat_app saves these on the assistant message.
- The context popover (ring at the top right of the chat) was redesigned: a
  "Usage" title, 6-hour and 7-day bars, a "This chat" section with the context
  window bar and input/output of the last turn, and a collapsed "Breakdown by
  agent" list.

## 4. Usage limits count delegated agents

The 6-hour and weekly limits now count the sum of `agent_usage`, not only the
top-level agent. The token count shown on each message is still the top-level
agent's own.

## 5. Usage history, sidebar panel and tracker page

- `usage.db` is no longer pruned to 7 days. Rows are kept; the tracker shows the
  last 12 months (`SHOWN_HISTORY_MONTHS`).
- `token_usage` gained `agent`, `model`, `input_tokens`, `output_tokens` and
  `chat_id` (added automatically to an existing database). One row is written per
  agent per turn; rows of one turn share a timestamp.
- Chat sidebar: a "Usage" button above "Manage Chats" opens a panel with the
  current session (6 hours) and this week (7 days) bars, the calendar-month
  total, the top agents and a link to the tracker.
- New page `chat_app/src/pages/Usage/` (`/usage`): stat cards, a 12-month
  heatmap, a per-agent table, ranges (this calendar month, 7d, 30d, 12 months)
  and a Markdown export (`/usage/export.md`).
- Permissions: `chat.access` shows your own usage. `usage.view_all` (new) lets an
  account view another user's usage.
- `chat_app/src/services/usage_backfill.py` is a one-time script that fills the
  agent, model and chat id on old rows from `chats.db`. Dry run by default;
  `--apply` backs up `usage.db` first. Input/output cannot be recovered.

## 6. Watchers page: recipients are read-only

- The Recipients column is display-only. The Edit button, its click handler
  and `POST /watchers/api/recipients` were removed, and the `watchers.manage`
  permission is no longer registered.
- Recipients are still set on the mcp_server side, through each capability's
  `tool_<alias>_setWatcherRecipients`.
- The "Watchers' recipients" write-action section was removed from the
  `chatapp-page-scaffold` skill (both `.claude` and `.agents` copies).

## 7. Smaller fixes carried over

- `text_extraction._extract_xlsx` keeps blank cells as empty columns so later
  values stay aligned; trailing blanks are trimmed.
- `tool_titles.title_for` drops the `tool_<prefix>_` capability tag and splits
  camelCase, so `tool_srv_startApp` reads "Start App".
- Streamed replies hide `[[DOWNLOAD ...]]` markers while typing and render the
  download card as soon as the reply finishes (`renderReplyBody`).

## Tests and known failures

New or updated: `ai_agent/tests/test_agent_roles.py`, `test_delegation.py`,
`test_server.py`, `test_agent_config.py`; `chat_app/tests/test_chat_page.py`,
`test_ai_agent_client.py` and the new `test_usage_page.py`.

Failing before these changes and still failing: `test_capabilities_page`, `test_chat_client` and `test_logs_page`.
