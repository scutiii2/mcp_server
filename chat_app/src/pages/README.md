# src/pages/

Each subfolder is one page: a Flask blueprint auto-discovered and
registered by `__index__.py` at app-boot time (see `register_pages()`).

## Convention

- A page folder must contain an `__index__.py` exposing a `blueprint`
  attribute (a Flask `Blueprint`).
- The URL prefix is derived from the lowercased folder name
  (`Auth` → `/auth`, `Account` → `/account`, `Admin` → `/admin`) — with
  one exception: `Overview` maps to `/`, since it's the post-login
  landing page.
- `__shared__/` is excluded from discovery — it holds `base.html`,
  `sidebar.html`, `shared.css`, `shared.js`, and the shared error pages
  — the layout every page's templates extend, not a page itself.
- Adding a new page means adding one folder here (with its own
  README) — this file just needs one new line in the index below.
- Each page's `Blueprint(..., template_folder=".")` shares one flat
  Jinja template namespace with every other page — Flask resolves a
  template name to whichever blueprint registered it first if two
  pages use the same filename. Give each page's main template a
  **unique name** (e.g. `overview.html`, `account.html`), not the
  generic `view.html`, unless it's the only page using that name.
- A page can declare `PAGE_PERMISSION = <permission-string-or-None>` at
  module level: `None` means "visible to any logged-in account",
  otherwise the account needs that permission for the page to appear in
  `nav_pages` (the Overview tiles / sidebar links, computed by
  `register_pages()`'s context processor). `PAGE_PERMISSION` can also
  be a tuple/list of permission strings, meaning "visible if the
  account holds *any* of these" — for a page whose routes are gated by
  more than one permission and reachable with any one of them (e.g.
  `Logs`). `Overview` and `Auth` are always excluded from `nav_pages`
  regardless of their own `PAGE_PERMISSION` — they're not "other pages"
  to navigate to. `Account` and `Admin` are also excluded from
  `nav_pages` — they instead go into `account_menu_pages`, rendered by
  `__shared__/account_menu.html`'s dropdown (the avatar/username button
  in the sidebar footer and the Overview header), not the main nav.
- A page can also declare `PAGE_DESCRIPTION = "<one-line description>"`
  at module level — shown under the page's name on its Overview card.
  Optional; omit it (or leave it `None`) and the card just shows the
  icon and name.
- `__shared__/logo.png`, if present, replaces the 🏠 emoji next to
  "Overview" in the sidebar (checked once at boot in
  `register_pages()`). Drop a PNG there to brand the sidebar; remove it
  to go back to the emoji.
- A page can declare `PAGE_LAYOUT = "full"` (default, if omitted) or
  `PAGE_LAYOUT = "centered"` at module level. `"full"` lets the page's
  `<main>` fill the space next to the sidebar; `"centered"` caps it at
  960px and centers it (the old default look), for pages whose content
  reads better narrower. Resolved per-request by a context processor
  that matches `request.blueprint` against each page's declared
  layout, independent of authentication state (unlike `nav_pages`).

## Pages

- [`Auth/`](Auth/README.md) — the merged login/registration/logout flow.
- [`Admin/`](Admin/README.md) — role/permission/account administration
  and invite generation. Reached via the account menu, not `nav_pages`.
- [`Logs/`](Logs/README.md) — server and per-account activity/error
  log viewer. Visible in `nav_pages` to any account holding
  `logs.view` and/or `logs.errors.view`.
- [`Overview/`](Overview/README.md) — post-login landing page / page
  picker.
- [`Account/`](Account/README.md) — self-service profile view/edit.
  Reached via the account menu, not `nav_pages`.
- [`Sample/`](Sample/README.md) — minimal example page, kept so
  `nav_pages` / the Overview grid always has at least one real card and
  so new pages have something to copy.
- [`Chat/`](Chat/README.md) — LLM conversation UI, provider/extension
  selection, and per-user chat history. Gated by `chat.access`.
- [`Capabilities/`](Capabilities/README.md) — live MCP tool/resource
  browser and try-it console. Gated by `capabilities.view` /
  `capabilities.try`.
