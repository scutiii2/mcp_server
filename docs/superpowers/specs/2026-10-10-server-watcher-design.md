# ServerWatcher: first child of JobWatcher

Date: 2026-10-10. Status: design, awaiting review.

## Goal

`JobWatcher` (`apps/mcp_server/src/services/watcher.py`) becomes the shared base for capability-owned background
workflows: a **trigger** (`poll()` sees something) and an **action** (`on_completed()` does something). The user-facing
`watchers` capability is removed. `ServerWatcher`, owned by `server_manager`, is the first child.

## Behaviour

- `tool_srv_startApp` and `tool_srv_restartApp` start a `ServerWatcher` for the app after a successful start. The key is
  the container name; a second start replaces the first (the base class already does this).
- `tool_srv_stopApp` cancels that app's watcher and deletes its record (a deliberate stop is not a crash).
- Interval: every 30 s for the first 10 minutes, then every 5 minutes. No time limit.
- Each poll:
  1. `domain.list_apps()` for the app's status.
     - Not listed: finish with reason `removed`.
     - Listed and not `running` (`exited`, `dead`, `restarting`, `paused`): finish with reason `crashed`.
  2. If running, `domain.read_app_logs(name, contains="error")`. Lines not seen before are kept in `detail`.
- Emails go to the owner (the account that called `tool_srv_startApp`; stored in the record so resume still knows it):
  - On finish (`removed` or `crashed`): one email with the reason, last status and the last 20 log lines (already masked by
    `redact()`). The watcher then ends. Restarting the app starts a fresh watcher.
  - New error lines while running: one email covering all new lines found since the last email, at most one per app per
    hour. Lines found inside the cool-down are held and go out in the next email.
- Delivery uses `services/email_delivery.deliver_email` with the `notification` template. The outcome is stored in
  `detail["email_result"]` (`sent`, `skipped: ...`, `failed: ...`). A mail failure never stops the watcher.
- Resume: `ServerWatcher.resume_all(settings.watchers_dir)` at server start, when `srv` is enabled. An app that is not
  running at resume counts as crashed (right after a host restart).

## List apps shows watched state

- `AppInfo` gets `watched: bool` (true while a `ServerWatcher` is registered for that name).
- `list_apps()` fills it from `ServerWatcher.is_watching(name)` and the text report gains a `watched` column.
- `tool_srv_listApps` docstring mentions it so the assistant can answer "which apps are watched".

## Base class changes (`services/watcher.py`)

- Open-ended schedule: a `backoff_schedule` whose last cutoff is `None` never times out.
- Shared `cancel(state_dir, key)` (stop the running watcher and delete its record). `UserWatcher` has its own copy today.
- Shared `is_active(key)` used by `is_watching`.
- `on_state_change` docstring loses "reserved for a future notification hook".

## Removal of the `watchers` capability (separate step, after ServerWatcher works)

- `capabilities/watchers/`, its tests, the `watch` toggle in `config_capabilities.json(.example)`, `run.py` resume block,
  `capability_loader` references, ember_api `routes/watchers.py` + permission, ember_web Watchers page + overview tiles,
  ember_admin role entry, server_launcher references, README and `_TODO.md` mentions.
- `watcher_recipients.py` goes if nothing else uses it after removal.
- `MCP_WATCHERS_DIR` stays as the state directory for all job watchers.
- The email helper in `watchers/utils/notify.py` moves into the server_manager child.
- Scheduler agent (`agents/scheduler.json`) is kept as requested, but loses its `tool_watch_*` tools. Flag it again at the
  end of the removal step.
- ember_web changes are proposed and approved step by step.

## Testing

Fake `list_apps`, `read_app_logs` and notifier injected as in `test_user_watcher.py`. Cases: crash, removal, error-line
email with batching and the hourly limit, cancel on `stopApp`, resume after restart, `watched` flag in `list_apps`.
