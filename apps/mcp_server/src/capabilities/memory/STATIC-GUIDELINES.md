# capabilities/memory/ static and state files

## `apps/mcp_server/specifics/memory/.data/memory.db`

- Runtime state: a SQLite database created on the first save. Gitignored by `/apps/mcp_server/specifics/*/.data/`.
- Tables: `notes` (id, owner, text, norm, created_at) and `notes_fts`, an FTS5 index over the note text whose rowid equals `notes.id`.
- Lifecycle: written by `tool_mem_save`, read by `tool_mem_search`, deleted from by `tool_mem_forget`. Never edited by hand; delete the file to wipe every user's notes.
- Contains user-stated personal facts. Back it up and protect it like account data. Note text is never written to the logs.
