# pages/Admin/

Role/permission/account administration and invite generation (spec §10).
URL prefix: `/admin`. Reached via the account menu (the avatar/username
dropdown in the sidebar footer / Overview header), gated by
`admin.roles.manage`, rather than the main `nav_pages` sidebar links —
see `pages/README.md`.

## Routes

- `GET /admin/` — dashboard: lists roles (with their permissions),
  accounts (with their roles), and the 20 most recent invites. Accepts
  a `?tab=` query param (`roles` | `accounts` | `invites`, defaults to
  `roles`, falls back to `roles` on an unrecognized value) selecting
  which tab renders active — every mutating route below redirects back
  with its own tab set, so the page stays on the tab an action came
  from instead of always bouncing to Roles.
- `POST /admin/roles` — create a role (`name`, `description`).
- `POST /admin/roles/<id>/edit` — rename/redescribe a role (`name`,
  `description`). Rejects a duplicate `name` (flashes an error,
  no-ops). The `Administrator` role's name specifically cannot be
  changed (its description still can) — see Permissions below.
- `POST /admin/roles/<id>/delete` — delete a role outright, which also
  clears it from every account and permission it's linked to (the
  many-to-many association rows are cleaned up automatically). The
  `Administrator` role cannot be deleted.
- `POST /admin/roles/<id>/permissions` — grant a permission to a role
  (`permission_name`, must be one `authz.registered_permissions()`
  already knows about — a page has to declare it via
  `@require_permission` before it can be granted).
- `POST /admin/roles/<id>/permissions/remove` — revoke a permission.
- `POST /admin/accounts/<id>/roles` — assign a role to an account
  (`role_id`).
- `POST /admin/accounts/<id>/roles/remove` — remove a role from an
  account. Refuses (flashes an error, no-ops) if the account is
  `is_protected`.
- `POST /admin/invites` — generate an invite (`invitee_email`,
  `delivery_method` = `manual` or `email`). Manual invites flash the
  plaintext code once, in a **persistent toast** (no auto-dismiss
  timer — the flash is tagged with the `"persistent"` category, which
  `__shared__/base.html`/`shared.js` render/treat differently so it
  stays on screen until manually dismissed or the page changes, giving
  time to copy it); email invites send it via
  `email_service.send_invite_email` instead.
- `POST /admin/invites/<id>/remove` — delete an invite outright (used
  or pending — e.g. to clean up one whose code was missed before the
  toast was dismissed, or just to tidy the list).

## Permissions

The bootstrap `Administrator` role (created by
`auth_service.ensure_bootstrap_admin`, self-healed on every boot) is
protected against structural changes: `admin_service.update_role`
raises `ProtectedRoleError` if asked to rename it away from
`"Administrator"` (renaming would break the by-name lookup that
self-heals it), and `admin_service.delete_role` raises the same for
any attempt to delete it. Both are caught in the route and flashed as
an error rather than propagating.

Every route requires `admin.roles.manage` **except** `/admin/invites`
and `/admin/invites/<id>/remove`, which require `auth.invite`
specifically — spec §7 ties invite generation to that distinct
permission, separate from the broader admin gate. (In this
single-dashboard-page implementation, reaching the invite form still
requires `admin.roles.manage` to view the page at all; a role holding
only `auth.invite` has no route to it yet — giving invite generation
its own page is a natural extension for a project cloning this
template.)

## Templates

`view.html` extends `__shared__/base.html`. One page, sectioned into
Roles / Accounts / Invites, rather than three separate pages — kept
together since every action here is an admin action.
