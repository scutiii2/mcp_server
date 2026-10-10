# capabilities/memory/ static and state files

## `apps/mcp_server/specifics/memory/.data/memory.db`

- Runtime state: a SQLite database created on the first save. Gitignored by `/apps/mcp_server/specifics/*/.data/`.
- Tables: `notes` (id, owner, text, norm, created_at) and `notes_fts`, an FTS5 index over the note text whose rowid equals `notes.id`.
- Lifecycle: written by `tool_mem_save`, read by `tool_mem_search`, deleted from by `tool_mem_forget`. Never edited by hand; delete the file to wipe every user's notes.
- Contains user-stated personal facts. Back it up and protect it like account data. Note text is never written to the logs. Ember does store each answer's tool steps, including saved or searched note text, in the chat transcript, and `tool_mem_forget` removes the note from memory but not from past chats.
- Notes are keyed on the username only (no purge or move when Ember renames or deletes an account, so a rename orphans notes and a reused username inherits them), and the username is whatever the caller asserts: set `INTERNAL_API_TOKEN` whenever the server listens on a non-loopback address. Distinct usernames are not capped (only 200 notes x 500 characters each).
