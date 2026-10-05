# MCPServer

Project note: `Brain/Projects/MCPServer.md` in the Obsidian vault (`../../Brain/` from this folder; component notes sit beside it, e.g. `ember_api.md`).

## Agent instructions
This file is the one instruction file for every coding agent. Codex reads it directly; `CLAUDE.md` only imports it (`@AGENTS.md`) for Claude Code. Edit this file, never `CLAUDE.md`.

## Skills
Edit skills only in `.agents/skills/` (Codex reads it). Then run `python sync_skills.py` to copy them into `.claude/skills/` for Claude Code. `python sync_skills.py --check` reports drift. Never edit `.claude/skills/` directly; the next sync overwrites it. A pre-commit hook (`.githooks/pre-commit`) blocks a commit that touches either skills folder while they differ or have unstaged changes. After a fresh clone, enable it once with `git config core.hooksPath .githooks`.
