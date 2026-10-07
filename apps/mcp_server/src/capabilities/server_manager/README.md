# capabilities/server_manager/

Start, stop, restart and list the Docker containers on this host, and download an app's recent log - six tools.

## Tools

| Tool | Purpose | Connection |
| --- | --- | --- |
| `tool_srv_startApp` | Start a stopped app. | Docker socket |
| `tool_srv_stopApp` | Stop a running app. | Docker socket |
| `tool_srv_restartApp` | Restart an app. | Docker socket |
| `tool_srv_getAppLogs` | Download an app's newest log lines as a file. | Docker socket |
| `tool_srv_readAppLogs` | Read an app's newest log lines as text with secrets masked. MCP-only, for the assistant. | Docker socket |
| `tool_srv_listApps` | List every app with status and image. | Docker socket |

## Slash commands

| Tool | Slash command | Parameters |
| --- | --- | --- |
| `tool_srv_startApp` | `/server start` | <ul><li>`name` - required. Container name as Docker shows it.</li></ul> |
| `tool_srv_stopApp` | `/server stop` | <ul><li>`name` - required. Container name as Docker shows it.</li></ul> |
| `tool_srv_restartApp` | `/server restart` | <ul><li>`name` - required. Container name as Docker shows it.</li></ul> |
| `tool_srv_getAppLogs` | `/server logs` | <ul><li>`name` - required. Container name as Docker shows it.</li><li>`lines` - optional, default `500`. How many of the newest log lines to collect (1 to 5000).</li></ul> |
| `tool_srv_listApps` | `/server list` | <ul><li>none.</li></ul> |

## Typical workflow

| Sequence | Tool | Explanation |
| --- | --- | --- |
| 1 | `tool_srv_listApps` | Find the exact container name. |
| 2 | `tool_srv_startApp` / `stopApp` / `restartApp` | Act on it by name. |

## Configuration

No config or secrets. Needs the host's Docker socket reachable
(`/var/run/docker.sock` bind-mounted if this server runs in a container);
without it each tool fails with a message saying so and the rest of the
server is unaffected. The client is built per call, so a missing socket
never breaks startup. Actions are reversible and not approval-gated.

## Log downloads

`/server logs name=<app>` puts the log in `services/downloads.py`'s in-memory store and returns a
`[[DOWNLOAD ...]]` marker (`download_markers`), which the chat shows as a download card. The card's link is
`/server/download?path=<id>` (`download_routes.py`): the id is random and opaque, the file is held for
10 minutes and only for the account that asked, and nothing names a file on disk. A caller with no identity
gets no card. A log over 5 MB is cut to its newest part. Restarting this server drops every pending
download. Container logs can contain secrets of the app; anyone who may run tools can fetch them.

## Log text for the assistant

`tool_srv_readAppLogs` returns up to 300 lines (and 20,000 characters) as text, optionally only lines holding
`contains`. `utils/redact.py` masks URL passwords, `Authorization`/cookie headers, bearer tokens, JWTs, `sk-`
style keys, AWS key ids, `password`/`secret`/`token`/`api_key` assignments and email addresses as `[REDACTED]`
before anything is returned. Masking is pattern based, so a secret in an unusual shape can get through.

Toggle: `"server"` in `configs/config_capabilities.json`.
