# Watchers

Read-only status of background watchers (`JobWatcher` subclasses) exposed by
any mcp_server capability. Every row is fetched live from mcp_server - this
page holds no watcher state of its own. Entirely client-rendered (no SSR
fetch in `index()` - see `script.js`'s `refreshWatchers()`).

## Discovery convention

A capability with watchers exposes a tool-only tool named
`tool_<alias>_listWatchers` returning `{"watchers": [...]}` (each row: `key`,
`phase`, `started_at`, `last_polled_at`, `detail`, `recipients`).
`GET /watchers/api/watchers` finds every `listWatchers` tool in the live tool
catalog, calls each and tags rows with their `capability` alias, so a new
capability's watchers appear here with no chat_app change. A capability that
fails to answer is reported in the response's `errors` list instead of
breaking the page.

## UI

One table: **Watcher** (key, capability alias, expandable `detail`),
**Status** (`running` "Running", `completed` "Success",
`failed`/`timed_out` "Failed"), **Duration** (elapsed, started/finished
times) and **Recipients** (read-only). Client-side filters (all run
on the already-fetched array): capability chips (built from the data),
status chips, started-from/until range, and a text search. The table
refreshes every 15s.

Viewing is gated by `watchers.view`. Recipients cannot be edited here; they
are set on the mcp_server side through the capability's
`tool_<alias>_setWatcherRecipients`.
