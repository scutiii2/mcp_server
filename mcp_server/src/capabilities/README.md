# src/capabilities/

One folder per tool, self-contained. One capability exists today - see
its own README for what it does:

- `server_manager/` - start/stop/restart/list managed apps (`/server ...`).

## Shape of a capability

Each subfolder holds everything specific to that capability. The folder's
top level is a **closed whitelist** - nothing else is allowed there:

- **`contract.py`** - Pydantic request/result models. The shape a tool
  call takes in and returns.
- **`domain.py`** - the real logic. Typed in, typed out, imports only
  `services/` (never `mcp` or anything MCP-protocol-specific). This is the
  file you unit test, and the only one that needs to know nothing about
  how it's invoked.
- **`tool.py`** - a few lines: load config, call the domain function,
  return its result. `@mcp.tool()` appears here and nowhere else.
- **`help.json`** - see "Add a new capability" step 5c below.
- **`README.md`** - this capability's domain/business logic: what it
  does, how its tools/contract/domain fit together. Never restates this
  file's convention rules - link back here instead.
- **`STATIC-GUIDELINES.md`** - documents this capability's own
  dot-prefixed folders and its `static/` folder (below): what's in each
  one, its file format, and its lifecycle (regenerated vs.
  hand-maintained, committed vs. gitignored). Every capability has at
  least one dot-folder or a `static/` folder today, so this file is
  mandatory, not optional.
- **`__init__.py`** - registers `META` (step 7 below).
- **`utils/`** - any other `.py` file this capability needs (its own
  `__init__.py` too). Nothing non-Python belongs here, except its own
  `README.md`.
- **No runtime state or capability-owned config here.** A capability's
  own state and config live outside `src/`, in
  `mcp_server/specifics/<capability_name>/`: dot-prefixed folders
  (`.cache/`, `.data/`, `.logs/`, `.secrets/`, ...) hold
  **runtime/generated state only** and are always gitignored; a plain
  `configs/` folder holds tracked, capability-owned config. See each
  capability's own `STATIC-GUIDELINES.md` for what it actually uses.
  `__pycache__/` is exempt from this rule (Python controls that name,
  not this convention).
- **`static/`** - curated static reference data that is neither code nor
  runtime state: a knowledge base, policy documents, reference `.txt`
  definitions. Not dot-prefixed - it isn't generated and isn't ephemeral.
  One subfolder per category (`static/knowledge/`, `static/policies/`,
  ...), each with its own `README.md`. Tracking is decided
  per subfolder, not by this rule: some commit their real
  content because it *is* the source; others (e.g. `static/knowledge/`,
  `static/policies/`) gitignore their real content because it's
  deployment-specific, and commit only that `README.md` plus - for JSON
  files only - a `<name>.json.example` sibling documenting the shape. See
  each capability's own `STATIC-GUIDELINES.md` for which applies where.

Nothing outside this list belongs at a capability's top level - a new
runtime/generated file goes in a dot-folder, a new curated static
reference file goes in `static/`, a new Python file goes in `utils/`.

Shared infrastructure (`services/ssh.py`, `services/email.py`,
`services/app_config.py`) stays one level up,
at `src/services/` - every capability reuses the same clients and config
loader rather than each folder inventing its own.

`server_manager/` is a good one to read for all three code files
together: four tools, a domain module that imports only `services/`, and
a contract of typed results.

A different pattern lives at `src/services/extensions.py`: proxied
external tools, connected out to other MCP servers as a client and
re-exposed here under a namespaced name, rather than written by hand in
this repo at all. Reach for a capability when you're wrapping logic
that lives in this codebase; reach for an extension when you're
exposing an MCP server that already exists elsewhere.

## Output formatting

A tool call's return value is a Pydantic model, and FastMCP serializes
that to indented JSON as the wire content - readable to a machine, not
to a person reading chat_app's Chat page or Capabilities page. Neither
page shows that raw JSON: `chat_app/src/services/command_formatting.py`'s
`format_command_result()` renders it as Markdown instead, and both
surfaces that can invoke a tool directly use it -

- **Chat's "/" commands** (`services/commands.py`'s `execute_command()`)
  - the reply bubble is the Markdown rendering, not the JSON (see
  `Chat/script.js`'s `renderMarkdown()`).
- **Capabilities page's "try it" console** (`Capabilities/__index__.py`'s
  `try_tool()`/`read_resource_route()`) - the same Markdown rendering is
  the default view of a result, with a "Show raw JSON" toggle underneath
  for the untouched wire response.

