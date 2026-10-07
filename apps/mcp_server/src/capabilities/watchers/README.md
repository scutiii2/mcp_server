# capabilities/watchers/

Watch a web address, a managed app or a TCP port in the background and get one email when it is up (or down) -
three tools. Chat id `watch`, label "Watchers".

## What a watcher is

One-shot: it ends when its condition is first met, or after 24 hours (`timed_out`). It checks every 30 seconds for
the first 10 minutes, then every 5 minutes. One `UserWatcher` class (`utils/user_watcher.py`, built on
`services/watcher.py`'s `JobWatcher`) runs the check named by its `WatchSpec` (`utils/spec.py`).

| `kind` | "up" is true when | "down" is true when |
| --- | --- | --- |
| `url` | status 200-399 and, if `contains` is set, the first 64 KB of the body holds the text (case-insensitive) | the request fails or times out (10 s), or the status is outside 200-399 |
| `app` | `server_manager` lists the app as `running` | the app is listed and not running |
| `tcp` | a TCP connection to `host:port` succeeds within 5 s | it fails or times out |

An app that is not listed at all is "unknown" and matches neither. `app` needs Docker, like the `server_manager`
tools; `url` and `tcp` work anywhere. URL checks follow no redirects, refuse addresses with a user name or password,
and never return or store the page body. Private and loopback addresses are allowed on purpose (watching a home-lab
service is the main use); only a boolean and a status code come back.

## Tools

| Tool | Slash command | Purpose |
| --- | --- | --- |
| `tool_watch_create` | `/watch create kind=... target=... expect=... contains=... label=...` | Start a watcher |
| `tool_watch_listWatchers` | `/watch list` | Your watchers, newest first (ember_api's Watchers page reads this tool by name) |
| `tool_watch_cancel` | `/watch cancel key=...` | Stop or remove one of your watchers |

## Notification

One email to the creator's own address (`identity_context.current_email()`), never a tool argument, through
`services/email.send_email` with the `notification` template. It needs `configs/config_email.json` (copy the
`.example`, set `from`) and `SMTP_PASSWORD` in `.env`. The outcome is stored in the watcher's `detail["email_result"]` (`detail["email"]` stays the address):
`sent`, `skipped: <reason>` or `failed: <reason>`. A missing or invalid config never stops a watcher.

## State and limits

Records and recipients live under `MCP_WATCHERS_DIR` (default `.data/watchers/`, gitignored), one folder per class,
and running watchers are resumed when the server starts. At most 5 running watchers per user and 50 in total; each
user keeps their newest 20 finished records. Watchers belong to their creator: list and cancel only see your own.

Toggle: `"watch"` in `configs/config_capabilities.json`.
Toggling it at runtime does not stop running watchers or resume records: watchers are resumed only at server start,
and only when the capability is enabled.
