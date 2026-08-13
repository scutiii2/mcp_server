# SAP AIOps — greenfield scaffold

Two independent Python packages, one MCP tool server and one Flask chat
app, talking over HTTP. This is a starter skeleton, not a finished system —
the Control category (`get_available_sids`, `stop_sap_system`,
`start_sap_system`) is built end-to-end as a faithful, full-fidelity port
of the legacy multi-tier landscape orchestration, so you have a working
pattern to copy for the rest.

## Layout

```
mcp_server/                        MCP tool server (port 8010)
├── pyproject.toml
├── src/mcp_server/
│   ├── run.py                     entrypoint — imports capabilities/*, resources/*, starts uvicorn
│   ├── server.py                  shared FastMCP instance
│   ├── config.py                  settings (config path, host, port)
│   ├── infra/                     shared across both capabilities/ and resources/
│   │   ├── ssh.py                  SSH client + run_command() (bare exec_command, monitoring's style)
│   │   ├── sap_config.py           config loader — SapServerConfig (SSH+HANA+landscape), RfcServerConfig (RFC)
│   │   ├── db.py                   HANA client — DB-API 2.0, mirrors ssh.py's context-manager shape
│   │   ├── rfc.py                  pyrfc.Connection wrapper + shared RfcConnection Protocol — see optional [rfc] extra
│   │   └── email.py                 SMTP notifications — genuinely new, stdlib only, see its docstring
│   ├── capabilities/               Tools — actions the model deliberately invokes
│   │   ├── control/                 get_available_sids, stop/start_sap_system — multi-tier landscape
│   │   │   ├── contract.py
│   │   │   ├── domain.py
│   │   │   └── tool.py
│   │   ├── monitoring/              all 13 monitoring tools
│   │   │   ├── contract.py
│   │   │   ├── domain.py
│   │   │   └── tool.py
│   │   ├── dumps/                   all 3 dump tools — RFC-based (SNAP table), not SSH or HANA SQL
│   │   │   ├── contract.py
│   │   │   ├── domain.py
│   │   │   └── tool.py
│   │   ├── health/                  system health assessment + maintenance mode
│   │   │   ├── contract.py
│   │   │   ├── domain.py
│   │   │   └── tool.py
│   │   ├── jobs/                    all 7 job tools — RFC-based (BAPI_XBP_* + TBTCO)
│   │   │   ├── contract.py
│   │   │   ├── domain.py
│   │   │   └── tool.py
│   │   └── kernel/                  kernel update — Windows-local file dependency, see its docstring
│   │       ├── contract.py
│   │       ├── domain.py
│   │       └── tool.py
│   └── resources/                  Resources — read-only, URI-addressed, browsable data
│       └── job_history/
│           ├── contract.py         Pydantic request/result models
│           ├── domain.py           pure logic — queries TBTCO over HANA directly, no RFC
│           └── resource.py         thin @mcp.resource() wrapper — only place that decorator appears
└── tests/
    ├── test_control_domain.py     domain tests — no SSH, no MCP, no network
    ├── test_monitoring_domain.py  domain tests — run_command mocked with real sapcontrol-shaped CSV
    ├── test_dumps_domain.py       domain tests — fake RFC connection object, no pyrfc needed
    ├── test_health_domain.py      domain tests — run_command mocked + real tmp_path file I/O
    ├── test_jobs_domain.py        domain tests — fake RFC connection object, no pyrfc needed
    ├── test_kernel_domain.py      pure helpers + validation phase — NOT full orchestration, see its docstring
    └── test_job_history_domain.py domain tests — HanaClient mocked, no real DB connection

chat_app/                          Flask chat + capabilities browser (port 5009)
├── pyproject.toml
├── tests/
│   ├── conftest.py                 Flask app/test-client fixtures, resets cooldown state per test
│   ├── test_chat_routes.py         /chat, /api/chat, /api/providers, router mocked
│   ├── test_capabilities_routes.py /capabilities routes, list_tools/call_tool mocked
│   ├── test_llm_providers.py       schema reshaping + availability + cooldown per provider
│   ├── test_router.py              dispatch, availability-gating, cooldown-blocking
│   └── test_cooldown.py            the tracker itself, in isolation
└── src/chat_app/
    ├── run.py                     entrypoint — python -m chat_app.run
    ├── app.py                     create_app() — sets up the PrefixLoader (see its docstring)
    ├── config.py
    ├── services/
    │   ├── mcp_client.py           the only place this process talks to the MCP server
    │   ├── tool_titles.py           friendly display titles for the capabilities page
    │   └── llm/                    one provider per LLM, picked at request time
    │       ├── base.py             ProviderSpec / ChatResult shared interface
    │       ├── openai_provider.py   OpenAI Responses API — function_call / parameters
    │       ├── claude_provider.py   Anthropic Messages API — tool_use / input_schema
    │       ├── sap_ai_hub_provider.py  SAP AI Core proxy — Chat-Completions function-wrapped shape
    │       ├── router.py           availability check + dispatch, only file that imports all three
    │       └── cooldown.py         process-wide rate-limit tracking, shared across requests
    └── pages/                      one self-contained folder per page — routes + its own template/
        ├── chat/
        │   ├── routes.py           /chat page + /api/chat + /api/providers
        │   └── template/
        │       ├── index.html      structure only — links styles.css/script.js via url_for
        │       ├── styles.css
        │       └── script.js
        └── capabilities/
            ├── routes.py           /capabilities — the tool browser
            └── template/
                ├── index.html
                ├── styles.css
                └── script.js
```