An LLM-routed chat turn (no leading `/`) never goes through this at all -
the model gets the raw JSON tool result and writes its own prose reply,
which is the right place for that path to differ.

`format_command_result()` is generic - it walks whatever JSON object
comes back rather than needing a per-tool-name entry (see its docstring
for why: `tool_titles.py`/`tool_capabilities.py` have both gone stale
that way before). It understands two result shapes, and every contract
in `capabilities/*/contract.py` should fit one of them to get useful
formatting for free:

1. **Flat fields + `message`** - the common case. Scalar fields become
   a bulleted `**Label:** value` line each, a `list[dict]` field (rows
   sharing the same keys) becomes a Markdown table, a `list` of scalars
   becomes a bullet list, and a top-level `message: str` (present on
   nearly every result model in this codebase) is pulled out and shown
   first, as the lead sentence. This is what `server_manager`'s
   contract already does - no changes needed
   to add a new tool here, just include a `message` field like the rest.
2. **`status` + `report`** - for a result that reads better as a
   preformatted, fixed-width block (aligned labels, a title rule) than
   as prose or a table, e.g. a nested `status` object plus a `report: str` built by `domain.py`.
   `report` is rendered as a fenced code
   block so its alignment survives; any nested `dict` field (like
   `status`) is then skipped, since `report` already presents that same
   data in human-readable form and repeating it as a raw field list
   underneath would just show the same numbers twice.

Reach for shape 2 only when a tool's output is genuinely a status
readout worth a fixed layout; shape 1 is the default, and is enough for
nearly everything - a good `message` field is most of what makes a
result read well.

## Form inputs (how Chat renders a tool parameter)

Chat's command form builds each input from the tool's JSON schema, so a
tool param controls its widget with plain schema keys plus two hints set
through `Field(json_schema_extra={...})`:

- `input` - `"text"`, `"textarea"`, `"password"`, `"number"`, `"range"`,
  `"date"` or `"select"`. Optional; without it the form infers a select
  from `enum`/`examples`, a number box from `integer`/`number`, else text.
- `options_url` - a plain path on this server (e.g.
  `"/system/check-capabilities"`) returning the select's options as a JSON
  list of strings, a list of `{"value", "label"}`, or a `{value: label}`
  object. Chat fetches it when it loads the command list. If it fails the
  form falls back to a text box.
- `depends_on` - another param whose value fills a `{placeholder}` in
  `options_url` (e.g. `"/apps/options?kind={kind}"`);
  the select stays disabled until that param has a value and reloads when
  it changes. Chat fetches these through `/chat/api/param-options`, which
  only accepts an `options_url` some command really declares.
- `sets` - `{other_param: option_field}`: choosing an option also fills
  those params from extra fields on the option (so a job's `job_count`
  travels with its name). Pair with `"input": "hidden"` on the filled
  param so it has no row of its own.
