---
name: chatapp-page-scaffold
description: Scaffold a new page in chat_app (the Flask frontend), or add a route/permission/tab to an existing page, following this repo's folder-per-page blueprint convention. Use whenever the user asks to add a new page, screen, tab, dashboard, or UI section to chat_app — even if they describe it only by what it should show or do ("I want a page where operators can see X", "add a screen for the watchers") without naming files or saying "page" explicitly. Also use when reviewing whether an existing page folder follows the repo's conventions (blueprint discovery, PAGE_PERMISSION/nav_pages gating, template naming, shared layout).
---

# chat_app page scaffolding

`chat_app/src/pages/` (this repo's Flask frontend — see
[chat_app/src/pages/README.md](../../chat_app/src/pages/README.md), the
source of truth this skill compresses) auto-discovers one Flask
blueprint per subfolder at boot (`register_pages()` in
`pages/__index__.py`). There's no central routes file to edit — adding
a page means adding a folder; deleting one removes it from routing and
navigation automatically. Ten pages exist today (`Auth`, `Admin`,
`Logs`, `Overview`, `Account`, `Sample`, `Chat`, `Capabilities`,
`Watchers`) — **`Sample/` is kept specifically as the copy-from
template**; start there.

**REQUIRED SUB-SKILL:** Use checking-the-catalog before writing any new
reusable function/class for this page (a formatter, a validator, a
client wrapper) — check `catalog_service` for an existing tagged
building block in chat_app/mcp_server/ai_agent before designing the
interface from scratch.

## Before scaffolding: is this a new page or a new route/tab on an existing one?

