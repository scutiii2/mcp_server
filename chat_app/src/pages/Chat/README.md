# Chat

LLM conversation UI: provider/model selection, an extensions (proxied
MCP server) toggle panel, per-user chat history (list/resume/rename/
delete), and the `/api/chat` turn endpoint. Ported from MCPArchitecture
- see `docs/superpowers/specs/2026-08-22-chat-capabilities-port-design.md`.

Gated by the `chat.access` permission (route-level, via
`@require_permission("chat.access")` on every route in this blueprint,
not just the page itself). `CSRF_EXEMPT = True`: this page's JSON
`fetch()` calls carry no CSRF token, relying instead on the project-wide
`Sec-Fetch-Site`/Origin check in `src/services/security/cross_site.py`.

Chat history is a dedicated SQLite file (`data/chats.db` by default,
`src/services/chats_store.py`), separate from `app.db` - see the spec's
"Persistence" section for why. Each turn is also logged as a
`kind="chat_trace"` `LogEntry` (`src/services/log_service.log_chat_trace`),
visible on the Logs page to any account holding `logs.chat.view`.

## Background responses

Submitting a turn creates a server-owned job (`src/services/chat_jobs.py`),
not a browser-owned streaming request. The job runs the provider call and
saves its terminal transcript on a server thread, so switching chats or
disconnecting a browser does not stop an in-flight answer. Jobs are
process-local: an application restart ends them. Only one response may write
to a chat at a time.

Job status is scoped to the signed-in username. The chat list exposes only
that user's active jobs, and the status, events, cancellation, and deletion
routes reject a chat that is missing or belongs to somebody else. A caller
therefore cannot use a guessed chat ID to discover another user's activity.
The owned chat-detail endpoint includes running-job metadata and its pending
question, allowing a refresh or another tab to show the active prompt before
replaying response events. That prompt shares the process-local job lifetime
until the terminal transcript is saved.

`last_response_at` records when a successful completed AI response was saved;
cancelled, failed, usage-blocked, and command turns leave it unchanged. It
is distinct from a chat's general `updated_at`: the sidebar uses it for
completed-chat recency while running chats sort by their job start time.

The events endpoint accepts an `after_sequence` cursor (or `Last-Event-ID`)
and replays the bounded event buffer before streaming newer events. This lets
a selected chat reconnect after a temporary navigation or network loss. The
bounded buffer can truncate older events when it fills. Separately, a
completed job is evicted from the registry when its retention window expires
or the completed-job cap is reached; the saved chat transcript is then
authoritative and the client reloads it instead.

Individual chat deletion returns 404 when the ID is missing or belongs to
another user. Confirmed bulk deletion intentionally ignores missing and
foreign IDs, deleting only the requested chats owned by the signed-in user.

`POST /chat/api/chats/<chat_id>/cancel` requests cooperative cancellation for
an owned running job. Once the provider has started, that request is forwarded
to the selected `ai_agent`; the provider's terminal event determines whether
the outcome is cancelled, failed, or completed. Deleting a chat also requests
cancellation and discards its replay state, so an already-running worker
cannot recreate the deleted conversation.
