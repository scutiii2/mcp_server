# pages/Account/

Self-service profile view/edit (spec §5's own example permission,
`account.edit`). URL prefix: `/account`. Reached via the account menu
(the avatar/username dropdown in the sidebar footer / Overview header)
rather than the main `nav_pages` sidebar links — see
`pages/README.md`.

## Routes

- `GET /account/` — view your own username/email. Everyone logged in
  can reach this page (`PAGE_PERMISSION = None`).
- `POST /account/` — update email and/or password (`current_password`
  required to authorize the change, verified via
  `auth_service.update_account_profile`). Requires `account.edit` —
  registered via `authz.register_permission()` at import time (checked
  manually with `authz.has_permission()`, not the `@require_permission`
  decorator, since GET and POST share one route and only POST needs the
  gate).

## Permissions

`account.edit` — **flagged default**: new accounts get no roles at
registration (spec §7), so a fresh account cannot edit its own profile
until an admin grants it. This matches the template's "admin controls
everything explicitly" philosophy, but is worth reconsidering per
project — a project might prefer everyone can always edit their own
profile, in which case drop the permission check here entirely.

## Templates

`account.html`, not `view.html` — Flask's blueprint template loader
resolves same-named templates across blueprints to whichever one
registered first, so every page in this project needs a uniquely-named
main template (see `pages/Overview/`'s `overview.html` for the same
reason; `pages/Admin/`'s `view.html` was first and keeps that name).
