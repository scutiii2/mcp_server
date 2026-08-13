# MCP server + chat app — scaffold

Two independent Python packages, one MCP tool server and one Flask chat
app, talking over HTTP.

**This is a general-purpose scaffold with zero capabilities registered.**
What's here is the structure, not the features: the MCP server wiring,
shared infrastructure (SSH, SMTP, a durable request store, a config
loader), the Flask page layout, and multi-provider LLM routing with
automatic fallback. Everything domain-specific has been removed, so
nothing below assumes what you're building. Start with "Adding a new
tool".

Because nothing is registered, `/capabilities` renders an empty catalog
and `/chat` runs with an empty tool list — both work, they just have
nothing to show yet.

## Layout

```
mcp_server/                        MCP tool server (port 8010)
├── pyproject.toml
├── .env.example
├── config.json.example            currently only an "email" section
├── src/mcp_server/
│   ├── run.py                     entrypoint — loads .env, prints a startup banner, starts uvicorn
│   ├── server.py                  shared FastMCP instance — rename it here
│   ├── config.py                  env-var settings (config path, host, port, DB path, public URL)
│   ├── infra/                     shared across both capabilities/ and resources/
│   │   ├── app_config.py           JSON config loader — resolves ${VAR} secrets, fails loudly
│   │   ├── ssh.py                  SSH client + run_command() + two SFTP helpers
│   │   ├── email.py                SMTP notifications — stdlib only
│   │   └── pending_requests.py     SQLite store for approval-gated / resumable requests
│   ├── capabilities/              Tools — actions the model deliberately invokes
│   │   └── __init__.py             empty; the per-capability pattern is in its docstring
│   └── resources/                 Resources — read-only, URI-addressed, browsable data
│       └── __init__.py             empty
└── tests/
    ├── test_app_config.py        mostly asserts on the *errors* — the point is failing loudly
    ├── test_email.py             smtplib mocked; asserts what would be sent, and to whom
    └── test_pending_requests.py  real tmp_path SQLite file, no mocking — pure stdlib

chat_app/                          Flask chat + capabilities browser (port 5009)
├── pyproject.toml
├── .env.example
├── tests/
│   ├── conftest.py                 Flask app/test-client fixtures, resets cooldown state per test
│   ├── test_chat_routes.py         /chat, /api/chat, /api/providers, router mocked
│   ├── test_capabilities_routes.py /capabilities routes, list_tools/call_tool mocked
│   ├── test_llm_providers.py       schema reshaping + availability + cooldown per provider
│   ├── test_router.py              dispatch, availability-gating, cooldown-blocking, AUTOMATIC_ORDER exclusion
│   ├── test_tool_titles.py         the title_for() override table + auto-generated fallback
│   └── test_cooldown.py            the tracker itself, in isolation
└── src/chat_app/
    ├── run.py                     entrypoint — python -m chat_app.run
    ├── app.py                     create_app() — sets up the PrefixLoader (see its docstring)
    ├── config.py
    ├── services/
    │   ├── mcp_client.py           the only place this process talks to the MCP server
    │   ├── tool_titles.py          friendly display titles for the capabilities page
    │   └── llm/                   one provider per LLM, picked at request time
    │       ├── base.py             ProviderSpec / ChatResult / ModelOption + the shared SYSTEM_PROMPT
    │       ├── openai_provider.py   OpenAI Responses API — function_call / parameters
    │       ├── claude_provider.py   Anthropic Messages API — tool_use / input_schema
    │       ├── ollama_provider.py   local Ollama via its OpenAI-compatible endpoint, manual-select only
    │       ├── router.py            availability check + dispatch, only file that imports all three providers
    │       └── cooldown.py          process-wide rate-limit tracking, shared across requests
    └── pages/                     one self-contained folder per page — routes + its own template/
        ├── chat/
        │   ├── routes.py           /chat page + /api/chat + /api/providers
        │   └── template/
        │       ├── index.html      structure — links styles.css/script.js, loads marked.js + DOMPurify from cdnjs
        │       ├── styles.css      left-rail message layout extending /capabilities' badge palette
        │       └── script.js       markdown rendering, loading state, try/catch around fetch()
        └── capabilities/
            ├── routes.py           /capabilities — the tool + resource browser
            └── template/
                ├── index.html
                ├── styles.css
                └── script.js
```