## Page structure — `pages/<name>/`

Each page is a self-contained folder: its own `routes.py` (a Flask
Blueprint) and its own `template/` directory holding `index.html`,
`styles.css`, and `script.js` as three separate files rather than one
HTML file with everything inlined. Adding a new page later means adding
one more `pages/<name>/` folder in this same shape, plus a two-line
addition to `app.py` (import the blueprint, add its entry to the
`PrefixLoader`) — nothing else changes.

Two Flask mechanics make this layout work, both handled centrally in
`app.py` rather than repeated per page:

- **Template collision** — two blueprints both naming their template
  `index.html` would collide under Flask's default template loading
  (whichever blueprint registers first "wins" for *every* page's
  `render_template("index.html")` call). `app.py` replaces the app's
  Jinja loader with a `PrefixLoader` keyed by page name, so routes call
  `render_template("chat/index.html")` / `render_template("capabilities/index.html")`
  and can never resolve to the wrong page's file. This was verified by
  actually rendering both templates through a real `PrefixLoader` and
  confirming zero cross-contamination, not just reasoned about.
- **Serving CSS/JS** — Jinja template folders aren't web-servable by
  default. Each blueprint sets `static_folder="template"` (the *same*
  directory Jinja reads from) plus a unique `static_url_path`, so
  `styles.css`/`script.js` become real fetchable URLs via
  `url_for('chat.static', filename='styles.css')` without needing a
  conventional top-level `static/` folder.

## Running it

Each package is independently installable:

```bash
cd mcp_server && pip install -e ".[dev]"
cd ../chat_app && pip install -e ".[dev]"
```

Copy the `.env.example` in each package to `.env` and fill in real values —
both `run.py` entrypoints load their local `.env` automatically via
`python-dotenv` before anything reads a setting, so this is all you need
per package. Required: `SAP_CONFIG_PATH` in `mcp_server/.env`. In
`chat_app/.env`, set at least one of `OPENAI_API_KEY` /
`ANTHROPIC_API_KEY` — the `/chat` page's provider dropdown grays out
whichever one you leave unset rather than failing when picked.

Then start both processes:

```bash
# terminal 1
cd mcp_server && python -m mcp_server.run

# terminal 2
cd chat_app && python -m chat_app.run
```

Open `http://127.0.0.1:5009/capabilities` to browse and test-call every
registered tool directly — no chat, no OpenAI, just the raw tool catalog
and a form per tool generated from its Pydantic schema. Open `/chat` for
the actual assistant.

## Adding a new tool

Follow the pattern in `capabilities/control/` — one self-contained folder
per tool:

1. `mkdir capabilities/<name>/` with an `__init__.py`.
2. **`capabilities/<name>/contract.py`** — Pydantic request/result models.
3. **`capabilities/<name>/domain.py`** — the real logic. Takes typed input,
   returns typed output, imports `infra/` but never `mcp` or `flask`. This
   is what you unit test.
4. **`capabilities/<name>/tool.py`** — a few lines: load config, call the
   domain function, return its result. `@mcp.tool()` appears here and
   nowhere else.
5. Add `from mcp_server.capabilities.<name> import tool as <name>_tool` to
   `run.py`.

