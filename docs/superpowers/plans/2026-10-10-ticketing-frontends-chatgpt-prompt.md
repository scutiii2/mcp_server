# Prompt: implement the ticketing front ends (paste into ChatGPT / Codex)

Paste everything below the line. Use an agent that can read and edit files and run commands in the repo (Codex CLI, ChatGPT with a repo connection) and that can pause for your reply between steps. A plain chat window without file access cannot do this task.

Prerequisites: the ticketing backend (plan 1) and the ember_api plan (plan 2) are already merged to `main`. This prompt covers plan 3 only (ember_web and ember_admin).

---

You are implementing an approved, test-first plan in an existing Vue 3 + TypeScript repo. This is UI work, and the owner has a standing rule for it: **before each task you propose it and wait for approval.** Follow that rule exactly; it is part of the job.

## Repo and documents

- Repo root: `D:\User\Documents\Programming\Python\MCPServer` (git repo, branch `main`).
- Read first, in this order:
  1. `AGENTS.md` (repo root), `apps/Ember/ember_web/README.md`, `apps/Ember/ember_admin/AGENTS.md` and `apps/Ember/ember_admin/README.md`.
  2. The repo's UI conventions: `.claude/skills/ember-design-system/SKILL.md` (and its `tokens.css` and `components.md`) and `.claude/skills/ember-feature-scaffold/SKILL.md` (sections 3 and 5). Read them as documentation only; do not edit anything under `.claude/skills/`.
  3. The spec: `docs/superpowers/specs/2026-10-10-ticketing-system-design.md` (sections 4 and 5).
  4. The plan you must execute: `docs/superpowers/plans/2026-10-10-ticketing-frontends.md`.
- The plan has 6 tasks: Part A is ember_web (Tasks 1 and 2), Part B is ember_admin (Tasks 3 to 6). Each task lists exact files, interfaces, test code, implementation code, run commands and a commit message. The plan is the source of truth: follow its code and structure.
- ember_api's ticket routes already exist: read `apps/Ember/ember_api/src/routes/tickets.py` and `apps/Ember/ember_api/src/services/ticket_gateway.py` to confirm the response shapes the clients in the plan assume (`{ tickets }`, `{ ticket }`, `{ groups }`, `{ group }`, stats dict, create returns `{ ticket, duplicate, group_size }`). If a shape differs, stop and report instead of guessing.

## The approval rule (important)

For every task, in this order:
1. **Propose.** Reply with a short proposal: the task name, the files you will create or change, and anything that deviates from the plan. Then **stop and wait** for the owner to answer "approved" (or give changes). Do not write or edit any file for that task before approval. Never propose or build several tasks at once.
2. **Implement** the task test-first, exactly as the plan says.
3. **Verify** with the task's commands and report the real output (type-check clean, tests passing).
4. **Hand over.** Report what changed, what was verified and how, and the manual checks the owner should do by hand (the owner tests the UI manually; do not launch browser or Playwright verification agents, and run `npm run test:e2e` only where the plan says to).
5. **Commit** only after the checks pass and the owner agrees, with the plan's commit message. Never push.

## How to work

1. Before Task 1, create a branch: `git switch -c feat/ticketing-frontends`. Do all work there.
2. Run commands from the app folder (`apps/Ember/ember_web` or `apps/Ember/ember_admin`). Type-check: `npx vue-tsc -b --noEmit` (prints nothing when clean). Tests: `npx vitest run <file>` and `npm test`. If `node_modules` is missing in an app, stop and ask before running `npm install`.
3. If a plan step has a mistake (wrong name, a test that is clearly a test bug, a type error, an API that behaves differently from what the plan assumed), fix it minimally, keep the intent, and state the deviation in your proposal or report. Known soft spots to check as you go: the `URLSearchParams` space encoding in Task 3 (`a b` must produce `a%20b`), the `<dialog>` jsdom polyfill in tests (copy the `beforeAll` from `AccountsPanel.test.ts`), the `SegmentedControl` / `ToggleSwitch` props in each app (they differ slightly between ember_web and ember_admin; read the component first), Task 6's overview test (read the existing overview test file's setup before writing the new cases), and that `radiusScale.test.ts` passes (no literal `px` radii, no hex colors).
4. Do not silently weaken a test to make it pass and do not skip a step. If you cannot resolve something after a real attempt, stop at that task and report exactly what failed with the command output.

## Rules for this repo (must follow)

- **Dirty working tree:** it holds uncommitted work from other people, including files this plan also touches (for example `apps/Ember/ember_web/README.md`, `apps/Ember/ember_web/e2e/fakeApi.ts`, `apps/Ember/ember_web/src/api/types.ts`, `apps/Ember/ember_web/src/components/CommandFormModal.vue`, and the deleted `Server Launcher.lnk`). Run `git status` before every commit. Stage only the exact paths a task names. If a file the task must edit already has someone else's uncommitted changes, do not stage the whole file: make your edit, tell the owner, and let the owner decide how to commit it (you may use `git add -p` only if your tool supports it non-interactively; otherwise leave that file unstaged and say so). Never revert, reformat or commit other people's changes.
- Never read, print or edit `.env`, `.env.*`, `secrets/`, `.secrets/`, or key files.
- Ignore `node_modules`, `dist`, `build`, `test-results`, and old-version zips.
- Do not run git commands above the repo root. Do not push, force-push, rebase, amend, or delete branches.
- Edit instruction files only in `AGENTS.md` (never `CLAUDE.md`).
- UI rules: radius only through `--radius-*` tokens and colors only through the tokens in `src/style.css`; status is shown with an icon and a word, never color alone; no `confirm()`, use `ConfirmModal`; ticket text is rendered with `{{ }}` (never `v-html`); switches and selects that call the server show only server-confirmed state; `erasableSyntaxOnly` is on (no enums, no constructor parameter properties); pages live in `src/views/`, reusable pieces in `src/components/`.
- Code quality: small focused components, clear names, comments that explain intent, no placeholders or TODOs, no dead code. Match the style of neighbors such as `AgentsView.vue` (ember_web) and `AccountsPanel.vue` / `AccountDrawer.vue` (ember_admin).
- Commit messages: conventional style as given in the plan, ending with the line `Co-Authored-By: ChatGPT <noreply@openai.com>` (replace with your own agent name if different).

## Out of scope (do not build)

Any ember_api or mcp_server change, attachments, email notifications, a tag editor with a fixed vocabulary, assignee and type filter controls in the admin UI (the client supports them; the plan leaves their controls out on purpose). If you believe a backend change is needed, stop and report.

## Done means

- All 6 tasks approved, verified and committed on `feat/ticketing-frontends`, one commit each.
- In both apps: `npx vue-tsc -b --noEmit` is clean, `npm test` passes, and `npm run test:e2e` passes (Task 6 step 5).
- The READMEs of both apps describe the Tickets pages (Task 6).

## Final report (reply with this, short)

1. Branch name and the list of commits (`git log --oneline main..HEAD`).
2. Final results: type-check, `npm test` and `npm run test:e2e` for each app.
3. Every deviation from the plan, with the reason.
4. Files you edited that also had someone else's uncommitted changes, and how you handled staging.
5. Anything skipped or unresolved, with the exact error output.
6. The manual checks the owner should do (per page: light and dark, 768 px and 375 px widths, keyboard focus).