## Making it yours

Four places carry the assistant's identity. Nothing else needs to change
to rebrand this:

- **`mcp_server/server.py`** — the FastMCP `name=` and `instructions=`,
  which are what an MCP client sees before it looks at a single tool.
- **`chat_app/services/llm/base.py`** — `SYSTEM_PROMPT`, shared by all
  three providers. It lives there rather than in each provider file
  because it describes the assistant, not the wire format; three copies
  of the same paragraph is three places to forget when you change the
  assistant's job.
- **`chat_app/pages/chat/template/index.html`** — the page `<title>` and
  the input placeholder.
- **`config.json`** — whatever per-deployment data your capabilities need
  (see "Configuration" below).

## Running it

Each package is independently installable:

```bash
cd mcp_server && pip install -e ".[dev]"
```

```bash
cd chat_app && pip install -e ".[dev]"
```

Copy the `.env.example` in each package to `.env` and fill in real values —
both `run.py` entrypoints load their local `.env` automatically via
`python-dotenv` before anything reads a setting, so this is all you need
per package. In `chat_app/.env`, set at least one of `OPENAI_API_KEY` /
`ANTHROPIC_API_KEY` — the `/chat` page's provider dropdown grays out
whichever one you leave unset rather than failing when picked.

Then start both processes:

```bash
cd mcp_server && python -m mcp_server.run
```

```bash
cd chat_app && python -m chat_app.run
```

Open `http://127.0.0.1:5009/capabilities` to browse and test-call every
registered tool directly — no chat, no LLM, just the raw tool catalog and
a form per tool generated from its Pydantic schema. Open `/chat` for the
actual assistant.

## Configuration — three kinds, deliberately separate

- **`config.py` in each package** — process settings read from
  environment variables: bind host/port, where the config file lives,
  which model to default to. Small, flat, always present. Set them in
  `.env`.
- **`mcp_server`'s JSON config file** — structured per-deployment data
  read via `infra/app_config.py` from the path in `CONFIG_PATH`: host
  inventories, ports, addresses, recipient lists. Too nested to be
  comfortable as env vars. See `config.json.example`; `config.json`
  itself is gitignored.
- **the environment** — the actual secret *values*. The JSON file only
  refers to them by name.

### Secrets are named in `config.json`, never stored in it

Structure and secrets want opposite treatment: structure benefits from
being versioned, diffed and reviewed; secrets should never be written
down next to it. Mixing both into one file is what makes a config file
radioactive — you can't share it, commit it, or paste it into an issue
without leaking something.

So any string in the config file may contain `${VAR}`, replaced at load
time with that environment variable's value:

```json
"password": "${SMTP_PASSWORD}"
```

`config.json` therefore holds no secrets and stays safe to diff and
share, while the values live wherever suits the deployment — `.env` in
development, or injected by the service manager, container runtime, or a
secrets manager in production. Changing that backend later means changing
how the environment gets populated: not this file's format, and not any
domain code.

Note this is about *separating* secrets from structure, not about `.env`
being safer than JSON — it isn't. Both are plaintext files with the same
permissions, read by the same process. What reduces exposure is keeping
secrets out of version control (already handled — `.gitignore` covers
both, and only `.example` files are tracked), restricting file
permissions to your own account, and eventually keeping the values
somewhere encrypted at rest. The `${VAR}` indirection is what makes that
last step a drop-in change instead of a rewrite.

Details worth knowing:

- Resolution walks the whole structure — nested objects and lists
  included — so any section added later gets it for free.
- An unset **or empty** variable is a hard failure at load time. Empty is
  treated as unset because `SMTP_PASSWORD=` left blank in `.env` is the
  common mistake, and a blank password otherwise fails much later at SMTP
  login with a far less obvious message. Write a literal `""` in the JSON
  if empty is genuinely intended.
- `$$` escapes a literal `$`, so `$${VAR}` survives as the text `${VAR}`
  (same convention as docker-compose). Without that there'd be no way to
  store a string that genuinely contains `${...}` — a sharp edge this
  project's own `config.json.example` hit while being written.

