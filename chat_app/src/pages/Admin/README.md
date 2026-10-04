# pages/Admin/

Role/permission/account administration and invite generation (spec §10).
URL prefix: `/admin`. Reached via the account menu (the avatar/username
dropdown in the sidebar footer / Overview header), gated by
`admin.roles.manage`, rather than the main `nav_pages` sidebar links —
see `pages/README.md`.

## Routes

- `GET /admin/` — dashboard: lists roles (with their permissions),
  accounts (with their roles), every distinct `Permission` row, the 20
  most recent invites.
  Accepts a `?tab=` query param (`roles` | `accounts` | `permissions` |
  `invites`, defaults to `roles`, falls back to `roles`
  on an unrecognized value) selecting which tab renders active — every
  mutating route below redirects back with its own tab set, so the
  page stays on the tab an action came from instead of always
  bouncing to Roles. Also renders a search box (`admin-search`) above
  the tabs — `script.js` filters the visible cards client-side as you
  type (matched against each card's `data-search` attribute, not its
  rendered text, since a role's name only otherwise lives inside an
  editable `<input value>`) and switches to whichever tab has
  matches, no server round trip.
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
- `POST /admin/accounts/<id>/edit` — edit an account's `username` and
  `email`. Rejects a duplicate username or email (flashes an error,
  no-ops). Refuses outright if the account is `is_protected` — see
  Permissions below. Does not touch `is_active` — there's no admin UI
  control for it currently, so `update_account` leaves it as-is.
- `POST /admin/accounts/<id>/verify` — (re)send a verification-code
  email to the account's own address, reusing
  `otp_service.create_email_verification` +
  `email_service.send_email_verification` (the same pair
  `pages/Auth/__index__.py` uses for registration/resend). No-ops if
  the account is already `email_verified`. The account still has to
  enter the code itself via `/auth/verify-email` — this route only
  triggers the send, it never marks an account verified on an admin's
  say-so.
- `POST /admin/accounts/<id>/delete` — delete an account outright,
  which also clears it from every role it held. Refuses if the
  account is `is_protected`, or if it's the account making the
  request (no self-delete).
- `POST /admin/accounts/<id>/roles` — assign a role to an account
  (`role_id`).
- `POST /admin/accounts/<id>/roles/remove` — remove a role from an
  account. Refuses (flashes an error, no-ops) if the account is
  `is_protected`.
- `POST /admin/permissions/<id>/grant` — grant a permission to a role
  from the permission's own card (`role_id`) — the mirror image of
  `/admin/roles/<id>/permissions`, reusing the same
  `admin_service.assign_permission_to_role`.
- `POST /admin/permissions/<id>/edit` — edit a permission's
  `description`. The `name` is never editable here — it's wired to a
  `@require_permission("...")` decorator somewhere in the code, and
  renaming the row would silently detach it from that check.
- `POST /admin/permissions/<id>/delete` — delete a permission
  outright, revoking it from every role that currently holds it. Safe
  to do even for a permission still in use: `auth_service.
  ensure_bootstrap_admin`'s self-heal recreates and re-grants any
  registered permission missing from the `Administrator` role on
  every boot, so deleting it just resets that role's grant (any other
  role's grant stays revoked, same as manually revoking it).
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

The bootstrap admin `Account` itself (also created by
`ensure_bootstrap_admin`, `is_protected=True`) is protected the same
way: `admin_service.update_account` and `delete_account` both raise
`ProtectedAccountError` for it, since it's the only account guaranteed
to exist and self-heal — editing or deleting it has no recovery path
short of DB surgery. `delete_account` separately refuses to let an
account delete itself (protected or not), to avoid cutting off your
own session mid-action.

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
Roles / Accounts / Permissions / Invites, rather than
separate pages — kept together since every action here is an admin
action.

Each Role/Account/Permission card (`.role`/`.account`/`.permission`)
has one top row of identifying fields, a scrollable list of related
items with per-row Revoke buttons, and a footer split into a
grant/assign control (left) and Save/Delete (right) — the mutating
action a field belongs to is still a distinct `<form>` per POST route,
but Save/Delete/edit-field elements live wherever the layout wants
them and point back at their form by `id` via the HTML5 `form="..."`
attribute, rather than needing to be that form's DOM descendant. The
edit/delete forms themselves render as empty, `display:none` "shells"
(`.form-shell`, just the CSRF token) parked at the top of the card —
see `style.css`'s `.entity-*` rules for the layout this enables.

The grant/assign control in each footer (`grant_combobox` macro, top of
`view.html`) is a filter-as-you-type combobox, not a plain `<select>`
— a text input plus an absolutely-positioned `.combobox-options`
panel of `.combobox-option` divs, narrowed by substring match against
`data-label` as you type. `initGrantComboboxes()` in `script.js` wires
every `[data-combobox]` element the same way regardless of which
grant route it posts to (grant a permission to a role, a role to an
account, or a role to a permission — `role_options`/
`permission_options`, built once in `dashboard()`, feed all three).
Selecting an option (via `mousedown`, not `click`, so it fires before
the input's `blur` would otherwise close the panel first) fills a
hidden hint input with the id/name actually submitted; typing without
selecting clears that hidden value, so a stale or unselected label can
never silently submit.

The Accounts card's badge slot shows a green shield for
`email_verified` accounts and a "Verify" button otherwise (posts to
`/admin/accounts/<id>/verify`) — independent of `is_protected`, which
only gates the edit/delete affordances now, not the badge.

`script.js` (page-local, loaded at the bottom of `view.html`) handles
the search box and the grant comboboxes; tab switching and the delete
confirmation modal (which attaches to the form element directly, so
it's unaffected by where its fields/buttons are positioned) are still
`__shared__/shared.js`'s `initTabs()`/`initConfirmModals()`, reused
as-is.