- **New page** (a new URL prefix, a new nav entry): full scaffold, steps below.
- **New route on an existing page** (another action inside `Capabilities` or `Watchers`, say): add the `@blueprint.route(...)` function to that page's existing `__index__.py` and, if it needs its own template, drop it alongside the page's other templates — no new folder, no `register_pages()` changes needed.
- **A tab within one page** (like `Watchers`'s tabs): still one page folder, one blueprint; the "tabs" are just sections of the same template switched client-side or by query param — check the existing page's `script.js`/template for the pattern already in use before inventing a new one.

## The discovery contract (why the boilerplate below is exactly this shape)

`discover_page_modules()` walks `src/pages/`, skips `__shared__` and
anything without an `__index__.py`, and imports
`src.pages.<Folder>.__index__` for every match — so:

- The folder name **must** match what you want the URL prefix and blueprint import path to be. `_url_prefix_for()` lowercases it (`Watchers` → `/watchers`), except `Overview` → `/` (the post-login landing page).
- `__index__.py` **must** expose a module-level `blueprint` (a `Blueprint` instance) — that's the only hard requirement; everything else below is convention, not enforced by code, but every existing page follows it and deviating breaks the generic rendering/nav logic other pages rely on.
- An empty `__init__.py` is still required (makes the folder importable as a package) — copy `Sample/__init__.py` (empty) rather than omitting it.

## Scaffold a new page

1. Copy `pages/Sample/` to `pages/<PageName>/` (PascalCase folder name — this becomes both the URL prefix and the blueprint's Python package name).
2. In `<PageName>/__index__.py`:

   ```python
   from flask import Blueprint, render_template

   from src.services.authz import register_permission, require_permission

   blueprint = Blueprint("<pagename>", __name__, template_folder=".")

   PAGE_PERMISSION = "<domain>.view"   # or None if any logged-in account should see it
   PAGE_DESCRIPTION = "One line shown on the Overview card."
   # PAGE_LAYOUT = "centered"          # default is "full"; set only if content reads better narrow

   register_permission("<domain>.view")


   @blueprint.route("/")
   @require_permission("<domain>.view")   # or @require_login() if PAGE_PERMISSION is None
   def index():
       return render_template("<pagename>.html")
   ```

   Blueprint name (first `Blueprint(...)` arg) is conventionally the lowercased folder name — it's what `url_for("<pagename>.index")` and template `{% block %}` overrides key off, and other pages use it consistently.

3. Give the main template a **globally unique filename** (`<pagename>.html`, not `view.html`/`index.html`) — every page's `Blueprint(..., template_folder=".")` shares one flat Jinja namespace, so a colliding name silently resolves to whichever blueprint registered first.

   ```html
   {% extends "base.html" %}
   {% block title %}<Page Title>{% endblock %}
   {% block sidebar %}{% include "sidebar.html" %}{% endblock %}
   {% block content %}
   <h1><Page Title></h1>
   {% endblock %}
   ```

4. `<PageName>/README.md` — URL prefix, routes table, permissions, templates, anything the page owns under its own `data/`/`configs/`. `Sample/README.md` is the minimal shape; `Capabilities/README.md` or `Watchers/README.md` for a page with several routes/tabs worth documenting individually.
5. Add one line to `pages/README.md`'s "Pages" list linking the new README — that's the only place a new page needs a manual mention.

That's it — no registry, no imports elsewhere. `register_pages()` picks it up on the next app boot because the folder exists and `__index__.py` has a `blueprint`.

## Permission gating (controls both access AND nav visibility)

- `PAGE_PERMISSION = None` → visible to any logged-in account (use `@require_login()` on routes, not `@require_permission`).
- `PAGE_PERMISSION = "some.permission"` → the account needs that permission for the page to appear in `nav_pages` (the Overview tiles / sidebar links). Gate the actual routes with `@require_permission("some.permission")` too — `PAGE_PERMISSION` only controls whether the link is *shown*, not whether the route is *reachable*; an ungated route behind a hidden link is still reachable by URL.
- `PAGE_PERMISSION = ("perm.a", "perm.b")` (tuple/list) → visible if the account holds *any* of these — for a page whose different routes are gated by different permissions (see `Logs/__index__.py`, which registers four separate `logs.*` permissions but is one page).
- Call `register_permission("x")` once at module level for any permission the page checks via `has_permission()` directly (not just through a route decorator) — `require_permission()` already registers its own argument, so don't double-register the same string both ways for the same permission.
- `Overview` and `Auth` never appear in `nav_pages` regardless of `PAGE_PERMISSION` (they're not "other pages" to navigate to). A page meant for the account-menu dropdown instead of the main sidebar nav (like `Account`/`Admin`) is special-cased by folder name in `pages/__index__.py`'s `_ACCOUNT_MENU_PAGES` — extending that list is a core-file change, not something a new page opts into on its own.

## Page-local static assets (only if the page needs its own CSS/JS)

`Sample` has none — its styling comes entirely from `__shared__/shared.css`.
If the new page needs page-specific behavior or styling, follow `Chat/__index__.py`'s pattern:

```python
blueprint = Blueprint(
    "<pagename>", __name__, template_folder=".", static_folder=".", static_url_path="/static"
)
```

then reference `url_for("<pagename>.static", filename="styles.css")` /
`script.js` from the template. Keep page-specific rules in the page's
own `styles.css`/`script.js`; only promote something to
`__shared__/shared.css`/`shared.js` once **at least two pages** need it
(see `pages/__shared__/README.md`).

If a route only serves `fetch()`/JS calls (no HTML form with a CSRF
token) — a JSON API endpoint the page's own script hits — set
`CSRF_EXEMPT = True` at module level (see `Chat/__index__.py`,
`Capabilities/__index__.py`, `Watchers/__index__.py`) so Flask-WTF's CSRF
check doesn't reject those calls; `register_pages()` reads this flag
and calls `csrf.exempt(blueprint)` for you.

## A route that streams a long-running result

If a route calls something slow enough that the user needs live
progress rather than a single blocking response (an AI turn, a
multi-step external call), don't invent a new mechanism — `Chat`
already has the reusable pieces: `chat_app/src/services/sse.py`
(`encode_sse()` + `stream_async_generator()`, bridging an async
generator onto a plain sync iterator since chat_app is WSGI/sync) and
`Chat/__index__.py`'s `chat_api()` as the reference route (`Response(event_source(), mimetype='text/event-stream', headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})` —
the three headers matter, they stop a proxy/browser from buffering the
whole stream before delivering it). `Chat/script.js`'s `send()` shows
the client side: `res.body.getReader()` + `TextDecoder`, splitting on
`\n\n` frame boundaries, dispatching on each event's `type`. Copy this
pattern rather than reinventing SSE framing for a new page.

## Logging

chat_app's logger factory is `src.utils.logging_setup.get_logger(__name__)` — a daily-rotating file logger writing to `logs/{MM}{DD}{YYYY}.txt` (see `chat_app/src/utils/README.md`). Get one logger per module at import time and log where something worth knowing happens — auth failures, external service calls, unexpected errors — not per-request boilerplate. This is a different mechanism from `mcp_server`'s root-logger setup (`configure_logging()`); the two apps deliberately don't share logging code (separate venvs — same convention as the rest of this repo's per-app duplication), so don't import one app's `logging_setup` from the other.

## Verify before calling it done

- Start the server (`chat_app/run.bat`), confirm the page loads at its URL prefix, appears (or correctly doesn't) in the sidebar for an account with/without the gating permission, and its Overview card shows the right description.
- `pytest` from `chat_app/` if the page has routes worth testing (see `tests/` for existing page-route test patterns).
- Check the browser console/network tab for a 403 from a route whose `@require_permission` string doesn't match what `PAGE_PERMISSION` (or the granted role) actually has — the two are easy to typo out of sync since nothing enforces they match.

## The Chat page is server-driven (don't hard-code capabilities into it)

- **Capability names.** The suggestion bar and welcome card take each capability's label from mcp_server (`capability_meta`
  -> `GET /capabilities` -> chat_app's `/chat/api/capability-labels`, backed by `tool_capabilities.known_labels()`); there is no
  name map in `script.js`. A new capability needs no chat_app change.
- **Command form widgets.** `command_form_modal.js` builds inputs from the tool's schema hints (`input`, `options_url`,
  `depends_on`, `sets`, `shows`, `initial`, ...). Add a widget or hint generically there and in `commands.py`'s `CommandParam`,
  never a `capability === '...'` branch. `tests/command_form_modal.test.cjs` covers it (`node --test`). See
  mcp-capability-scaffold's "Chat form inputs".
