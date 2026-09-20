# Chat App, AI Agent & MCP Server — System Overview Documentation

**Version:** 2.0 (reflects live code)
**Last Updated:** September 7, 2026
**Scope:** `chat_app/`, `ai_agent/`, and `mcp_server/` — how the three services are built and how they talk to each other. The `ai_agent` layer's own design rationale lives in [`docs/superpowers/specs/2026-09-07-ai-agent-mcp-layer-design.md`](superpowers/specs/2026-09-07-ai-agent-mcp-layer-design.md).

---

## 1. Executive Summary

This repository holds three independent services:

- **`chat_app`** — a Flask web application: an invite-only account system with role/permission-based authorization, a network-security pipeline, an LLM chat interface, and a set of admin/ops pages (Capabilities browser, Approvals inbox, Logs viewer).
- **`ai_agent`** — a standalone MCP agent, hard-pinned to one LLM provider+model per instance (two instances run today: `claude-agent` and `openai-agent`), sitting between `chat_app` and `mcp_server`. It owns the LLM tool-calling loop that used to live inside `chat_app`.
- **`mcp_server`** — a general-purpose MCP (Model Context Protocol) tool server: model-callable capabilities, a human-approval gate for irreversible actions, and a proxy that re-exposes other MCP servers' tools as its own.

Each is a separate installable Python package, run as a separate process. `chat_app` and each `ai_agent` instance communicate over MCP's streamable-HTTP transport; each `ai_agent` instance holds its own persistent MCP connection to `mcp_server` rather than reconnecting per call. `chat_app` also still talks to `mcp_server` directly, over the same transport plus a handful of plain HTTP routes, for everything that isn't the LLM Q&A path (slash commands, extension/capability admin, approvals). Nothing in `mcp_server` imports from `chat_app`, `ai_agent`, or vice versa.

Ollama (local-model) support existed in `chat_app` before this architecture and was retired rather than ported into `ai_agent` — see the design doc's "Problem"/"Goal" sections for why.

---

## 2. High-Level Architecture

```
Browser
  │  HTTPS
  ▼
chat_app  (Flask, :5000)
  ├─ Auth / Admin / Account / Overview / Logs / Sample   — account & platform pages
  ├─ Chat page            — LLM conversations via ai_agent, "/" slash commands via mcp_server
  ├─ Capabilities page    — live tool/resource browser + "try it" console
  └─ Approvals page       — pending approval inbox
        │
        │  MCP: ask / status / cancel
        ├──────────────────────► ai_agent (claude-agent, :9100) ──┐
        │                                                          │
        ├──────────────────────► ai_agent (openai-agent, :9101) ──┼──┐
        │                                                          │  │
        │  MCP streamable HTTP  (POST /mcp)                        │  │
        │  + plain HTTP routes  (/approvals, /extensions,          │  │
        │    /commands, /capabilities)                             │  │
        ▼                                                          ▼  ▼
mcp_server  (FastMCP, :8010)  ◄─────── persistent MCP connection, one per agent instance
  ├─ capabilities/   — server_manager
  ├─ resources/      — client-readable URIs (none registered in this checkout)
  ├─ infra/          — SSH, RFC-adjacent config, email, approvals, extension proxying
        │
        ├─ SSH  ──────────────▶  Managed hosts
        └─ SMTP       ──────────────▶  Outbound mail (approval-request emails, SUM alerts)
```