`app_config.py` fails loudly throughout. A missing file, unparseable
JSON, a missing required key, or an unresolvable `${VAR}` all raise at
load time, naming the file and the exact key — rather than returning `{}`
or a blank string and letting a capability fail much later deep inside
domain logic. The convention for which exception: `KeyError` when
something required is absent, `ValueError` when it's present but
unusable.

Add one loader function per config section as capabilities need them,
following `load_email_config`: read the section, validate what's
required, return a frozen dataclass. Domain code should take that
dataclass, never a raw dict — a typo in `config.json` is then caught in
one place instead of at every call site.

## Adding a new tool

One self-contained folder per capability:

1. `mkdir capabilities/<name>/` with an `__init__.py`.
2. **`capabilities/<name>/contract.py`** — Pydantic request/result models.
3. **`capabilities/<name>/domain.py`** — the real logic. Takes typed input,
   returns typed output, imports `infra/` but never `mcp` or `flask`. This
   is what you unit test.
4. **`capabilities/<name>/tool.py`** — a few lines: load config, call the
   domain function, return its result. `@mcp.tool()` appears here and
   nowhere else.
5. Add `from mcp_server.capabilities.<name> import tool as <name>_tool` to
   `run.py`, where a comment marks the (currently empty) import block.
   Import order there is the order tools appear in `list_tools()`.

Everything a capability needs (its contract, domain logic, and tool
wrapper) lives together in one folder — no jumping between three parallel
top-level directories to see one tool's full picture. Only genuinely
shared code (`infra/`) stays outside `capabilities/`.

The payoff of keeping `domain.py` free of `mcp` imports is that its tests
need no server, no network, and no MCP SDK — they call a plain function
with plain arguments. `tool.py` stays thin enough that there's little
left in it to test.

Nothing needs to change on the Flask side — `/capabilities` and `/chat`
both pick up new tools automatically via `list_tools()`. Optionally add a
display title to `_OVERRIDES` in `chat_app/services/tool_titles.py`; the
automatic fallback just title-cases the name, which mangles acronyms
(`get_cpu_usage_tool` → "Get Cpu Usage").

## Tools vs. Resources — and adding a new resource

MCP has two distinct primitives for exposing server capabilities, and
they map to genuinely different use cases:

- **Tools** (`capabilities/`) — actions the model *decides* to invoke,
  with arguments, usually because something needs to happen (restart a
  service) or a specific computed answer is needed.
- **Resources** (`resources/`) — read-only, URI-addressed data a client
  can *browse and read directly* (`logs://recent/web-1`), without a
  tool-call round trip. Better fit for "just give me the data" cases —
  files, log excerpts, database records — where the model doesn't need
  to reason about arguments first.

Adding a resource follows the same shape as a tool:

1. `mkdir resources/<name>/` with an `__init__.py`.
2. **`resources/<name>/contract.py`** — Pydantic request/result models.
3. **`resources/<name>/domain.py`** — the real fetch logic. For
   file/log-backed resources, reuse `infra/ssh.py` the same way tools do.
   For database-backed ones, add a client under `infra/`.
4. **`resources/<name>/resource.py`** — a few lines: load config, call
   the domain function, return its result as a string. `@mcp.resource()`
   appears here and nowhere else.
5. Add `from mcp_server.resources.<name> import resource as <name>_resource`
   to `run.py`.

The Flask capabilities browser (`/capabilities`) shows both sections —
Tools with their argument forms, Resources with their URI-template
parameters — pulled live from `list_tools()`/`list_resource_templates()`
respectively. Nothing needs to change there for a new resource either.

**Honest caveat on the exact MCP client/SDK details**: `@mcp.resource()`'s
exact keyword arguments, whether `list_resource_templates()` is the right
client call versus `list_resources()`, and the response attribute's exact
casing (`resource_templates` vs `resourceTemplates`) are written to the
best of my knowledge of the MCP spec and FastMCP's documented patterns,
but are **not runtime-verified** against the pinned `mcp==1.28.0` — there
is no registered resource to exercise them against yet. `mcp_client.py`
and `run.py` both have inline comments flagging exactly which lines to
check first. `run.py`'s startup banner already falls back to `"unknown"`
for the resource count rather than crashing if neither call works.

