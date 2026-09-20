---
name: mcp-capability-scaffold
description: Scaffold a new capability (tool) in mcp_server, or add a tool/command to an existing capability, following this repo's established contract.py/domain.py/tool.py pattern. Use whenever the user asks to add a new MCP tool, a new "/<id> ..." chat command, or wants to expose any new piece of backend logic through mcp_server — even if they just describe the desired behavior ("I want a tool that checks X and reports back") without naming files or mentioning "capability" explicitly. Also use when reviewing whether an existing capability follows the repo's conventions (contract/domain/tool split, capability_meta registration, help.json, config_capabilities.json toggle).
---

# mcp_server capability scaffolding

`mcp_server` (this repo's MCP tool server — see [mcp_server/src/capabilities/README.md](../../mcp_server/src/capabilities/README.md), the source of truth this skill compresses) organizes every tool as a self-contained folder under `mcp_server/src/capabilities/`. The folder shape itself is domain-agnostic — the one capability in this checkout today is `server_manager` (start/stop/restart/list managed apps), but nothing about `contract.py`/`domain.py`/`tool.py`/`capability_meta` requires that; the same shape fits a capability wrapping any external system, API, or piece of internal logic. Follow it exactly regardless of domain — a new capability that deviates breaks the generic `format_command_result()` rendering, the `/capabilities` toggle, and the `/<id> help` command, all of which walk every capability the same way rather than special-casing by name.

Read one existing capability end to end first if you haven't seen this codebase's pattern before — `server_manager/` is the reference; its `tool.py` shows every mechanical convention below in one file, even though its domain (managed apps) won't match what you're building.

**REQUIRED SUB-SKILL:** Use checking-the-catalog before writing any new
function/class in `domain.py` — check `catalog_service` for an existing
tagged building block in chat_app/mcp_server/ai_agent before designing
the interface from scratch.

## Before scaffolding: is this a new capability or a new tool on an existing one?

- **New capability** (a new domain of logic entirely, e.g. "check transport queue status" or "query a ticketing system"): full scaffold, steps below.
- **New tool on an existing capability** (another check within a domain a capability already owns): skip straight to writing the `contract.py` model + `domain.py` function + `tool.py` `@command`/`@mcp.tool` pair inside the existing folder. Don't touch `__init__.py`, `run.py`, or `config_capabilities.json` — those are per-capability, not per-tool.
- **Wrapping an MCP server that already exists elsewhere** (not logic living in this repo): that's an *extension*, not a capability — see `mcp_server/src/services/extensions.py` instead. Don't scaffold a capability folder for this case.

## The three-file split (non-negotiable)

Every capability is `contract.py` + `domain.py` + `tool.py`, each with one job:

1. **`contract.py`** — Pydantic request/result models only. No logic. Every result model should end with a `message: str` field (human-readable summary) — that's what `format_command_result()` pulls out and shows first in chat_app. Scalar fields render as bullet lines; a `list[dict]`/`list[BaseModel]` field with uniform keys renders as a Markdown table. Only reach for the alternate `status` + `report: str` shape when the output is genuinely a fixed-width status readout — it's the exception, not the default.
2. **`domain.py`** — the real logic, typed in and typed out. Imports **only** `src/services/*` (ssh, email, app_config, pending_requests) — never `mcp`, never anything MCP-protocol-specific, never `tool.py`. This is what makes `domain.py` unit-testable without spinning up a server, and it's the file `pytest` actually exercises. If you catch yourself importing `@mcp` here, the logic belongs in `tool.py` instead.
3. **`tool.py`** — thin glue only: load config from `settings`, call the one matching `domain.py` function, return its result. `@mcp.tool()` appears here and nowhere else in the capability. Each tool function also gets `@command(name=..., description=...)` (unless it's meant to be agent-only — see the "MCP-only tools" note below) and `@offload` (existing capabilities always do; it's what keeps blocking work off the request-handling thread).

## Folder shape at a capability's top level (closed whitelist)

A capability's top level is **not** a free-for-all — only these belong there, everything else is misplaced: `contract.py`, `domain.py`, `tool.py`, `help.json`, `README.md`, `STATIC-GUIDELINES.md`, `__init__.py`, plus two folder kinds. See `mcp_server/src/capabilities/README.md`'s "Shape of a capability" for the canonical rule; this is the summary a scaffold needs:

- **`utils/`** — any other `.py` file the capability needs (its own `__init__.py`, and its own `README.md` if it holds more than one file). Nothing non-Python goes here.
- **No state or capability-owned config inside the capability folder.** It lives in `mcp_server/specifics/<capability_name>/`: dot-prefixed folders (`.cache/`, `.data/`, `.logs/`, `.secrets/`, ...) hold **runtime/generated state only** (a cache, a SQLite audit DB, session files, generated output) and are always gitignored; a plain `configs/` folder holds tracked capability-owned config. Never hand-maintained reference data in a dot-folder. Wire each path as a `Settings` field in `mcp_server/src/config.py` whose default is relative to `mcp_server/` and sits under `specifics/<capability_name>/` (e.g. `specifics/server_manager/.data/audit.db`); `.gitignore` already ignores `specifics/*/.{data,logs,cache,secrets}/`, so a new capability adds no ignore entry, and an untracked dot-folder needs no `README.md`. Files a capability *generates* (work orders, downloaded archives, per-system audit JSON) go in its own `.logs/` through a dedicated `Settings` field, never under the general `log_dir`. State shared by every capability lives in `mcp_server`'s own root `.data/` `.logs/` `.cache/` `.secrets/` (`pending_requests.db`, `server.log`, `secret_*.env`); `configs/` at that level is tracked.
- **`static/`** — curated reference data that's neither code nor runtime state: a knowledge base, policy documents, reference `.txt` definitions. Not dot-prefixed. One subfolder per category (`static/knowledge/`, `static/policies/`, ...), each with its own `README.md`. Tracking is decided per subfolder: some commit their real content because it *is* the source; others (org-specific rules, policy docs) gitignore the real content and commit only the `README.md` plus — for JSON files only — a `<name>.json.example` sibling documenting the shape. Pick whichever a new capability's data actually needs; don't default everything to gitignored, and don't default everything to committed.

If the capability creates any dot-folder or `static/` subfolder, `STATIC-GUIDELINES.md` documenting it is **mandatory**, not optional — see step 3 below.

## Tool function conventions (copy from `server_manager/tool.py`)

- Parameter typing via `Annotated[type, Field(description=...)]` — every parameter needs a `description`, since that's the schema an MCP client (and chat_app's "/" command help) shows the caller.
- If the tool targets one of several configured external systems/environments, give it a labeled-target parameter built from a `known_*` helper computed once at import time (not per-call), with `examples=` populated from it (add `json_schema_extra={"input": "select", "options_url": ...}` for a server-fed dropdown - see "Chat form inputs"), resolving the label through a small config loader in `services/app_config.py`.
- If the tool needs to know who called it (for an audit trail), do NOT add it as a tool parameter — a declared parameter is something any MCP caller, including an LLM deciding its own tool arguments, could set, which defeats the point of an audit trail. Instead call `current_username()`/`current_email()` from `src/services/identity_context.py` wherever the audit row gets written; chat_app's command layer attaches the real value as an `X-Requester-Username`/`X-Requester-Email` HTTP header on the underlying MCP call (see `_IDENTITY_INJECTED_TOOLS` in `chat_app/src/services/commands.py`), which `IdentityContextMiddleware` reads into a per-request contextvar server-side. Absent (a different MCP client, or the LLM Q&A/ai_agent path, which doesn't thread end-user identity today) just gets `""` back, never an error.
- `@mcp.tool(meta={"keywords": [...], "display_label": "..."})` - `keywords` are lowercase terms a user might type or search for, for tool discovery. `display_label` is a short present-tense phrase ("Checking app status", not the tool name) shown wherever a caller renders live tool-call progress - chat_app's Chat trace UI (`step_start`/`step_end` SSE events). **`display_label` is mandatory on every tool**, enforced by `mcp_server/tests/test_tool_display_labels.py`.
- **Tools never call an AI.** A tool is deterministic: it reads/computes and returns a result. If the result needs interpreting (a judgment call, a plain-language explanation), add `"ai_explain_result": True` to the meta. ai_agent (`src/mcp_upstream.py`'s `tool_description()`) then appends an explain-the-result note to that tool's description, so the assistant that ran it explains the result to the user. The old `needs_ai_review` meta, `pending_ai_review`/`ai_instructions` result fields and `ai_required` in help.json are gone - do not reintroduce them, and do not import an LLM client into `domain.py`/`tool.py`. Classify what is unresolved deterministically instead (e.g. return an `unclassified` bucket).
- **Tool naming: `tool_<alias>_<camelTask>`** - the function name IS the tool name (FastMCP), e.g. `tool_srv_listApps`. Alias example: `srv` (server manager). A tool with a `@command` gets a matching slash command `/<id> <snake_task>` (id = `capability_meta` id, e.g. `server`), e.g. `/server list`; `@command` records `tool_name=fn.__name__`.
- **A capability with an audit trail or watchers carries tool-only tools (no `@command`)** for them: `tool_<alias>_getAuditLog`, `tool_<alias>_listWatchers`.
- Multi-item parameters (a list of items) take a comma-separated string, run each item, and return a batch result with a `failed` list so one bad item does not abort the rest.
- **Never ask the user for something config already knows.** If a value is derivable from a config file, it is not a tool parameter - look it up inside the tool, fail with an error naming the file when it is missing, and say in the docstring not to ask the user for it (an AI otherwise asks). Show the derived value read-only with the `shows` hint on the relevant param (see "Chat form inputs").
- Docstrings matter: they're what an LLM-routed chat turn sees when deciding whether/how to call the tool. State what it reads, what it computes deterministically vs. what's left to the caller, and what tool to run before/after it in a multi-step workflow.
- **MCP-only tools** (no `@command`): skip the `@command` decorator when a parameter's shape can't be expressed in a slash command's `key=value` syntax — e.g. a `list[SomeModel]` parameter. Leave a comment above the function explaining why.

## Chat form inputs (how a tool parameter renders)

chat_app's command form is built from the tool's JSON schema - **never add per-command or per-capability JS branches to
`chat_app/src/pages/Chat/command_form_modal.js`**. Control the widget from the tool parameter instead:

- Standard schema keys: `Literal[...]`/`enum` -> dropdown (enforced by the server), `examples=` -> dropdown of non-binding
  suggestions, `Field(ge=, le=)` -> min/max, `max_length`, `pattern`, `format="file"` -> file picker.
- Hints via `Field(json_schema_extra={...})`: `input` (`text`, `textarea`, `password`, `number`, `range`, `date`, `select`,
  `hidden`), `options_url` (a plain path on mcp_server returning a list of strings, a list of `{"value", "label", ...}` or a
  `{value: label}` object - chat_app resolves it into `options` in `/chat/api/commands`), `depends_on` (another param whose
  value fills a `{placeholder}` in `options_url`; the select stays disabled until it has a value; fetched through
  `/chat/api/param-options`, which only accepts an `options_url` some command declares), `sets` (`{other_param: option_field}`:
  choosing an option also fills those params - pair with `"input": "hidden"` on the filled param), `shows`
  (`{label: option_field}`: read-only lines under the select, e.g. an option's description) and `initial` (text-box prefill;
  `{timestamp}` becomes `YYYYMMDDHHMMSS`).
- An options route is a small GET in `mcp_server/src/command_routes.py`; if the fetch fails the form falls back to a plain input. `mcp_server/src/capabilities/README.md`
  ("Form inputs") is the reference - keep it, `commands.py`'s `CommandParam` and the modal in step when adding a hint.

## Logging

Use the standard library logger, not `print()` or a bespoke handler. `mcp_server/src/run.py` calls `configure_logging(settings.log_dir)` once at startup (`src/utils/logging_setup.py`), wiring the root logger to a rotating `.logs/server.log` (5MB × 3 backups) plus stderr. A new capability just needs `logger = logging.getLogger(__name__)` at module level in `domain.py` (see `server_manager/domain.py`) and calls to `logger.info()`/`logger.warning()`/`logger.error()` flow there automatically — no per-capability setup. Never call `configure_logging()` again or attach a new handler; that wiring happens exactly once, in `run.py`. This is ordinary application logging (unexpected errors, warnings, notable branches) — a capability's per-call audit trail (who ran what, with what outcome) is a separate concern.

## Background job watchers (long-running external jobs)

If a tool schedules a job that runs for minutes/hours on the external system (a background job, an upgrade, an async report) and the capability needs to notice when it finishes without a human polling manually, subclass `JobWatcher` from `mcp_server/src/services/watcher.py` rather than hand-rolling a thread/poll loop. It owns threading, backoff-schedule polling, state persistence, and startup resume; a subclass only defines what "poll" and "job finished" mean for its own domain.

- A watcher subclass defines: `backoff_schedule` (a tiered `[(elapsed_seconds_cutoff, interval_seconds), ...]` table), `poll()` (calls the domain function that checks job status, returns `(WatcherPhase, detail_dict)`), `on_completed()` (called once on the COMPLETED transition — e.g. auto-download a result file), and `on_state_change()` (called on every phase change — e.g. write a `WATCHER_COMPLETED`/`WATCHER_FAILED`/`WATCHER_TIMED_OUT` audit event via the capability's own audit logger, matching how a manual action is audited).
- A tool that schedules the job constructs the subclass and calls `.start()` once scheduling actually succeeds (not unconditionally).
- If a later tool call would otherwise redo the watcher's own completed work (e.g. re-download a file the watcher already fetched), check the watcher's persisted state first and return the cached result instead of repeating the external call — see `find_cached_download()` in the same file.
- Wire `YourWatcher.resume_all(state_dir)` into `mcp_server/src/run.py`'s startup coroutine, gated on `capability_registry.is_enabled("<id>")`, so a watcher still running when the server last restarted picks back up.
- State files land at `{state_dir}/{YourWatcherClassName}/instances/{key}.json` (one per watched job) with the recipients beside them at `{state_dir}/{YourWatcherClassName}/recipients.json` - so one capability can hold several watcher classes; `state_dir` is `specifics/<capability_name>/.data/watchers` — give the capability its own dedicated `Path` setting in `mcp_server/src/config.py` for `state_dir`, don't reuse another capability's directory or the generic `log_dir`.
- **Watcher email recipients** (`services/watcher_recipients.py`): each watcher has its own recipient list, stored in `{state_dir}/{WatcherClass}/recipients.json` (beside, not inside, the class's `instances/` record folder, so `resume_all()`/`list_watchers()` globs never read it; written write-then-rename so a crash cannot truncate it). A watcher that emails reads it with `get_recipients(state_dir, type(self).__name__, self.key)` at send time. A capability with a watcher ships **three commands, all with a matching slash command**: `tool_<alias>_addWatcherRecipient` / `removeWatcherRecipient` / `listWatcherRecipients` (`/<id> add_watcher_recipient`, `remove_watcher_recipient`, `list_watcher_recipients`), each taking the watcher's key parts plus `email` (one address; validated by `parse_recipients`), plus a hidden `setWatcherRecipients` (replace whole list) for the Watchers page. Add/remove/list return a result with the full `recipients` list; `listWatchers` results carry `recipients` too.
- **What a watcher emails**: decide per capability and write it in the README's "Email notifications" section. Typical choices: an email on every state change, an hourly "still unresolved" reminder while in an error state (last-alert time persisted in the record's `detail` so a restart does not reset the hour), and - when an address is newly added - one email of the watcher's **last saved status** (never a live poll); the add/set tool's reply must say "Expect an email at ..." only when that mail was actually sent. Mail is best-effort: log and swallow failures, never fail the watcher or the recipient save. Recipients on the watcher win; the config's standing `to` list is only a fallback.
- **Every email** goes through `services/email.py`'s `send_email`, which appends "This is an auto-generated message. Do not reply." to both the plain and HTML parts - do not build a second sender or add your own footer.
- Polling cadence is a `backoff_schedule` of `(elapsed_cutoff_seconds, interval_seconds)` tiers, elapsed measured from the watcher's original start (so a resumed watcher does not restart the fast tier). A typical first tier is `(60, 10)` - every 10 s for the first minute.

## Registering a brand-new capability

Do these in order — each step depends on the last:

1. `mkdir mcp_server/src/capabilities/<name>/` with an `__init__.py`.
2. Write `contract.py`, `domain.py`, `tool.py` per the split above.
3. `<name>/README.md` documenting: which `../../configs/*.json` and `../../secrets/*.env` files it reads, what it owns under its own dot-prefixed folders or `static/` folder (if anything — see "Folder shape at a capability's top level" above), how to toggle it off, and the tool / slash-command / workflow tables. Use `server_manager/README.md` as the template.

   README format (identical in every capability - copy `server_manager/README.md`'s top half):

   1. `# capabilities/<folder>/` title, then a short intro (what it does, how many tools).
   2. `## Tools` - one table, columns **exactly** `Tool | Purpose | Connection`, one row per tool. Tools with a slash command first (definition order), then tools with no command sorted alphabetically; a no-command tool's Purpose says it is internal-only / MCP-only.
   3. `## Slash commands` - one table, columns **exactly** `Tool | Slash command | Parameters`, one row per tool that has a command. Parameters is a `<ul><li>` list that always starts with `system_name` (or that command's own first parameter) - never "None beyond system_name" - each item written `` `name` - required|optional[, default `x`]. Description. ``
   4. `## Typical workflow` - table with columns **exactly** `Sequence | Tool | Explanation` (a manual step uses `*(manual - no tool)*`; fold any "AI-only" note into Explanation, no extra column).
   5. Capability-specific sections after that (configuration, email notifications, ...), never between these three.

   Keep the README tables, `help.json` and the code's `@command`/`@mcp.tool` set in sync whenever a tool is added, renamed or removed.
3b. `<name>/STATIC-GUIDELINES.md` — **mandatory** the moment step 2's `domain.py` creates any dot-prefixed folder or `static/` subfolder: document each one, its file format, and its lifecycle (regenerated vs. hand-maintained, committed vs. gitignored). Any existing capability's `STATIC-GUIDELINES.md` shows the expected level of detail; a `static/<category>/` subfolder also gets its own short `README.md` alongside its content.
4. `<name>/help.json` — same facts as the README's tables, in the small structured shape `/<id> help` renders:

   ```json
   {
     "summary": "One or two sentences - what this capability does.",
     "tools": [
       {"name": "some_tool", "purpose": "...", "connection": "SSH",
        "commands": ["cmd_name"]}
     ],
     "commands": [
       {"name": "cmd_name", "tool": "some_tool", "params": [
         {"name": "system_name", "required": true, "default": null, "description": "..."}
       ]}
     ],
     "workflow": [
       {"sequence": "1", "tool": "some_tool", "ai_only_step": false, "explanation": "..."}
     ]
   }
   ```

   `commands[].name` is the bare sub-command (`"list"`, not `"/server list"`) — the capability id prefix is added at render time. A manual, human-only workflow step uses the literal string `"(manual - no tool)"` for `tool`.

5. Add a toggle entry to both `mcp_server/configs/config_capabilities.json` **and** `config_capabilities.json.example`:

   ```json
   { "<id>": { "enabled": true } }
   ```

   `<id>` is the short id from step 6 (e.g. `server`), not necessarily the folder name.

6. In `<name>/__init__.py`, register the capability's chat-facing id and label — **once, here, nowhere else** (chat_app's suggestion bar and welcome card read the label from mcp_server via `/chat/api/capability-labels`, so nothing to add there):

   ```python
   from src.services import capability_meta

   META = capability_meta.register(folder="<name>", id="<id>", label="<Display Label>")
   ```

   `<id>` is what chat users type as `/<id> ...` and what `PATCH /capabilities/{id}` toggles. Every `@command` in this capability's `tool.py` infers its capability from `META` automatically — no `capability=` argument needed on any of them.

7. In `mcp_server/src/run.py`, follow the existing capabilities' pattern exactly:

   ```python
   from src.capabilities import <name>

   with capability_registry.capturing(mcp, <name>.META.id, label=<name>.META.label):
       from src.capabilities.<name> import tool as <name>_tool
   ```

   The bare `from src.capabilities import <name>` only runs `__init__.py` (cheap, no tools registered yet). Importing `tool` inside `capturing()` is what actually runs the `@mcp.tool()` decorators and lets the capability be disabled/re-enabled live via chat_app's Capabilities page, without a server restart.

8. If the capability wraps a client-readable URI resource (not just a callable tool), have the capability import the resource's `domain.py` — never the reverse — so deleting the capability wrapper leaves the resource untouched. See `mcp_server/src/resources/README.md`.

## Verify before calling it done

- `pytest` from `mcp_server/` — `domain.py`'s pure functions should have unit tests that don't need a live external system (mock the `services/` clients); this run also covers `test_tool_display_labels.py`, so a missing `display_label` fails here rather than silently at runtime.
- Grep the capability for `pending_ai_review`, `ai_instructions`, `needs_ai_review`, `ai_required` and any LLM client import - none may exist. Confirm `tool_<alias>_getAuditLog`/`listWatchers`/`listSystems` are present and that a tool whose result needs explaining sets `ai_explain_result`.
- Start the server (`mcp_server/run.bat`) and confirm the new capability shows up in `GET /capabilities`, and that `/<id> help` in chat_app renders the `help.json` content correctly.
- Sanity-check a result model renders well in chat_app: does it have a `message` field, and does any `list` field share uniform keys so it tables cleanly?