Everything a capability needs (its contract, domain logic, and tool
wrapper) lives together in one folder — no jumping between three parallel
top-level directories to see one tool's full picture. Only genuinely
shared code (`infra/ssh.py`, `infra/sap_config.py`) stays outside
`capabilities/`, since every capability uses the same SSH client and
config loader.

Nothing needs to change on the Flask side — `/capabilities` and `/chat`
both pick up new tools automatically via `list_tools()`.

## Tools vs. Resources — and adding a new resource

MCP has two distinct primitives for exposing server capabilities, and
they map to genuinely different use cases:

- **Tools** (`capabilities/`) — actions the model *decides* to invoke,
  with arguments, usually because something needs to happen (stop a
  system) or a specific computed answer is needed.
- **Resources** (`resources/`) — read-only, URI-addressed data a client
  can *browse and read directly* (`sap://job-history/E4G`), without a
  tool-call round trip. Better fit for "just give me the data" cases —
  files, log excerpts, database records — where the model doesn't need
  to reason about arguments first.

`resources/job_history/` is a working example: it queries HANA's `TBTCO`
table directly (bypassing SAP's RFC layer entirely — legitimate for
reporting, not for anything that should go through SAP's own
authorization/locking) via the new `infra/db.py` HANA client, and exposes
the result as `sap://job-history/{sid}`.

Adding a new resource follows the same three-file shape as a tool:

1. `mkdir resources/<name>/` with an `__init__.py`.
2. **`resources/<name>/contract.py`** — Pydantic request/result models.
3. **`resources/<name>/domain.py`** — the real fetch logic. For
   file/log-backed resources, reuse `infra/ssh.py` the same way tools do.
   For database-backed ones, reuse `infra/db.py` (or add a new client
   there for a different database).
4. **`resources/<name>/resource.py`** — a few lines: load config, call
   the domain function, return its result as a string. `@mcp.resource()`
   appears here and nowhere else.
5. Add `from mcp_server.resources.<name> import resource as <name>_resource`
   to `run.py`.

The Flask capabilities browser (`/capabilities`) shows both sections —
Tools with their argument forms, Resources with their URI-template
parameters — pulled live from `list_tools()`/`list_resource_templates()`
respectively. Nothing needs to change there for a new resource either.

**Honest caveat on the exact MCP client/SDK details**: several pieces
here — `@mcp.resource()`'s exact keyword arguments, whether
`list_resource_templates()` is the right client call versus
`list_resources()`, and the response attribute's exact casing
(`resource_templates` vs `resourceTemplates`) — are written to the best
of my knowledge of the MCP spec and FastMCP's documented patterns, but
**not runtime-verified** against your pinned `mcp==1.28.0` in this
sandbox (no network access to install it here). `mcp_client.py` and
`run.py` both have inline comments flagging exactly which lines to check
first if something doesn't work as expected.

## Multi-provider chat, Automatic selection, and rate-limit cooldown

`/chat` shows a provider dropdown: **Automatic** (selected by default),
**ChatGPT**, **Claude**, and **SAP AI Hub**. Each is grayed out per-option
for one of three reasons, all driven live by `GET /api/providers`:

- **No API key** — that provider's env var isn't set. Static, checked via
  each provider's `has_api_key()`. For SAP AI Hub specifically this means
  all four `AICORE_*` vars, not just one — see its own section below.
- **Rate-limited** — a previous call to that provider got a real 429 from
  its SDK (`openai.RateLimitError` / `anthropic.RateLimitError` — SAP AI
  Hub does NOT have this wired up, see below), caught in that provider's
  `run_chat()`, which starts a cooldown in `services/llm/cooldown.py`
  using the server's own `Retry-After` header when present, or a 60s
  default otherwise. The dropdown polls `/api/providers` every 15s and
  re-enables the option automatically once the cooldown expires — no page
  reload needed.
- **Nothing available** (Automatic only) — every real provider is either
  missing a key or cooling down.

**Automatic** (`router.AUTOMATIC_ORDER`, currently
`["openai", "claude", "sap_ai_hub"]`) tries each provider in that order
and dispatches to the first one that's genuinely usable right now — key
present *and* not in cooldown. If ChatGPT hits a rate limit mid-session,
the very next message automatically falls through to Claude with no
action needed from you; if that's also unavailable, `run_chat` raises a
clear "No provider is currently available" error instead of trying and
failing ugly. Every `ChatResult` carries a `provider_id`, so when
Automatic resolves to a specific provider, the chat page shows a small
"Answered by Claude (Automatic)" note — otherwise there'd be no way to
tell which one actually responded. Change `AUTOMATIC_ORDER` in
`router.py` to change the fallback priority.

