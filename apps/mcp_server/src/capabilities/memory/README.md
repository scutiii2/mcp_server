# capabilities/memory/

Short notes the assistant keeps about a user between chats. Three tools. Notes belong to the user named in the request's identity (never a tool parameter; see Rules for how far that can be trusted), live in a local SQLite file and are searched by keyword.

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
- Ownership is keyed on the username only. Ember lets admins rename or delete accounts and nothing purges or moves notes then: a rename orphans the user's notes, a deleted account's notes stay, and a new account that takes a freed username inherits the old notes.
- Privacy is only as strong as the caller is trusted. The identity is whatever the caller asserts (the `X-Requester-Username` header or `_meta.requester`), so notes are private only as far as the caller is trusted. Set `INTERNAL_API_TOKEN` whenever the server listens on a non-loopback address (`zima_host.yaml` binds 0.0.0.0).
- The number of distinct usernames is not capped; only 200 notes x 500 characters per username.

## Configuration

- `MCP_MEMORY_DB_PATH` (`.env`, optional): the SQLite file. Default `specifics/memory/.data/memory.db`, gitignored.
- Toggle: the `memory` entry in `configs/config_capabilities.json`, or the Capabilities page in ember_admin.