## Multi-provider chat, Automatic selection, and rate-limit cooldown

`/chat` shows a provider dropdown: **Automatic** (selected by default),
**ChatGPT**, **Claude**, and **Local (Ollama)**. Each is grayed out
per-option for one of three reasons, all driven live by
`GET /api/providers`:

- **No API key** — that provider's env var isn't set. Static, checked via
  each provider's `has_api_key()`. Ollama has no equivalent at all —
  `has_api_key()` is unconditionally `True` there, since a local Ollama
  instance has no auth by default; see its own section below for what
  "available" actually means for it.
- **Rate-limited** — a previous call to that provider got a real 429 from
  its SDK (`openai.RateLimitError` / `anthropic.RateLimitError` — Ollama
  does NOT have this wired up, see its own section), caught in that
  provider's `run_chat()`, which starts a cooldown in
  `services/llm/cooldown.py` using the server's own `Retry-After` header
  when present, or a 60s default otherwise. The dropdown polls
  `/api/providers` every 15s and re-enables the option automatically once
  the cooldown expires — no page reload needed.
- **Nothing available** (Automatic only) — every provider *in
  `AUTOMATIC_ORDER`* is either missing a key or cooling down. Note this
  is deliberately NOT "every registered provider" — see Ollama's section
  below for why that distinction matters and a real bug it exposed.

**Automatic** (`router.AUTOMATIC_ORDER`, currently
`["openai", "claude"]` — Ollama is deliberately NOT in this list, see its
own section below) tries each provider in that order and dispatches to
the first one that's genuinely usable right now — key present *and* not
in cooldown. If ChatGPT hits a rate limit mid-session, the very next
message automatically falls through to Claude with no action needed from
you; if that's also unavailable, `run_chat` raises a clear "No provider
is currently available" error instead of trying and failing ugly. Every
`ChatResult` carries a `provider_id`, so when Automatic resolves to a
specific provider, the chat page shows a small "Answered by Claude
(Automatic)" note — otherwise there'd be no way to tell which one
actually responded. Change `AUTOMATIC_ORDER` in `router.py` to change the
fallback priority.

Each real provider also exposes a **model dropdown** (hidden when
Automatic is selected — see `router.run_chat`'s docstring for why mixing
"pick any provider" with "but insist on this exact model" doesn't make
sense). Model IDs live in `MODELS` at the top of each provider file —
`openai_provider.py`'s three (`gpt-5.6-sol`/`terra`/`luna`),
`claude_provider.py`'s three (`claude-opus-4-8`, `claude-sonnet-5`,
`claude-haiku-4-5-20251001`). Add or remove entries there as models
change — nothing else needs to change to pick up a new one.
`ollama_provider.py`'s `MODELS` is different — see below.

Adding a fourth provider means writing one module that exports a
`ProviderSpec`, then registering it in `router.py`'s `_PROVIDERS` — and
deciding separately whether it belongs in `AUTOMATIC_ORDER`. Nothing
outside `services/llm/` knows how many providers exist.

`cooldown.py`'s in-memory dict is a deliberate exception to the
"no module-level mutable state" rule below — a provider's rate-limit
status is genuinely process-wide (if OpenAI 429s once, it's 429ing every
user of this process), unlike per-user session data. See that file's
docstring for the full reasoning, including the caveat that it won't work
correctly if this ever runs behind multiple worker processes without a
shared cache.

### Local (Ollama) — manual-select only, and two real bugs found building it

`ollama_provider.py` talks to a local (or LAN) Ollama instance via its
OpenAI Chat-Completions-compatible endpoint (`/v1/chat/completions`),
reusing the `openai` package already in `chat_app`'s dependencies rather
than adding a separate SDK. Deliberately the OLDER Chat-Completions shape,
not `openai_provider.py`'s newer Responses API shape — Ollama's own docs
describe `/v1/responses` support as still preliminary, while
Chat-Completions (including tool calling) is the mature, long-documented
path.