Each real provider also exposes a **model dropdown** (hidden when
Automatic is selected — see `router.run_chat`'s docstring for why mixing
"pick any provider" with "but insist on this exact model" doesn't make
sense). Model IDs live in `MODELS` at the top of each provider file —
`openai_provider.py`'s three (`gpt-5.6-sol`/`terra`/`luna`) were confirmed
directly against `platform.openai.com/docs/models`; `claude_provider.py`'s
three (`claude-opus-4-8`, `claude-sonnet-5`, `claude-haiku-4-5-20251001`)
against Anthropic's current lineup. Add or remove entries there as models
change — nothing else needs to change to pick up a new one.
`sap_ai_hub_provider.py`'s `MODELS` is different — see below.

### SAP AI Hub — genuinely different from the other two

SAP AI Hub (via `sap-ai-sdk-gen`, SAP AI Core's proxy to OpenAI/Claude/
Gemini/etc.) isn't a drop-in fourth API key. Two structural differences
worth understanding before touching `sap_ai_hub_provider.py`:

1. **Auth is OAuth2 client-credentials, not one key.** `has_api_key()`
   checks all four of `AICORE_CLIENT_ID`, `AICORE_CLIENT_SECRET`,
   `AICORE_AUTH_URL`, `AICORE_BASE_URL` — normally pulled from a BTP
   service key JSON, not typed by hand.
2. **Model availability is tenant-specific.** Every model must already be
   provisioned as a "deployment" in your own BTP AI Core subaccount
   before it's callable — there's no universal model-id list the way
   OpenAI/Anthropic's own public APIs have. `MODELS` is parsed from the
   `SAP_AI_HUB_MODELS` env var (`"model_name:Label,model_name:Label"`)
   instead of hardcoded — edit that env var to match what you've actually
   deployed, not the provider file.

It's also the only provider not required by default — `sap-ai-sdk-gen` is
in `chat_app`'s `[project.optional-dependencies]` under `sap-ai-hub`
(`pip install -e ".[dev,sap-ai-hub]"`), since it's a heavier, SAP-specific
package most setups of this scaffold won't need. The deferred import
inside `run_chat()` means the app runs fine without it installed — this
provider just stays permanently unavailable until both the package and
all four env vars are in place.

**Honest caveat, same spirit as the `title=` and resources caveats
elsewhere in this README**: the exact SDK calling convention
(`gen_ai_hub.proxy.native.openai.chat.completions.create`, OpenAI
Chat-Completions-shaped messages/tools) is written to the best of my
knowledge of SAP's documented "native OpenAI client integration"
pattern, but **not runtime-verified** — no network access to
`pip install sap-ai-sdk-gen` in the sandbox this was built in. Rate-limit
cooldown is deliberately *not* wired up for this provider either, since I
don't know SAP AI Core's actual rate-limit exception type/shape and
guessing wrong risks worse behavior than not guessing at all. Confirm
both against your installed version before trusting this in production —
`sap_ai_hub_provider.py`'s module docstring has the same notes inline.

`cooldown.py`'s in-memory dict is a deliberate exception to the
"no module-level mutable state" rule below — a provider's rate-limit
status is genuinely process-wide (if OpenAI 429s once, it's 429ing every
user of this process), unlike per-user session data. See that file's
docstring for the full reasoning, including the caveat that it won't work
correctly if this ever runs behind multiple worker processes without a
shared cache.

## What this deliberately avoids from the legacy codebase

- No module-level mutable globals (`CACHED_DUMPS`-style state) for
  per-user data. Scope request-specific state per-session on the Flask
  side; keep MCP tools stateless. (Process-wide facts like rate-limit
  cooldowns are a deliberate, documented exception — see above.)
- No duplicated SSH-connect implementations — `infra/ssh.py` is the only
  one.
- No untyped `dict` config with silent `{}` fallback on error —
  `infra/sap_config.py` fails loudly at load time.
- No hand-maintained tool description strings separate from what OpenAI
  and the capabilities page see — one Pydantic schema, one description,
  everywhere.

## Verification practices used while porting

`py_compile` only catches syntax errors — it does NOT catch a function
being imported under a name that doesn't actually exist in the target
module. That gap let a real structural bug through once during this
port: an edit to `monitoring/domain.py` accidentally dropped a function's
`def` line, silently merging its body as dead, unreachable code inside
the *previous* function — syntactically valid, so `py_compile` reported
success, but `debug_raw_process_list_tool` would have called a function
that no longer existed.