- `shows` - `{label: option_field}`: read-only lines under the select,
  taken from the chosen option (e.g. an option's description).
- `initial` - prefill for a text box; `{timestamp}` becomes the current
  time (`YYYYMMDDHHMMSS`).
- `Field(ge=, le=)`, `Literal[...]`, `max_length`, `pattern` become the
  input's min/max, fixed choices, length limit and pattern. `examples`
  stays non-binding (a hand-typed value in a full command still works);
  `enum` is what the server enforces.

## Add a new capability

1. `mkdir capabilities/<name>/` with an `__init__.py`.
2. `capabilities/<name>/contract.py`.
3. `capabilities/<name>/domain.py`.
4. `capabilities/<name>/tool.py`.

   **Tool naming:** `tool_<capabilityAlias>_<taskName>` - three parts split on `_`, so alias and task
   stay camelCase with no underscores (`tool_srv_listApps`). The function name is the MCP tool
   name. Alias example: `srv` (server manager: `tool_srv_startApp`, `tool_srv_listApps`).
   Every capability also exposes tool-only (no `@command`, `meta={"hidden": True}`) `getAuditLog`,
   and `listWatchers` where the capability has watchers.

   **AI metadata:** a tool never calls or instructs an AI. To have an assistant explain a tool's
   result when it runs the tool from a chat prompt, set `"ai_explain_result": True` in the
   `@mcp.tool(meta=...)` dict 
   `ai_agent/src/mcp_upstream.py`'s `tool_description()` appends the
   standard explain-the-result note to that tool's description. There is no `needs_ai_review` or
   `ai_required` metadata anymore, and slash commands never go through an AI agent.
5. `capabilities/<name>/README.md` - what it reads (which
   `../../configs/*.json` files, which `../../.secrets/*.env` files), what (if
   anything) it owns under its own dot-folders, and how to toggle it
   off. Every capability README uses the same three tables under fixed
   headings: `## Tools` (`Tool | Purpose | Connection`; slash-command tools
   first, then no-command tools alphabetically), `## Slash commands`
   (`Tool | Slash command | Parameters`, parameters as a `<ul>` list that always
   includes `system_name`) and `## Typical workflow`
   (`Sequence | Tool | Explanation`); capability-specific sections come after.
   `server_manager/README.md` is the template.
5b. `capabilities/<name>/STATIC-GUIDELINES.md` - if this capability
    creates any dot-prefixed runtime folder (cache, data, sessions, ...)
    or a `static/` folder (knowledge, policies, reference
    docs, ...), document each one here: what's in it, its file format,
    and whether it's regenerated, hand-maintained, or committed. See
    "Shape of a capability" above for the rule this file exists to
    satisfy, and any existing capability's `STATIC-GUIDELINES.md` for
    the expected level of detail.
5c. `capabilities/<name>/help.json` - the same tool/command/workflow
    facts as step 5's README tables, in the small structured shape
    `/<id> help` renders (see `capability_help.py`'s docstring for why
    this is a hand-maintained sibling file rather than parsed out of the
    README itself):

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

    `commands[].name`/`tools[].commands[]` are the bare sub-command
    (`"list"`, not `"/server list"`) - `capability_help.py` prefixes the
    capability id at render time, so nothing here needs to know its own
    slash alias in advance. A workflow step with no real tool (a manual,
    human-only step) uses the literal string `"(manual - no tool)"` for
    `tool`, matching how the README tables already write it.

6. Add a toggle entry to `../../configs/config_capabilities.json` and
   `config_capabilities.json.example`:

   ```json
   { "<id>": { "enabled": true } }
   ```

   (`<id>` is the short id from step 7 below, e.g. `server` - not
   necessarily the folder name.)

7. In `capabilities/<name>/__init__.py`, register this capability's
   chat-facing slash id and display label - **once, here, and nowhere
   else**:

   ```python
   from src.services import capability_meta

   META = capability_meta.register(folder="<name>", id="<id>", label="<Display Label>")
   ```

   `<id>` is what chat users type as `/<id> ...` and what
   `PATCH /capabilities/{id}` toggles - pick something shorter than the
   folder name if the folder name is unwieldy (e.g. `id="server"` for
   `server_manager`), or equal to it if not. See
   `services/capability_meta.py`'s docstring for exactly who reads `META`
   next: `run.py` (step 8), every `@command` in this capability's
   `tool.py` (no `capability=` argument needed on any of them - they
   infer it from here automatically), and chat_app's Capabilities page,
   via `GET /capabilities`'s `label`/`tools` fields.

8. In `run.py`, import the package first (cheap - only runs its
   `__init__.py`, not `tool.py`, so no tools are registered yet) to get
   `META`, then wrap the real import in `capability_registry.capturing()`
   using it, following the existing capabilities there:

   ```python
   from src.capabilities import <name>

   with capability_registry.capturing(mcp, <name>.META.id, label=<name>.META.label):
       from src.capabilities.<name> import tool as <name>_tool
   ```

   Importing `tool` is what runs its `@mcp.tool()` decorators and
   registers them; `capturing()` records exactly what got registered so
   the capability can be disabled - and, unlike the old "skip the
   import" mechanism, re-enabled live - later. See
   `services/README.md`'s `capability_registry.py` entry for how toggling
   actually works, and `capability_routes.py` for the
   `PATCH /capabilities/{name}` route chat_app's Capabilities page
   calls to do it.

If the new capability wraps a resource (a client-readable URI, not just
a model-callable tool - see `src/resources/README.md`), have the
capability import the resource's `domain.py`, not the other way around:
the resource owns the logic, and the capability wrapper stays additive
so deleting it leaves the resource untouched. No capability in this
checkout does this today (see `src/resources/README.md` for why there's
no worked example to point at right now) - this is the pattern to follow
the first time one needs to.