No API key concept at all — Ollama has no auth by default, so
`has_api_key()`/`is_available()` are unconditionally `True`. That also
means, unlike every other provider, there's no live reachability check:
an unreachable Ollama host (wrong `OLLAMA_BASE_URL`, LAN down, box off)
shows as "available" in the dropdown and only surfaces as an error at
actual chat time, the same way a technically-present-but-broken API key
would for any other provider.

**Two config knobs, both env vars, neither obvious:**

- `OLLAMA_BASE_URL` — point this at your Ollama host's actual LAN
  address, NOT `localhost`, whenever `chat_app` and Ollama run on
  different machines (e.g. Ollama on a NAS/homelab box). Ollama itself
  also binds to `127.0.0.1` only by default — it needs
  `OLLAMA_HOST=0.0.0.0` (or equivalent) set on the Ollama side too, or
  no amount of correct config on the `chat_app` side will reach it.
- `OLLAMA_MODELS` — parsed from env rather than hardcoded, as
  `"model_id=Label,model_id=Label"`, using `=` as the separator on
  purpose. That's a fix for a real bug found while testing this provider:
  Ollama model IDs already contain a colon themselves (the `name:tag`
  format, e.g. `qwen2.5:3b`), so using `:` as the id/label separator too
  made `qwen2.5:3b:My Label` genuinely ambiguous — it silently truncated
  the id to `qwen2.5`, losing the tag, which then 404'd against Ollama
  since `qwen2.5` alone was never a pulled model. Covered by a dedicated
  regression test (`test_ollama_models_parsed_preserves_the_tag_colon_in_model_id`)
  so this can't quietly come back.

**Deliberately excluded from `AUTOMATIC_ORDER`.** Ollama's own template
for the default model (`llama3.2:1b`) does have genuine tool-calling
support — that part isn't guesswork — but every independent guide on
Ollama tool-calling agrees small models are the least reliable at
producing well-formed `tool_calls` JSON, and most already call 3B
unreliable for production use; 1B (the default) and 3B (a common
step-up, e.g. `qwen2.5:3b`) are both below or at that line. Manual-select
only, so a flaky local model can never silently become what answers a
real question under "Automatic."

**That exclusion exposed a second real bug**, in `router.py` itself, not
`ollama_provider.py`: `list_providers()` used to compute whether
"Automatic" should show as available from *every registered provider*,
not just the ones `_pick_automatic()` actually tries. That distinction
was invisible before — the original providers were both "registered" and
"in `AUTOMATIC_ORDER`," the same set. Ollama is registered (so it's
manually selectable) but excluded from `AUTOMATIC_ORDER` on purpose, and
is always `is_available() == True` — so without the fix, "Automatic"
would have claimed to be available the moment Ollama existed, even with
zero real providers configured, then failed anyway the instant it was
actually picked. Fixed by computing Automatic's availability from
`AUTOMATIC_ORDER` specifically; covered by
`test_list_providers_automatic_ignores_providers_outside_automatic_order`.

No rate-limit cooldown wiring here — local inference doesn't 429 the way
a cloud API does.

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
  and can never resolve to the wrong page's file.
- **Serving CSS/JS** — Jinja template folders aren't web-servable by
  default. Each blueprint sets `static_folder="template"` (the *same*
  directory Jinja reads from) plus a unique `static_url_path`, so
  `styles.css`/`script.js` become real fetchable URLs via
  `url_for('chat.static', filename='styles.css')` without needing a
  conventional top-level `static/` folder.

### Chat page: markdown rendering, loading state, and an external dependency

`pages/chat/template/` is a real message layout rather than a plain-text
log, extending `/capabilities`' existing color language (blue =
tool/action, green = resource/data) as a left-edge rail per message role.