Caught by a small AST-based script (not committed as a file here, but
worth keeping around if you continue this work) that, for every file:
walks every `from mcp_server.X import Y` and confirms `Y` is actually a
top-level name in module `X`, and separately checks for duplicate
top-level `def` names in the same file. Run both after any edit that
moves code between functions, not just after adding new files — that's
exactly the kind of edit that produces this failure mode.

## Known gaps in this scaffold

- Only `job_history` is implemented as a resource, and it's the only
  one — no file/log-backed resource example exists yet, even though
  `infra/ssh.py` is ready to support one the same way tools use it.
- `hdbcli` is a runtime dependency (`>=2.19`, unpinned — no known-good
  version was available to pin against, unlike the other dependencies)
  but its actual query behavior against a real HANA instance is
  untested here; only the domain logic is unit-tested with a mocked
  `HanaClient`.
- Control is fully implemented (`get_available_sids`, `stop_sap_system`,
  `start_sap_system`) — multi-tier landscape orchestration (DB → ASCS →
  PAS → additional app servers), idempotency checks, and GREEN/DOWN
  polling all faithfully ported from `sap_operations.py`. One disclosed
  adaptation: the legacy version streamed progress to a polled temp log
  file; this blocks synchronously and returns the accumulated log in one
  response instead, since MCP tool calls are request/response, not a
  background job.
- Monitoring is fully implemented — all 13 tools (`list_sap_systems`,
  `check_work_process_errors`, `get_work_process_breakdown` with its full
  3-tier fallback chain, `debug_raw_process_list`, `get_sap_process_list`,
  `get_sap_process_status`, `get_sap_system_health`, `get_kernel_version`
  with its sapcontrol → disp+work fallback, `check_disk_usage`,
  `find_largest_files`, `check_cpu_usage`, `check_memory_usage`,
  `get_hana_status`). One disclosed fix: the legacy `get_sap_system_health`
  indexed `sap_srv["pashost"]` etc. with no None-check after the SID
  lookup — an unhandled SID would raise a raw `TypeError` there instead of
  a clean error message like every other monitoring tool returns; fixed
  here since it's clearly an oversight, not intended behavior.
