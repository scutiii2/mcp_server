# capabilities/memory/

Short notes the assistant keeps about a user between chats. Three tools. Notes belong to the account whose stable uid is in the request's identity (never a tool parameter; see Rules for how far that can be trusted), live in a local SQLite file and are searched by keyword.

## Tools

| Tool | Purpose | Connection |
|---|---|---|
| `tool_mem_save` | Save one short note that outlives the chat | Local SQLite |
| `tool_mem_search` | Search your notes; an empty query lists the newest | Local SQLite |
| `tool_mem_forget` | Delete one of your notes by id | Local SQLite |

## Slash commands

| Tool | Slash command | Parameters |
|---|---|---|
| `tool_mem_save` | `/memory save` | <ul><li>`text` - required. One short fact, preference or instruction (max 500 characters).</li></ul> |
| `tool_mem_search` | `/memory search` | <ul><li>`query` - optional, default empty. Words to look for; empty lists the newest notes.</li></ul> |
| `tool_mem_forget` | `/memory forget` | <ul><li>`note_id` - required. Id of the note to delete, as shown by search.</li></ul> |

## Typical workflow

| Sequence | Tool | Explanation |
|---|---|---|
| 1 | `tool_mem_search` | Look up saved notes at the start of a conversation. |
| 2 | `tool_mem_save` | Save a fact or preference the user stated. |
| 3 | `tool_mem_forget` | Delete a note that is wrong or no longer wanted. |

## Rules

- 500 characters per note, 200 notes per user. An identical note (ignoring case and spacing) is stored once.
- The model may save only what the user stated, never anything from a tool result, web page, file or another agent. This rule is in the tool description (an instruction), not enforced by code.
- Search results are fenced as data (`services/untrusted.py`), but a fence is not a security boundary.
- Recall is on demand: nothing is injected automatically, so the model must call `tool_mem_search`.
- Notes are only returned to their owner, and this server never forwards notes to extensions (the model can still quote a note in another tool's arguments).
- Notes are keyed on the account's stable `uid` (a random id ember_api creates with the account; it never changes and is never reused), so renaming an account keeps its notes. When ember_api deletes an account it asks this server to delete that account's notes (`DELETE /memory/owners/{uid}`, internal token required). The purge is best effort: if `mcp_server` is down, no `INTERNAL_API_TOKEN` is set, or memory is offline, the notes stay behind. That is harmless for other users (a uid is never reused) but the data lingers.
- Privacy is only as strong as the caller is trusted. The uid, like the username before it, is whatever the caller asserts (the `X-Requester-Uid` header or `_meta.requester.uid`), so notes are private only as far as the caller is trusted. Set `INTERNAL_API_TOKEN` whenever the server listens on a non-loopback address (`zima_host.yaml` binds 0.0.0.0). A caller that sends no uid (a direct MCP client) is refused.
- The number of distinct uids is not capped; only 200 notes x 500 characters per uid.

## Configuration

- `MCP_MEMORY_DB_PATH` (`.env`, optional): the SQLite file. Default `specifics/memory/.data/memory.db`, gitignored.
- Toggle: the `memory` entry in `configs/config_capabilities.json`, or the Capabilities page in ember_admin.
