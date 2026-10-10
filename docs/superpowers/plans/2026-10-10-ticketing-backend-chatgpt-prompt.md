# Prompt: implement the ticketing backend (paste into ChatGPT / Codex)

Paste everything below the line. Use an agent that can read and edit files and run commands in the repo (Codex CLI, ChatGPT with a repo connection). A plain chat window without file access cannot do this task.

---

You are implementing an approved, test-first plan in an existing Python repo. Work autonomously, task by task, and report at the end.

## Repo and documents

- Repo root: `D:\User\Documents\Programming\Python\MCPServer` (git repo, branch `main`).
- Read first, in this order:
  1. `AGENTS.md` (repo root) and `apps/mcp_server/README.md`.
  2. The spec: `docs/superpowers/specs/2026-10-10-ticketing-system-design.md`.
  3. The plan you must execute: `docs/superpowers/plans/2026-10-10-ticketing-backend.md`.
- The plan has 11 tasks. Each task lists exact files, interfaces, test code, implementation code, run commands and a commit message. The plan is the source of truth: follow it, including the code it gives. Where the plan and the spec differ, the plan wins (Task 11 updates the spec to match).

## How to work

1. Create a branch first: `git switch -c feat/ticketing-backend`. Do all work there.
2. Execute Tasks 1 to 11 in order. For each task, follow its steps exactly: write the failing test, run it and confirm it fails, implement, run it and confirm it passes, then commit with the message the task gives. One commit per task.
3. Run commands from `apps/mcp_server` (tests use `.venv_mcp/Scripts/python -m pytest ...`; if that venv is missing, use `py -m pytest`). Task 10 runs ai_agent tests from `apps/ai_agent` with `.venv_ai_agent/Scripts/python`.
4. After each task, run that task's tests. After Tasks 7, 9 and 11, run the whole mcp_server suite (`pytest -q`) and fix any regression you caused before moving on.
5. If a plan step has a mistake (wrong name, failing test that is clearly a test bug, an API that behaves differently from what the plan assumed), fix it minimally, keep the intent, and note the deviation. Do not silently weaken a test to make it pass, and do not skip a step. If you cannot resolve something after a real attempt, stop at that task and report exactly what failed with the command output.

## Rules for this repo (must follow)

- Do not touch unrelated files. The working tree may hold uncommitted changes from other work (for example under `apps/Ember/ember_api/`, a deleted `Server Launcher.lnk`, `scuti_server_launcher.exe`). Never stage, modify, revert or commit them. Always `git add` only the exact paths each task names.
- Never read, print or edit `.env`, `.env.*`, `secrets/`, `.secrets/`, or key files. Do not put real secrets anywhere. `.env.example` is fine to edit.
- Ignore `node_modules`, `.venv*`, `__pycache__`, `dist`, `build`, and old-version zips.
- Do not run git commands at any folder above the repo root. Do not push, force-push, rebase, amend, or delete branches.
- Edit instruction files only in `AGENTS.md` (never `CLAUDE.md`). Agent files live in `apps/ai_agent/agents/*.json`; the plan's Task 10 edits them directly. Do not edit anything under `.claude/skills/`.
- Code rules: non-blocking (no blocking I/O on the event loop; SQLite work goes through `asyncio.to_thread` as the plan shows), small focused modules, clear names, docstrings that explain intent, complete runnable code, no placeholders or TODOs. Match the style of neighboring files such as `apps/mcp_server/src/services/memory_store.py` and `apps/mcp_server/src/download_routes.py`.
- Never log ticket titles, descriptions, comments or error text.
- Commit messages: conventional style as given in the plan, ending with the line `Co-Authored-By: ChatGPT <noreply@openai.com>` (replace with your own agent name if different).

## Out of scope (do not build)

ember_api, ember_web, ember_admin, attachments, email notifications on ticket changes, free-form labels. Those come in later plans.

## Done means

- All 11 tasks committed on `feat/ticketing-backend`, one commit each.
- `pytest -q` in `apps/mcp_server` passes with no new failures; `pytest -q` in `apps/ai_agent` passes.
- Task 8's manual Laya smoke check is the only step you may skip (it needs the Laya model running). If you skip it, say so.

## Final report (reply with this, short)

1. Branch name and the list of commits (`git log --oneline main..HEAD`).
2. Test results: the final pass/fail counts for both suites.
3. Every deviation from the plan, with the reason.
4. Anything skipped or unresolved, with the exact error output.
5. Anything in the plan you think is wrong or risky that I should review.
