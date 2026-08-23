# pages/Overview/

Post-login landing page and page picker (spec §12). URL: `/` (the one
exception to the folder-name-lowercased URL prefix rule).

## Routes

- `GET /` — shows a card for every page the current account can reach
  (any page with `PAGE_PERMISSION = None`, or one the account holds the
  permission for), computed by `pages/__index__.py`'s `nav_pages`
  context processor. Each card shows the page's icon, name, and its
  `PAGE_DESCRIPTION` (if set). `Account` and `Admin` don't get cards —
  they live in the account menu instead (see below). No sidebar here —
  Overview *is* the page picker, so it shows the account menu
  (`__shared__/account_menu.html`) in the upper-right corner instead
  (every other page gets the sidebar, with the same menu in its
  footer).

## Permissions

None beyond being logged in (`authz.require_login()`).
