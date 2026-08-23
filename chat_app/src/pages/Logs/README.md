# pages/Logs/

Server and per-account activity/error log viewer. URL prefix: `/logs`.

## Routes

- `GET /logs/` — renders whichever tab(s) the account is permitted to
  see. Query params: `tab` (`logs`|`errors`, which tab is active),
  `logs_actor` / `errors_actor` (`server` or an account id — which
  actor each tab's dropdown is filtered to; independent per tab).

## Permissions

- `logs.view` gates the Logs tab and its data.
- `logs.errors.view` gates the Errors tab and its data.
- The page itself is reachable (`nav_pages` link shown, route returns
  200 instead of 403) if the account holds **either** permission —
  see `pages/__index__.py`'s tuple-`PAGE_PERMISSION` support. If it
  holds only one, only that tab is rendered.

## Data

Backed by the `LogEntry` model (`models/log_entry.py`) via
`services/log_service.py`. `kind="action"` entries (written by
explicit `log_action(...)` calls in `Auth`, `Admin`, and `Account`'s
routes, on their success paths) populate the Logs tab. `kind="error"`
entries (written automatically by the generic exception handler in
`run.py` — never called manually) populate the Errors tab.
`account_id = NULL` means "server"; each tab's dropdown filters to
either Server or one specific account, listing every account
regardless of whether it has entries yet. Capped at the 200 most
recent entries per filter, newest first.

### Limitations

Automatic error capture (the `run.py` handler feeding `kind="error"`
entries) only covers exceptions raised during request routing, view
execution, and template rendering — the part of the request lifecycle
Flask routes through `@app.errorhandler`. Exceptions raised from
`after_request` hooks (this app has one, in the security pipeline,
which only sets headers) are NOT captured: Flask's `finalize_request`
runs those outside the try/except that dispatches to registered error
handlers, so such an exception would propagate uncaught rather than
producing a `LogEntry`. This is a known, low-severity gap; closing it
would require wiring Flask's `got_request_exception` signal, which was
judged not worth the added mechanism for the current risk level.

## Templates

`logs.html` extends `__shared__/base.html` and reuses Admin's
`data-tabs`/`tab-btn`/`data-tab-panel` markup convention for the two
tabs — both tabs' data are rendered together server-side in one
response, and only the active tab's panel is shown by default via the
`hidden` attribute (so the page works even without JS). Client-side
tab switching is wired via `shared.js`'s `initTabs()`, which is global
(loaded by `base.html` on every page via `DOMContentLoaded`) — no
page-specific JS is needed here. It's named `logs.html` rather than
the page-default `view.html` because `Admin/__index__.py` already
claims `view.html` in the shared flat template namespace all pages
render from (see `pages/README.md`'s naming-collision note).