- Dumps is fully implemented — `get_abap_dumps_tool`, `analyze_latest_dump_tool`,
  `analyze_abap_dump_tool`. RFC-based (SNAP table via `RFC_READ_TABLE`),
  needs the `[rfc]` optional dependency group (`pyrfc`, which itself
  needs SAP's proprietary NW RFC SDK — not a plain `pip install`). Three
  disclosed bugs found and fixed in the legacy `analyze_latest_dump`: it
  called `Connection(**cfg)` with `Connection` never imported anywhere
  reachable (guaranteed `NameError`), indexed a dict key (`"seqno"`) that
  never existed on that dict (guaranteed `KeyError`), and re-ran
  `analyze_dump_text()` on an already-analyzed result (type mismatch,
  and redundant). The function had never successfully executed once —
  rewritten to do what it clearly intended. One *cosmetic*, non-crashing
  bug (`SEQNO=` always renders blank in `get_abap_dumps_tool`'s report,
  since the display code reads a dict key — `'seqno'` — the data never
  populates) was preserved faithfully rather than silently fixed, since
  it never crashes, unlike the disclosed fixes above.
- Health is fully implemented — `get_system_health_tool`,
  `get_maintenance_status_tool`, `set_maintenance_mode_tool`. The seven
  health-scoring helpers (`_health_icon` through `_health_score`) are
  faithful ports. `get_system_health_tool` is the largest disclosed
  deviation in this whole port so far — not a bug fix, a **completion**:
  the legacy `get_system_health` does real SSH work to gather all eight
  health components (CPU, memory, disk, SAP PAS, SAP ASCS, database,
  connectivity, kernel) and computes an overall status and health score
  from all eight, but its display-formatting code only ever appends the
  header, CPU, and Memory sections to the output — Disk/SAP-PAS/SAP-ASCS/
  Database/Connectivity/Kernel are silently never formatted — and the
  function has **no `return` statement at all** (confirmed via raw byte
  inspection, not a rendering artifact — it falls straight into the next
  tool's `@mcp.tool()` decorator). Every real call would do 6+ SSH
  round-trips and then implicitly return `None`. The six missing sections
  in this port are written fresh, following the exact formatting
  convention the CPU/Memory sections already establish — not ported from
  source that doesn't exist, clearly marked in `domain.py` where the
  legacy source's content ends and the completion begins.
- Jobs is fully implemented — `get_job_failures_tool`, `get_job_log_tool`,
  `reschedule_job_tool`, `get_long_running_jobs_tool`, `get_completed_jobs_tool`,
  `get_longest_completed_jobs_tool`, `get_job_trend_analysis_tool`.
  RFC-based (`BAPI_XBP_*` for failures/log/reschedule, `TBTCO` via
  `RFC_READ_TABLE` for the rest), same `[rfc]` optional dependency group
  as Dumps. `infra/rfc.py`'s `RfcConnection` Protocol is now shared
  between Dumps and Jobs rather than each defining its own copy. Two
  disclosed behavioral notes (neither a crash, so neither silently
  "fixed" without saying so): `get_long_running_jobs`'s actual RFC filter
  is `STATUS <> 'A'` (not-aborted, last 7 days) — broader than its name
  and description ("STATUS='ACTIVE'") suggest, but not wrong, just
  under-documented; and `get_job_trend_analysis`'s legacy tool wrapper
  never checked for an `ERROR` status from the RFC call — only
  `NO_DATA`/`INSUFFICIENT_DATA` — so a real RFC failure would have fallen
  through to formatting a misleading empty-looking report instead of
  showing the actual error. That second one *was* fixed, matching the
  "clean error message" standard every other tool in this port follows.
- Kernel is fully implemented — `apply_kernel_update_tool`. The most
  architecturally unusual tool in this port, and the biggest single
  `domain.py` (500+ lines). Two things it does that every other tool in
  this scaffold avoids, both preserved per the explicit "full fidelity"
  decision for this category:
  1. **It assumes the MCP server process itself runs on Windows with
     local filesystem access** — it shells out to a local `SAPCAR.exe`
     (`subprocess.run`) to extract `.SAR` kernel files staged on a local
     drive, then SFTP-pushes the extracted files to the remote SAP host.
     Every other tool only needs network/SSH access *to* SAP hosts; this
     one needs to physically run on a specific prepared machine. Not
     redesigned to run remotely.
  2. **Two email notifications, now genuinely working for the first
     time.** The legacy code tried `from app import send_email,
     build_kernel_update_email` — neither function exists anywhere in
     the entire legacy codebase (confirmed by searching the whole tree),
     so every call has always raised `ImportError`, been silently
     caught, logged, and continued. This kernel-update tool has never
     actually sent an email, in any run, ever. `infra/email.py` is a
     fresh design (stdlib `smtplib`, no new dependency) against the
     `"email"` section already present in a real `config.json`
     (`smtp_server`, `smtp_port`, `from`, `password`, `to`) — there was
     no original implementation to port from, so the subject
     lines/HTML/wording are new choices, not faithful ports. A failed
     send is logged into the report but never aborts the update,
     matching the legacy code's evident (if never-working) intent.

  One more disclosed inconsistency, preserved rather than silently
  "fixed": `wait_for_green_blocking`'s DB branch connects using the
  default `sapadm` user, not `hanaadm`, unlike `trigger_start_db`'s
  explicit `hanaadm`+bash elsewhere in the same file. Both exist in the
  legacy code as-is. This category also duplicates polling logic
  (wait-for-down/wait-for-green) that `capabilities/control/domain.py`
  already has its own version of — this mirrors a real duplication
  already present in the legacy `sap_operations.py` itself, and was kept
  local rather than refactored into a shared helper, partly to match
  that legacy structure and partly to avoid touching Control's
  already-verified polling code for this pass.
- The other three legacy tool categories (rename,
  conversion, provisioning) haven't been started — see
  `mcp_server_copy/mcp_server.py` for the full list of 47 legacy tools.
  Each needs its own `capabilities/<name>/` (or `resources/<name>/`)
  folder following the same contract/domain/tool pattern.
- No auth on `/capabilities` or `/chat` yet — add the same
  `requires_basic_auth` pattern used in the migrated Flask app before
  exposing this beyond localhost.
- Dependencies (`mcp`, `pydantic`, `paramiko`, `flask`, `openai`) aren't
  installed in the environment this was built in, so everything here is
  syntax-checked but not runtime-verified — run the test suite yourself
  after `pip install -e ".[dev]"`.
