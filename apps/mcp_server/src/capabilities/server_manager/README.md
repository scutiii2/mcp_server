# capabilities/server_manager/

Start, stop, restart and list the Docker apps on this host; read their logs. Chat id `server`, label "Server Manager".

## App watcher

Starting an app (`tool_srv_startApp`, `tool_srv_restartApp`) starts a `ServerWatcher` (`utils/server_watcher.py`, a
`JobWatcher` child). It polls every 30 seconds for 10 minutes, then every 5 minutes, with no time limit:

- App missing from `tool_srv_listApps` data (removed) or listed but not `running` (crashed): one email with the last
  20 log lines, then the watcher ends. Restarting the app starts a new one.
- New log lines containing "error" while running: one email with all new lines, at most one per app per hour; lines
  found during the cool-down go out in the next email.

`tool_srv_stopApp` ends the watcher first, so a deliberate stop sends no email. `tool_srv_listApps` shows which apps
are watched. Mail goes to the address of whoever started the app, through the Email capability (`notification`
template); it needs Email online and configured. The outcome is stored in the watcher's `detail["email_result"]`.

State lives under `MCP_WATCHERS_DIR` (default `.data/watchers/ServerWatcher/instances/`). Watchers are resumed when
the server starts, only while this capability is enabled.