Each service loads its own `src/secrets/*.env` (gitignored credentials, `ai_agent`'s under `ai_agent/secrets/`) and `src/configs/*.json` (mostly-committed structure) once at boot, independently of the others.

---

## 3. `chat_app`

A Flask app template (internally named **AuthTemplate**) that merges account/security infrastructure with an LLM chat surface.

### 3.1 Pages (`src/pages/`)

One folder per page, each a Flask blueprint auto-discovered at boot (`register_pages()`); URL prefix is the lowercased folder name, with `Overview` mapped to `/`. Every page can declare `PAGE_PERMISSION` (gates visibility/access) and an optional `PAGE_DESCRIPTION`.

| Page | Purpose |
| --- | --- |
| `Auth` | Merged login/registration/logout flow |
| `Overview` | Post-login landing page / page picker |
| `Admin` | Role/permission/account administration, invite generation |
| `Account` | Self-service profile view/edit |
| `Logs` | Server and per-account activity/error log viewer |
| `Sample` | Minimal example page, kept as a template for new pages |
| `Chat` | LLM conversation UI, agent + extension selection, per-user history |
| `Capabilities` | Live MCP tool/resource browser with a "try it" console |
| `Approvals` | Monitor and act on pending approval requests |

### 3.2 Services (`src/services/`)

Route handlers stay thin; policy/DB logic lives here.

- **`security/`** — the network-security pipeline: `ip_filter.py` (allow/deny + geofencing), `rate_limit.py` (DB-backed brute-force lockout), `headers.py` (CSP/HSTS/force-HTTPS), `fingerprint.py` (device identification on login), `cross_site.py` (`Sec-Fetch-Site`/Origin check standing in for CSRF on exempted routes), `pipeline.py` (wires the standing checks into `before_request`/`after_request`).
- **`llm/`** — just `settings.py` now (`mcp_server_url`, `chats_db_path`). Provider selection, the tool-calling loop, and Ollama support all moved to the standalone `ai_agent/` project (§4 below).
- `agent_registry.py` — the configured `ai_agent` instances the Chat page's dropdown can send questions to, read from `src/configs/config_agents.json`.
- `ai_agent_client.py` — the MCP client `chat_api()`/`providers_api()`/`cancel_chat_api()` use to call a configured agent's `ask`/`status`/`cancel` tools; one connection per call, same pattern as `mcp_client.py` below.
- `mcp_client.py` — this process's connection to `mcp_server` for everything except the LLM Q&A path: slash commands and admin/extension/capability management.
- `auth_service.py`, `authz.py`, `otp_service.py`, `email_service.py`, `admin_service.py`, `log_service.py` — account lifecycle, permission checks, invite emails, admin CRUD, and activity/error logging.

### 3.3 Data & Config

- `src/models/` — SQLAlchemy models, backed by `app.db` (SQLite by default, or `DATABASE_URL`).
- `src/data/` — chat history (`chats.db`), kept apart from `app.db`.
- `src/secrets/*.env` — Flask `SECRET_KEY`, DB URL, bootstrap admin credentials, SMTP, and `MCP_SERVER_URL`. LLM API keys and model choice live in each `ai_agent` instance's own secrets instead.
- `src/configs/*.json` — `config_agents.json` (the configured `ai_agent` instances), and per-stage tuning for the security pipeline.

---

## 4. `ai_agent`

A standalone MCP agent, hard-pinned to one LLM provider+model per instance, sitting between `chat_app` and `mcp_server`. Two instances run today (anthropic on `:9100`, openai on `:9101`) from the same `ai_agent/run.bat`, one instance per process — picking a provider/model is an env-var choice at process startup (`AI_AGENT_PROVIDER`/`AI_AGENT_PORT`/`AI_AGENT_MODEL`), not a per-request one.

### 4.1 Code layout (`src/`)

- `server.py` — FastMCP entry point; exposes `ask` (runs the 6-round tool-calling loop against `mcp_server`), `status` (live provider availability), and `cancel` (cooperative mid-turn cancellation) as MCP tools.
- `agent_config.py` — resolves `AI_AGENT_PROVIDER`/`AI_AGENT_MODEL` from `secrets/secret_llm.env` once at import time; fails loudly (`AgentConfigError`) for a missing/unknown provider or a missing API key, rather than on first request.
- `llm/` — `claude_provider.py`/`openai_provider.py` (the tool-calling loop, one per provider — Ollama is out of scope for this slice), `cooldown.py` (rate-limit cooldown), `cancellation.py` (process-local, in-memory; each `ai_agent` instance tracks only the turns it itself is serving), `base.py` (shared types: `ChatResult`, `ToolCallRecord`, `ChatCancelled`).
- `mcp_upstream.py`, `registry.py`, `config.py`, `transports.py`, `sync_wrapper.py` — a generic MCP-client layer (`McpClientRegistry`/`SyncMcpClient`) giving this project one persistent, namespaced connection to `mcp_server`, opened once at startup and reused for every request rather than reconnected per call.

### 4.2 Cancellation

`chat_app`'s Stop button sends `request_id` (and which agent) through to `ai_agent`'s `cancel` tool. Each provider's tool-calling loop checks `cancellation.is_cancelled(request_id)` between rounds and raises `ChatCancelled`, which `ask` catches and turns into a clean, non-error result (`{"response": "⏹️ Cancelled.", "cancelled": true, ...}`) rather than an MCP tool error.

### 4.3 Agent-to-agent delegation

Each agent's tool schema includes a `delegate_to_agent` tool whenever `configs/config_agents.json` (own copy per instance, listing every agent including itself) has at least one entry (`src/delegation.py`). The model can hand a focused sub-question to any configured agent - a different model for a second opinion, or itself for a fresh, unpolluted sub-conversation - via the same MCP `ask` call `chat_app` itself uses, one connection per call. A `depth` parameter (invisible to `chat_app`, which never sets it) is incremented on each hop and capped at 2, so a delegation chain fails cleanly rather than running away. Cancellation is not propagated into a delegated call - `chat_app`'s Stop button has no visibility past the top-level agent.

---

## 5. `mcp_server`

A `FastMCP`-based server exposing model-callable tools over streamable HTTP.

### 5.1 Code layout (`src/`)

- **`capabilities/`** — one folder per tool, each following a fixed three-file shape: `contract.py` (Pydantic request/result models), `domain.py` (real logic — SSH/SMTP calls, typed in and out, no MCP-protocol imports), `tool.py` (thin `@mcp.tool()` wrappers). One capability exists today: `server_manager` (start/stop/restart/list managed apps).
- **`resources/`** — the same shape minus `tool.py`, for client-readable URI resources (`scheme://...`) rather than model-chosen tools. None registered in this checkout.
- **`infra/`** — shared clients every capability reuses: `ssh.py` (the one paramiko connection path), `email.py` (SMTP send), `app_config.py` (loaders for every `configs/config_*.json` file, including `${VAR}` secret substitution), `pending_requests.py` (SQLite-backed store for approval-gated requests), `approvals.py` (the human-approval gate), `extensions.py` (proxies other MCP servers' tools in as this server's own), `capability_registry.py` (the live capability on/off toggle mechanism).
- `run.py` — entry point; loads secrets, reads the capability toggle, imports each capability (registering its tools), connects extensions, and serves.
- `server.py` — the shared `FastMCP` instance every capability/resource registers onto.
- `config.py` — process-level `Settings` (bind host/port, config/data/log locations).
- `commands.py` — the `@command` registry backing chat_app's `/` slash-command autocomplete.
- Plain HTTP routes mounted alongside the MCP surface (not MCP tools — deliberately unreachable by the model itself): `approval_routes.py` (where a human approves a gated action), `approver_sync_routes.py` (chat_app pushes its registered approvers here), `extension_routes.py` (list/add/remove proxied MCP servers), `command_routes.py` (chat_app discovers slash commands), `capability_routes.py` (`GET/PATCH /capabilities` — live on/off toggle).

### 5.2 Capability toggle

Each capability can be disabled without touching code or restarting: `config_capabilities.json` holds one `{"enabled": bool}` entry per capability (`server` is `true` by default in this checkout). `PATCH /capabilities/{name}` — called by chat_app's Capabilities page — flips the flag, persists it, and adds/removes that capability's tools from the running server in one request via `capability_registry.py`.

### 5.3 Human-approval gate

Any tool whose effect is irreversible (none registered currently) is registered as a `GatedCapability` with `infra/approvals.py` instead of acting directly. Calling it creates a pending request (persisted via `pending_requests.py`) and emails a link to that capability's registered approvers; the actual change only runs once a human approves, either through the emailed link (routed to chat_app's Approvals page login + eligibility check) or `mcp_server`'s own bare-HTML fallback approval page. This exists specifically so a model — including one manipulated via prompt injection — cannot approve its own request.

