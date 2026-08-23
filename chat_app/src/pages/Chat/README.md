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