**Assistant responses render as real markdown**, not raw text. `script.js`
loads [`marked`](https://marked.js.org/) and
[`DOMPurify`](https://github.com/cure53/DOMPurify) from cdnjs (pinned
versions, see `index.html`) and does
`DOMPurify.sanitize(marked.parse(text))` before setting `innerHTML`.
**The `DOMPurify` step is not optional polish** — `marked`'s own docs
say explicitly that it does not sanitize its own output, and this is
LLM-generated text landing in `innerHTML`; skipping it would be a live
XSS vector. `renderMarkdown()` falls back to plain `.textContent` if
either script failed to load (offline, CDN blocked, etc.) rather than
throwing. User and system messages are still rendered as plain text on
purpose (never run through `marked`) — there's no reason to interpret
what you typed, or a short system notice, as markdown.

**A real loading state.** The input and Send button disable during a
request (also prevents a double-send), a message rotates through a small
pool of phrases (`THINKING_MESSAGES` in `script.js`) every 3s so a long
wait doesn't look frozen, and after 15s it switches to an explicit "still
working — this can take longer with local models" note. `send()` wraps
`fetch()` in `try`/`catch`, so a network-level failure or non-2xx
response surfaces as a clear `⚠️ Request failed: ...` message instead of
hanging indistinguishably from "still thinking"; a normal provider-level
error (missing key, rate limit, a model 404 from Ollama) still comes back
as a `200` + `❌ ...` response string.

## Design rules this scaffold holds to

- No module-level mutable globals for per-user data. Scope
  request-specific state per-session on the Flask side; keep MCP tools
  stateless. (Process-wide facts like rate-limit cooldowns are a
  deliberate, documented exception — see above.)
- One SSH implementation — `infra/ssh.py`, not one per caller.
- No untyped `dict` config with a silent `{}` fallback on error —
  `infra/app_config.py` fails loudly at load time.
- No hand-maintained tool description strings separate from what the LLM
  and the capabilities page see — one Pydantic schema, one description,
  everywhere.
- Domain logic never imports `mcp` or `flask`, so it stays testable
  without either.

## Testing

```bash
cd mcp_server && python -m pytest tests -q
```

```bash
cd chat_app && python -m pytest tests -q
```

97 tests, all passing, none touching the network or a real MCP server.
Two patterns in here are worth knowing before you add more:

- **Patching a provider's `run_chat`** — patch it on the `ProviderSpec`
  (`router._PROVIDERS["claude"].run_chat`), not on the module
  (`claude_provider.run_chat`). Each provider builds its `PROVIDER =
  ProviderSpec(run_chat=run_chat, ...)` at import time, so the spec holds
  a direct reference to the original function; rebinding the module
  attribute afterwards leaves that reference untouched and the test sails
  past the mock into a real API call. `test_router.py`'s `_patch_run_chat`
  helper exists for exactly this.
- **`browse()` needs both patches** — it calls `_serialize_tools()` and
  `_serialize_resources()` inside the same try block, so patching only
  one leaves the other making a real network call, which the except
  clause catches and silently blanks *both* sections.

`py_compile` only catches syntax errors — it does NOT catch a function
being imported under a name that doesn't actually exist in the target
module. A cheap AST check covers that gap: for every file, walk each
`from mcp_server.X import Y` and confirm `Y` is a top-level name in
module `X`, and separately check for duplicate top-level `def` names in
the same file. Worth running after any edit that moves code between
functions, since that's what produces the failure mode.

## Known gaps

- **Nothing is registered.** No tool, no resource. `infra/ssh.py`,
  `infra/email.py`, and `infra/pending_requests.py` are all working and
  tested, but nothing calls them yet — so `paramiko` is a dependency
  whose behavior against a real host is unexercised here.
- **No auth on `/capabilities` or `/chat`.** Both let anyone reachable on
  the network call any registered MCP tool with arbitrary arguments. Add
  auth before exposing this beyond localhost — this matters more the
  moment the first real tool lands.
- The MCP resource-primitive details are unverified against the installed
  SDK — see the caveat in "Tools vs. Resources" above.
- `config.py`'s `pending_requests_path` and `public_base_url` support the
  emailed-approval-link pattern `infra/pending_requests.py` was built
  for. That pattern needs one more piece nothing here provides yet: an
  HTTP route to receive the approval click. Mount it on the Starlette app
  `mcp.streamable_http_app()` returns rather than making it an
  `@mcp.tool()` — a tool could be called directly by anyone in a chat
  session, which defeats the point of requiring the emailed link. Have
  the GET only render a confirmation page and the POST do the work;
  corporate mail scanners pre-fetch links, and a side-effecting GET would
  let a scanner silently approve things.
