# Logs Page — Design Spec

Date: 2026-08-22
Status: Draft — pending user review

## 1. Goals

Add a **Logs** page (`/logs`) with two tabs, **Logs** and **Errors**,
each gated by its own permission. The page is visible in `nav_pages` if
the current account holds *either* permission; if it holds only one,
only that tab is shown. Each tab has a dropdown listing **Server**
(default) plus every account — selecting Server shows entries not tied
to any account (app-level activity/errors); selecting an account shows
that account's own action/error entries.

This requires building the underlying logging subsystem — there is
currently no generic, queryable log store. `SecurityEvent` (existing)
stays scoped to the auth-specific events it already covers (new
device, lockout, ip block); it is not reused or extended here. The
file-based daily logs under `src/logs/` (spec
`2026-08-21-authtemplate-design.md` §13, `utils/logging_setup.py`) are
unrelated developer/ops logging and are untouched by this feature.

## 2. Non-Goals

- No manual `log_error(...)` call sites — errors are captured only via
  automatic unhandled-exception capture (see §5).
- No log search, export, or retention/rotation policy — a row cap is
  sufficient for v1.
- No real-time/streaming updates — the page reflects data as of the
  last load (query-param-driven GET reloads, no AJAX/websockets).
- No editing or deleting of log entries.

## 3. Data Model

New model, `src/models/log_entry.py`:

- **LogEntry** — id, `kind` (`"action"` | `"error"`), `account_id`
  (nullable FK → `accounts.id`; `NULL` = server/no account), `source`
  (string, e.g. `"auth.login"`, `"admin.assign_role"` — dot-namespaced
  like permissions, identifies the call site), `message` (short
  string), `details` (nullable text — full context, e.g. an exception
  traceback), `created_at`.

One table backs both tabs; a tab is just `kind="action"` or
`kind="error"`, filtered further by `account_id`.

Registered in `src/models/__init__.py` alongside the existing models.

## 4. `log_service.py`

New `src/services/log_service.py`:

- `log_action(session, account, source, message, details=None)` —
  writes a `kind="action"` entry. `account` is an `Account` instance
  (writes its id) — there's no "server action" concept, only server
  errors, so this always takes a real account.
- `log_error(session, account_or_none, source, message, details=None)`
  — writes a `kind="error"` entry; `account_or_none` is `None` for
  server-side errors (no authenticated user on the request) or an
  `Account` for errors during an authenticated request.
- `list_entries(session, kind, account_id=None, limit=200)` — returns
  the most recent `limit` entries of that `kind`, newest first, where
  `account_id=None` means `LogEntry.account_id.is_(None)` (Server) and
  a given id means `LogEntry.account_id == account_id`. No "all
  accounts" option — the dropdown always resolves to one of these two
  filter shapes.

## 5. Action & Error Capture

**Actions** — explicit `log_action(...)` calls added at these existing
call sites:

- `Auth/__index__.py`: `login` (on success, source `"auth.login"`),
  `logout` (capture `current_user` before `logout_user()`, source
  `"auth.logout"`), `register` (on success, logged against the new
  account, source `"auth.register"`).
- `Admin/__index__.py`: `create_role`, `assign_permission`,
  `remove_permission`, `assign_role`, `remove_role`, `create_invite` —
  each logged against `current_user` (the admin performing the
  action), source `"admin.<function_name>"`, on the success path only
  (skip logging when the route just flashes a validation error and
  no-ops).
- `Account/__index__.py`: `profile` POST handler, on successful update
  only, source `"account.profile_update"`, logged against
  `current_user`.

Failed login attempts are **not** logged here — `LoginAttempt` already
records those; a failed login has no verified account to attribute the
action to.

**Errors** — automatic, not manual. In `run.py`, alongside the
existing 401/403/429 handlers:

```python
@app.errorhandler(Exception)
def handle_unexpected_error(error):
    if isinstance(error, HTTPException):
        raise error
    log_service.log_error(
        db.session,
        current_user if current_user.is_authenticated else None,
        source="unhandled_exception",
        message=str(error) or type(error).__name__,
        details=traceback.format_exc(),
    )
    raise error
```

