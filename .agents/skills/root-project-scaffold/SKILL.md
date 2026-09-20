---
name: root-project-scaffold
description: Create or audit a new top-level project directory at the repo root (a new server, service, or standalone application sitting alongside mcp_server/ai_agent/chat_app) so it follows the same folder-structure convention those three already share. Use whenever the user asks to add a new app/server/service to this repo, scaffold a new root-level project, or wants to check whether an existing root folder matches repo convention — even if they only describe it ("I want a new microservice for X", "add another backend next to mcp_server") without naming this skill or "folder structure" explicitly. This is about the project's *top-level shape* (what folders exist at its root) — for what goes *inside* mcp_server's capabilities/, use mcp-capability-scaffold instead.
---

# root_project_scaffold

Every project at this repo's root (`mcp_server`, `ai_agent`, `chat_app`)
shares one top-level shape. A new root-level project must match it, not
invent its own layout — consistency here is what lets `server_launcher.py`,
onboarding docs, and anyone jumping between projects rely on the same
mental map.

## The required shape

Mandatory in every root project:

| Path | What it is |
|---|---|
| `README.md` | What the project does, setup steps, requirements — see mcp_server/README.md as the fullest example |
| `pyproject.toml` | Its own dependencies — each root project is a separate Python environment, never a shared venv |
| `run.bat` | The one launcher, env-var-configured (see aiagent-scaffold's Path 2 for the pattern: don't copy the bat per instance, set env vars before calling it) |
| `configs/` | JSON config, each real file gitignored with a committed `.example` twin (`config_x.json` + `config_x.json.example`) |
| `secrets/` | Credentials/env files, same gitignored-with-`.example` pattern (e.g. `secret_llm.env.example`) |
| `src/` | The actual code |
| `tests/` | Its test suite |

Conditional — add only if the project actually needs it, don't
pre-create empty ones "for consistency":

| Path | When to add it |
|---|---|
| `data/` | Persists runtime data to disk (mcp_server, chat_app have it; ai_agent doesn't — it's stateless, see aiagent-scaffold's "Logging (there isn't any)" section for why a project can legitimately skip a folder) |
| `docs/` | Documentation beyond the README is substantial enough to split out |
| `logs/` | The project writes its own log files (needs a `logging_setup.py`-style module in `src/`, not an ad-hoc log call) |

Do not invent additional top-level folders (`lib/`, `scripts/`, `bin/`,
`app/`, etc.) — if something doesn't fit `src/`, it likely belongs inside
`src/` as a subpackage instead. If a genuinely new top-level folder seems
necessary, flag it to the user rather than adding it silently, since it
changes the convention for every project after it.

## Adding a new root-level project

1. Confirm it's actually a new *project* (its own deployable
   process/environment) and not a new capability/page/agent inside an
   existing one — those go through mcp-capability-scaffold,
   chatapp-page-scaffold, or aiagent-scaffold instead.
2. Create the mandatory folders/files from the table above. Copy
   `mcp_server/run.bat` and `mcp_server/pyproject.toml` as starting
   templates — they're the most complete examples — and strip anything
   MCP-specific that doesn't apply.
3. For every config/secret file, write both the real (gitignored) file
   and a `.example` twin with placeholder values, matching how
   `mcp_server/configs/*.json.example` and `secrets/*.env.example` do it.
4. Write `README.md` covering: what the project does, requirements,
   setup steps, how to run it — model it on `mcp_server/README.md`.
6. Register it with `server_launcher.py` (repo root) if it should be
   startable from there like the other three projects are.

## mcp_server's dotted variant

`mcp_server` already goes one step further, and a new server that owns per-capability state should copy it: the rule is
**dot-prefixed = untracked runtime state or secrets, plain `configs/` = tracked**. Its root has `.data/`, `.logs/`, `.cache/`,
`.secrets/` (in place of plain `data/`, `logs/`, `secrets/`) and `configs/`, and each capability gets the same five under
`specifics/<capability_name>/` (`.data/ .logs/ .cache/ .secrets/ configs/`). An untracked dot-folder needs no `README.md`; a
credentials README that is worth keeping lives in `docs/` (see `mcp_server/docs/secrets.md`); `.secrets/*.example` twins stay
tracked. `mcp_server/migrate_state_layout.py` moves an older checkout onto this shape. `chat_app` and `ai_agent` still use the
plain folder names above.

## Auditing an existing root folder

Walk the table above against the folder in question. Flag:
- A missing mandatory item.
- A config/secret file committed without a `.example` twin, or an
  `.example` twin that's drifted out of sync with the real file's keys.
- A top-level folder not in either table — ask whether it should move
  under `src/` or whether the convention itself needs to grow.
- A conditional folder (`data/`/`docs/`/`logs/`, or mcp_server's dotted equivalents) present but empty/unused
  — likely copy-pasted out of habit rather than needed.

## Verify before calling it done

- `ls` the new project root and confirm it matches the mandatory table
  exactly, with no extra top-level entries.
- Every `configs/*.json` and `secrets/*` file has a committed `.example`
  counterpart, and neither the real file nor real secrets are staged in
  git (`git status` — they should show as untracked/ignored, not staged).
- `run.bat` starts the project standalone (not just importable) before
  wiring it into `server_launcher.py`.
