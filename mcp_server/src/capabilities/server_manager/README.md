# capabilities/server_manager/

Start, stop, restart and list the Docker containers on this host - four tools.

## Tools

| Tool | Purpose | Connection |
| --- | --- | --- |
| `tool_srv_startApp` | Start a stopped app. | Docker socket |
| `tool_srv_stopApp` | Stop a running app. | Docker socket |
| `tool_srv_restartApp` | Restart an app. | Docker socket |
| `tool_srv_listApps` | List every app with status and image. | Docker socket |

## Slash commands

| Tool | Slash command | Parameters |
| --- | --- | --- |
| `tool_srv_startApp` | `/server start` | <ul><li>`name` - required. Container name as Docker shows it.</li></ul> |
| `tool_srv_stopApp` | `/server stop` | <ul><li>`name` - required. Container name as Docker shows it.</li></ul> |
| `tool_srv_restartApp` | `/server restart` | <ul><li>`name` - required. Container name as Docker shows it.</li></ul> |
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

Toggle: `"server"` in `configs/config_capabilities.json`.