Re-raising after logging preserves Flask's normal 500 behavior (or
whatever `debug=True` does locally) — this handler only observes and
records, it doesn't change the response. The `isinstance(error,
HTTPException)` guard means 404s and any other `HTTPException` keep
propagating to their normal handling (or Flask's default) instead of
being logged as errors — only genuine unhandled exceptions (bugs) are
captured.

## 6. Permissions & Page Visibility

Two permissions, registered the same way `admin.roles.manage` and
`auth.invite` are today:

- `logs.view` — gates the Logs tab's route/data.
- `logs.errors.view` — gates the Errors tab's route/data.

`PAGE_PERMISSION` today is `None` or a single string, checked in
`pages/__index__.py`'s `_visible()`. This page needs "visible if the
account holds *any* of several permissions," so `_visible()` is
extended (backward compatible) to also accept a tuple/list:

```python
def _visible(p):
    perm = p["permission"]
    if perm is None:
        return True
    if isinstance(perm, (list, tuple)):
        return any(has_permission(current_user, name) for name in perm)
    return has_permission(current_user, perm)
```

`Logs/__index__.py` sets `PAGE_PERMISSION = ("logs.view",
"logs.errors.view")`. It appears in the main `nav_pages` sidebar (not
the account menu), like Sample — anyone with either permission sees
the link.

The route itself checks membership manually (not a single
`@require_permission`, since either permission is sufficient to reach
the page — but each tab's *data* still requires its own specific
permission):

```python
@blueprint.route("/")
@require_login()
def index():
    can_view_logs = has_permission(current_user, "logs.view")
    can_view_errors = has_permission(current_user, "logs.errors.view")
    if not (can_view_logs or can_view_errors):
        abort(403)
    ...
```

If the account has only one permission, only that tab's button/panel
is rendered — no disabled/empty tab shown for the one it lacks.

## 7. UI

`Logs/view.html`, follows the Admin page's existing `data-tabs` /
`tab-btn` / `tab-panel` convention (client-side show/hide, already
wired in `shared.js`'s `initTabs()`). Since tab switching is
client-side only, **both tabs' data are rendered together** in one GET
response — same pattern Admin already uses for its three sections.

Each tab (rendered only if permitted):

- A `<form method="get">` wrapping a `<select>` of Server + every
  account (`username`), `onchange="this.form.submit()"` — reloads
  `/logs/?tab=logs&logs_actor=<id|server>&errors_actor=<preserved>` (a
  hidden input carries the other tab's current selection so switching
  one tab's dropdown doesn't reset the other's, and a hidden `tab`
  input records which tab was active so it stays active after
  reload). Default/first option is always **Server**.
- A table of matching `LogEntry` rows: timestamp, source, message, and
  for the Errors tab, an expandable `<details>` per row showing the
  full `details` (traceback).

Route reads `logs_actor` / `errors_actor` query params (`"server"` or
an account id), resolves each to the `list_entries(...)` call for the
tab(s) the account is permitted to see, and passes both the entries
and the current selection back to the template so the dropdown reflects
the active filter after reload.

## 8. Testing Strategy

- `tests/test_models.py` — `LogEntry` create/query round-trip
  (mirrors existing model tests).
- New `tests/test_log_service.py` — `log_action`/`log_error` write
  expected rows; `list_entries` filters by kind and by
  server-vs-account correctly and respects the row cap.
- New `tests/test_logs_page.py` — route tests: 403 when neither
  permission is held; only the permitted tab's data present when
  holding one; both present when holding both; dropdown filtering
  (Server vs. a specific account) returns the right subset; an
  unhandled exception raised from a test-only route produces a
  `kind="error"` `LogEntry` and the response still surfaces the normal
  500/error behavior; a 404 does **not** produce an error `LogEntry`.
- Extend `tests/test_auth_page.py`, `tests/test_admin_page.py`,
  `tests/test_account_page.py` with assertions that the relevant
  action now produces a `LogEntry` (login, logout, register; the six
  admin actions; profile update).
- `tests/test_pages_index.py` — extend `_visible()` coverage for the
  tuple/"any of" case.

## 9. Defaults Flagged for Review

- Row cap of 200 most recent entries per tab/filter, no pagination
  beyond that — flag if you want older entries reachable.
- Dropdown lists **every** account regardless of whether it has any
  entries yet (consistent, doesn't shift as entries appear) rather
  than only accounts with existing entries.
- Admin actions are logged only on their success path; validation
  failures (e.g. "role not found") are not logged as actions or
  errors — they're routine flash-message no-ops, not app errors.
