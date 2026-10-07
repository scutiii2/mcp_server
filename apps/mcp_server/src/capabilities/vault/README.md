# capabilities/vault/

Search, list and read notes in the Obsidian vault, read-only - three tools.

## Tools

| Tool | Purpose | Connection |
| --- | --- | --- |
| `tool_vault_search` | Search note titles and text. | Local vault folder |
| `tool_vault_listNotes` | List the notes in a folder. | Local vault folder |
| `tool_vault_readNote` | Read one note. | Local vault folder |

## Slash commands

| Tool | Slash command | Parameters |
| --- | --- | --- |
| `tool_vault_search` | `/vault search` | <ul><li>`query` - required. Text to look for, case-insensitive.</li><li>`folder` - optional, default empty. A vault folder.</li><li>`max_results` - optional, default `15`. 1 to 50.</li></ul> |
| `tool_vault_listNotes` | `/vault list` | <ul><li>`folder` - optional, default empty. A vault folder.</li></ul> |
| `tool_vault_readNote` | `/vault read` | <ul><li>`path` - required. The note's path inside the vault.</li></ul> |

## Typical workflow

| Sequence | Tool | Explanation |
| --- | --- | --- |
| 1 | `tool_vault_search` / `listNotes` | Find notes by text, or list a folder. |
| 2 | `tool_vault_readNote` | Read the notes that matter. |

## Configuration

`MCP_VAULT_DIR` in `.env`: the vault folder. Default `../../../../Brain`, relative to `apps/mcp_server/`.
Nothing here writes: the vault rules (`Brain/AGENTS.md`) are for agents that edit it.

Only `.md` files are read. `services/confined_paths.py` refuses absolute paths, `..`, symlinks that leave the
vault, and names that mark a secret (`.env*`, `secrets`, key files) or tooling (`.obsidian`, `.git`). Note text is
capped at 24 KB and fenced as data. The search is a plain case-insensitive text match over the first 400 KB of
each note, at most 3 lines per note.

Toggle: `"vault"` in `configs/config_capabilities.json`.