### 5.4 Extensions (proxied MCP servers)

`infra/extensions.py` connects out to other MCP servers as a client and re-exposes their tools under a namespaced name, governed by `config_extensions.json`. This is the mechanism for exposing a tool that already exists elsewhere, as opposed to a `capabilities/` folder, which is for logic written in this codebase.

### 5.5 Output formatting

A tool's return value is a Pydantic model, serialized by FastMCP as JSON — the wire format, not something meant for a person to read directly. `chat_app/src/services/command_formatting.py`'s `format_command_result()` renders that JSON as Markdown for both surfaces that can invoke a tool directly outside a model turn: Chat's `/` commands and the Capabilities page's "try it" console (which still offers a "Show raw JSON" toggle underneath). An LLM-routed chat turn skips this — the model gets the raw JSON and writes its own prose reply. Every capability's `contract.py` is written to fit one of two shapes this formatter understands (flat fields + a `message` string, or a `status` + preformatted `report` block) to get useful rendering for free.

---

## 6. How the Three Services Connect

| Surface | Mechanism |
| --- | --- |
| LLM Q&A (Chat page, no leading `/`) | `chat_app`'s `ai_agent_client.py` calls the configured agent's `ask` tool over MCP streamable HTTP; that agent runs its own tool-calling loop against `mcp_server` over its own persistent MCP connection |
| Cancel (Chat page's Stop button) | `chat_app`'s `cancel_chat_api()` calls the same agent's `cancel` tool with the turn's `request_id` |
| Agent availability (provider dropdown) | `chat_app`'s `providers_api()` polls every configured agent's `status` tool live on each load |
| `/` slash commands (Chat page) | `chat_app`'s `services/commands.py` executes a command against `mcp_server`'s MCP surface directly (not through any agent) and renders the formatted result as the reply bubble |
| Capabilities page | Reads the live tool/resource catalog and runs "try it" calls against `mcp_server`'s MCP endpoint directly; `PATCH /capabilities/{name}` (plain HTTP) toggles a capability on/off |
| Approvals page | Polls `mcp_server`'s `GET /approvals` for pending rows and calls `POST /<token>/decide` (via `mcp_client.decide_approval`) to approve/decline; holds no pending-request state of its own |
| Approver sync | `chat_app` pushes its currently registered, verified `CapabilityApprover` accounts to `mcp_server`'s `approver_sync_routes.py` whenever that set changes, so `mcp_server` knows who to email |

`chat_app`, `ai_agent`, and `mcp_server` bind to `127.0.0.1:5000`, `127.0.0.1:9100`/`9101`, and `127.0.0.1:8010` respectively by default. Neither `mcp_server` nor `ai_agent` has authentication of its own — `mcp_server`'s startup banner prints an explicit warning if it's ever bound to a non-loopback address, since anything that can reach the port can then call every registered tool; the same caution applies to binding an `ai_agent` instance non-locally.

---

## 7. Running Locally

| Service | Command | From |
| --- | --- | --- |
| `mcp_server` | `run.bat` | `mcp_server/` (creates `.venv_mcp` on first run, installs, runs `py -m src.run`) |
| `catalog_service` | `run.bat` | `catalog_service/` (`.venv_catalog`, `py -m src.run`) |
| `ai_agent` (anthropic) | `run.bat` | `ai_agent/` (`.venv_ai_agent`, `py -m src.server`, default `AI_AGENT_PROVIDER=anthropic`/`:9100`) |
| `ai_agent` (openai) | `run.bat` | `ai_agent/` (same venv; `set AI_AGENT_PROVIDER=openai` and `set AI_AGENT_PORT=9101` first) |
| `chat_app` | `run.bat` | `chat_app/` (`.venv_chat`, `py -m src.run`) |
| Desktop launcher | `server_launcherun.bat` | repo root — Tkinter UI autodetecting every `<project>/run.bat`; start/stop/restart with live logs, port auto-assigned if taken |

Each needs its own `secrets/*.env.example` and `configs/*.json.example` files copied and filled in before first run — see each service's own `README.md` and `secrets/README.md` / `configs/README.md`.

---

## 8. References

- [`chat_app/README.md`](../chat_app/README.md), [`chat_app/src/README.md`](../chat_app/src/README.md)
- [`ai_agent/README.md`](../ai_agent/README.md)
- [`mcp_server/README.md`](../mcp_server/README.md), [`mcp_server/src/README.md`](../mcp_server/src/README.md)
- [`mcp_server/src/capabilities/README.md`](../mcp_server/src/capabilities/README.md) — the shape every capability follows
- `mcp_server/docs/capabilities/` — per-capability technical documentation
- [`docs/superpowers/specs/2026-09-07-ai-agent-mcp-layer-design.md`](superpowers/specs/2026-09-07-ai-agent-mcp-layer-design.md) — design notes behind the `ai_agent` layer, including a bug found and fixed during implementation
- `chat_app/docs/superpowers/specs/2026-08-22-chat-capabilities-port-design.md`, `docs/superpowers/plans/2026-08-24-capability-approval-workflow.md` — design notes behind the Chat/Capabilities port and the approval workflow
