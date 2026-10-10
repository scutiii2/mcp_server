# Prompt: implement the ticketing ember_api plan (paste into ChatGPT / Codex)

Paste everything below the line. Use an agent that can read and edit files and run commands in the repo (Codex CLI, ChatGPT with a repo connection). A plain chat window without file access cannot do this task.

Prerequisite: the ticketing backend (plan 1) is already merged to `main`. This prompt covers plan 2 only (ember_api). The front-end plan comes after this one lands.

---

You are implementing an approved, test-first plan in an existing Python repo. Work autonomously, task by task, and report at the end.

## Repo and documents

- Repo root: `D:\User\Documents\Programming\Python\MCPServer` (git repo, branch `main`).
- Read first, in this order:
  1. `AGENTS.md` (repo root) and `apps/Ember/ember_api/README.md`.
  2. The spec: `docs/superpowers/specs/2026-10-10-ticketing-system-design.md` (section 3 is the part you build).
  3. The plan you must execute: `docs/superpowers/plans/2026-10-10-ticketing-ember-api.md`.
- The plan has 5 tasks. Each task lists exact files, interfaces, test code, implementation code, run commands and a commit message. The plan is the source of truth: follow it, including the code it gives.
- mcp_server's ticket routes (`/tickets*`, `/ticket-admin/*`) already exist in `apps/mcp_server/src/ticket_routes.py`. Read it to confirm the shapes the plan's gateway and fake upstream assume. ember_api never talks to mcp_server's database; it only proxies.

## How to work

1. Create a branch first: `git switch -c feat/ticketing-ember-api`. Do all work there.
2. Execute Tasks 1 to 5 in order. For each task: write the failing test, run it and confirm it fails, implement, run it and confirm it passes, then commit with the message the task gives. One commit per task.
3. Run commands from `apps/Ember/ember_api`. Tests: `.venv_ember_api/Scripts/python -m pytest <target> -v` (if that venv is missing, check `run.bat` for the venv name it creates, or fall back to `py -m pytest`).
4. After Tasks 1, 3 and 4, run the whole ember_api suite (`pytest -q`) and fix any regression you caused. Task 1 changes the permission registry and migration head, so some existing tests may hard-code permission lists or `HEAD = "0010"`: update those expectations, never the application code, to match the plan.
5. If a plan step has a mistake (wrong name, a test that is clearly a test bug, an API that behaves differently from what the plan assumed), fix it minimally, keep the intent, and note the deviation. Known soft spots to check as you go: the `Account(...)` constructor call in the Task 2 gateway test (build it the way other tests do), the log order assertion in Task 4 (newest first, per existing tests such as `test_server_info.py`), and pydantic's handling of `Annotated[int, Field(ge=1)] | None` in the `MoveIn` model. Do not silently weaken a test to make it pass and do not skip a step. If you cannot resolve something after a real attempt, stop at that task and report exactly what failed with the command output.

## Rules for this repo (must follow)

- Do not touch unrelated files. The working tree may hold uncommitted changes from other work (for example `Server Launcher.lnk` deleted, `scuti_server_launcher.exe`, files under `apps/Ember/ember_web`). Never stage, modify, revert or commit them. Always `git add` only the exact paths each task names.
- Never read, print or edit `.env`, `.env.*`, `secrets/`, `.secrets/`, or key files. Do not put real secrets anywhere.
- Ignore `node_modules`, `.venv*`, `__pycache__`, `dist`, `build`, and old-version zips.
- Do not run git commands above the repo root. Do not push, force-push, rebase, amend, or delete branches.
- Edit instruction files only in `AGENTS.md` (never `CLAUDE.md`). Do not edit anything under `.claude/skills/`.
- Alembic: the plan's migration file `0011_ticket_permissions.py` is hand-written data only (no schema change), so do not run `scripts.migrate_db revision`. `tests/test_migrations.py` must still pass, including its check that models and migrations agree.
- Code rules: non-blocking (async routes, no blocking I/O on the event loop), small focused modules, clear names, docstrings that explain intent, complete runnable code, no placeholders or TODOs. Match the style of neighboring files such as `src/routes/server_info.py`, `src/services/mcp_server_info.py` and `src/routes/config_issues.py`.
- POST bodies are JSON only (existing middleware). Never log ticket titles, descriptions or comment bodies.
- Commit messages: conventional style as given in the plan, ending with the line `Co-Authored-By: ChatGPT <noreply@openai.com>` (replace with your own agent name if different).

## Out of scope (do not build)

ember_web, ember_admin, any mcp_server change, attachments, email notifications, rate limiting of ticket creation. If you believe an mcp_server change is needed, stop and report instead of editing it.

## Done means

- All 5 tasks committed on `feat/ticketing-ember-api`, one commit each.
- `pytest -q` in `apps/Ember/ember_api` passes with no new failures.
- The spec's section 3 and the ember_api README describe the routes as built (Task 5).

## Final report (reply with this, short)

1. Branch name and the list of commits (`git log --oneline main..HEAD`).
2. Final pass/fail counts of the ember_api suite.
3. Every deviation from the plan, with the reason (including any existing test expectation you had to update, and why).
4. Anything skipped or unresolved, with the exact error output.
5. Anything in the plan you think is wrong or risky that I should review.
