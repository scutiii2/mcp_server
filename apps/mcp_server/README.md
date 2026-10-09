# mcp_server

A general-purpose MCP (Model Context Protocol) tool server: a proxy for other MCP
servers' tools ("extensions"), and a `server_manager` capability for
starting/stopping/restarting/listing managed apps. Built to be called by
`chat_app` or any other MCP client speaking streamable HTTP.

## Requirements

- Python >= 3.11
- An SMTP account for outbound mail (Email capability, watcher notifications, Ember invites and verification)


## Setup

1. Copy `.env.example` to `.env` (created automatically on first run) and
   the `.example` files under `configs/`, and fill in real values - see [Configuration](#configuration).

2. Run the server:

   ```
   run.bat
   ```

   (from `apps/mcp_server/` - creates `.venv_mcp` and installs this project
   into it in editable mode on first run, then runs `py -m src.run`.)

## Configuration

Both loaded once at boot by `src/run.py`:

- **`.env`** - credentials and deployment settings, gitignored. Copy
  `.env.example` to `.env`. See [`docs/secrets.md`](docs/secrets.md).
- **`configs/*.json`** - structure, mostly committed. See
  [`configs/README.md`](configs/README.md).

## Security

- **`/mcp` needs the internal token** once `INTERNAL_API_TOKEN` is set in
  `.env` (`X-Internal-Token`, compared in
  constant time; `401` otherwise). Every caller is another server in this
  repo - chat_app, ai_agent, ember_api - and all of them send it. The
  startup banner says whether it's on.
- **Who is asking**: tools read the user from `X-Requester-Username` /
  `X-Requester-Email` (chat_app, ember_api), or from the tool call's
  `_meta.requester` (ai_agent, whose one session serves every user) - see
  `src/services/identity_context.py`. Each tool call is logged with it
  (`tool call <name> by <user>` in `server.log`).

## Code layout

See [`src/README.md`](src/README.md) for the full map - what lives
where, and where new code goes.

## Capabilities

Each tool this server offers lives under its own folder in
`src/capabilities/`, with its own README - see
[`src/capabilities/README.md`](src/capabilities/README.md) for the
shape every capability follows and how to add a new one:

- [`capabilities/server_manager`](src/capabilities/server_manager) - start/stop/restart/list managed apps (`/server ...`)

Every capability can be turned off without touching code, live - no
restart needed. `GET /capabilities` lists each one's current state
(`name`, `enabled`, `label`, `tools`, `resources`, `has_gui`, and
`loaded`, `missing`, `load_error`: `loaded` is false for a folder that was
found but never brought online, `missing` means its folder is gone from
disk, `load_error` is the text of the last failed import);
`PATCH /capabilities/{name}` (body `{"enabled": bool}`) toggles it,
persists the change to `config_capabilities.json`, and adds/removes its
tools and resources from the running server, all in one request. Going
online re-imports the capability from disk, and answers `409` with
`{"error": ...}` if that fails. `POST /capabilities/refresh` rescans
`src/capabilities/` so a folder added while the server runs shows up
(offline) and returns the same list. A new folder is never loaded until it
is switched online. See `src/capability_routes.py`,
`src/services/capability_loader.py` and `src/infra/README.md`'s
`capability_registry.py` entry. ember_admin's Capabilities page calls these.

Client-readable URI resources follow the same pattern one level over -
see [`src/resources/README.md`](src/resources/README.md).

## Runtime state

Dot-prefixed folders hold untracked runtime state and secrets; plain
`configs/` folders are tracked.

- **`.data/`** - state shared across capabilities (`pending_requests.db`,
  `uploads/`).
- **`.logs/`** - `server.log` plus one file per error reference id,
  regenerated on every run.
- **`.cache/`** - regenerable shared cache, if any.
- **`specifics/<capability_name>/`** - the same layout (`.data/`,
  `.logs/`, `.cache/`, `.secrets/`, `configs/`) for state and config
  that a single capability owns outright. Only `configs/` is tracked.
  Documented in that capability's own README.

## Tests

```
pytest
```

## Docker

See `zima_host.yaml` for a ZimaOS "customized app" Docker Compose recipe.


The recipe loads credentials from the host file
`/media/HDD320-1/MCPArchitecture/mcp_server/.env` (the same project `.env`
used by local startup, already gitignored). Place the file at that path
before starting the customized app; Compose does not upload it for you.
Keep `SMTP_PASSWORD` there and restrict the file's permissions to the
account managing the deployment. Keep the host path in `env_file` and the
volume mount in step if you move the deployment.

The SMTP password previously embedded in this recipe must be revoked at
the mail provider. Put a replacement password in the deployment `.env`,
then recreate the container and verify watcher email delivery. Removing
it from the recipe does not remove it from Git history or rotate it.


### PDF chat attachments

`POST /upload/pdf` accepts a multipart `file` (PDF, PNG, JPEG, WebP, TIFF,
GIF or HEIC; at most 15 MB). It requires this server's `X-Internal-Token`
and an authenticated `X-Requester-Username` supplied by Ember's API.
The configured `pdf_merger` extension must use HTTP, an internal token in
its headers, and `forward_requester: true`. The route resolves only that
extension's configuration and sends original bytes to its `/api/files`
endpoint under the same requester used by the proxied PDF tools. Browser
session fallback is rejected before uploading when the PDFMerger token is wrong.
The response contains PDFMerger's opaque file ID, metadata and expiry.
Originals remain in PDFMerger's store until its configured TTL expires.
No document bytes, extension credentials or internal URLs are sent to the model.
