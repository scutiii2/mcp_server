# MCPServer

Project note: `Brain/Projects/MCPServer.md` in the Obsidian vault (`../../Brain/` from this folder; component notes sit beside it, e.g. `ember_api.md`).

## Skills
Edit skills only in `.agents/skills/` (Codex reads it). Then run `python sync_skills.py` to copy them into `.claude/skills/` for Claude Code. `python sync_skills.py --check` reports drift. Never edit `.claude/skills/` directly; the next sync overwrites it.
